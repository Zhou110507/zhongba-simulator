"""Generate constrained simulation rollouts, train a small NumPy value network.

Run with python -m tools.train_runout. Splits are by initial layout, never by
individual stroke. Labels mean completion under this bounded rollout policy,
not professional success or the existence/nonexistence of a clear.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from time import monotonic

import numpy as np

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.model import Ball, Vec2
from billiards.play import PlayService
from billiards.pockets import unsupported_pocket, validate_position, outline
from billiards.runout import FEATURE_NAMES, MODEL_VERSION, Search, features, shot_options


def layout(service, seed):
    rng=np.random.default_rng(seed)
    state=GameStore(service).new({'seed':seed,'ai_player':1})
    state.update(turn=1,groups=['stripe','solid'],is_break=False,ball_in_hand=None,needs_placement=False)
    balls=[]
    count=int(rng.integers(1,4))
    ids=['cue',*[str(i) for i in range(1,count+1)],'8','9','10']
    for key in ids:
        for _ in range(1000):
            p=Vec2(float(rng.uniform(.08,2.46)),float(rng.uniform(.08,1.19)))
            if key=='cue' and seed%4==0:p=Vec2(float(rng.uniform(.07,.14)),float(rng.uniform(.18,1.09)))
            if key=='1' and seed%5==0:
                pocket=outline(service.table).pockets[int(rng.integers(0,6))]
                p=pocket.mouth-pocket.outward*float(rng.uniform(.15,.4))+pocket.tangent*float(rng.uniform(-.1,.1))
            if key=='10' and seed%4==1:
                p=balls[0].position+Vec2(float(rng.uniform(-.15,.15)),float(rng.uniform(-.15,.15)))
            candidate=Ball(key,p,spec=service.ball_spec)
            try:
                validate_position(candidate,service.table)
            except ValueError:continue
            if unsupported_pocket(candidate,service.table):continue
            if all((p-b.position).norm()>.09 for b in balls):
                balls.append(candidate);break
        else:raise RuntimeError('failed to generate layout')
    state['scene']=service.snapshot(balls,ShotInput(0,1.1))
    return state


def baseline_value(service,state,policy):
    if state['winner']==state['turn']:return 10.
    options=shot_options(service,state,policy)
    return -options[0]['cost']+.12*min(3,len({o['target'] for o in options})) if options else -4.


def generate(service, count, output):
    rows=[]; branches=[]; started=monotonic(); simulations=0
    for index in range(count):
        seed=17001+index
        state=layout(service,seed)
        search=Search(service,seconds=90,evaluations=1200,trained=False)
        root=search.candidates(state,attempts=16)
        root.sort(key=lambda n:n[1]['cost']-.8*baseline_value(service,n[0],search.policy))
        variants=[];seen=set()
        for after,step in root:
            key=(step['target'],step['pocket'],step['shot']['tip_y'])
            if key in seen:continue
            seen.add(key);variants.append((after,step))
            if len(variants)==4:break
        if not variants:
            rows.append({'layout_seed':seed,'x':features(service,state,search.policy).tolist(),'y':0.})
        for after,step in variants:
            initial=deepcopy(after);states=[];route=[step]
            while after['phase']=='playing' and after['turn']==1 and not search.stopped():
                states.append(features(service,after,search.policy).tolist())
                pool=search.candidates(after,attempts=10)
                if not pool:break
                pool.sort(key=lambda n:n[1]['cost']-.8*baseline_value(service,n[0],search.policy))
                after,next_step=pool[0];route.append(next_step)
                if len(route)>=4:break
            if search.stopped():continue
            clear=int(after['winner']==1)
            def quality(start):
                future=route[start:]
                effort=sum(s['cost'] for s in future)/max(1,len(future))
                return float((1. if clear else .10*min(1.,len(future)/3))*np.exp(-.55*effort))
            # Include the post-first-shot feature even if it was already terminal.
            x=features(service,initial,search.policy).tolist()
            rows.append({'layout_seed':seed,'x':x,'y':quality(1)})
            for offset,item in enumerate(states[1:],2):rows.append({'layout_seed':seed,'x':item,'y':quality(offset)})
            branches.append({'layout_seed':seed,'x':x,'clear':clear,
                             'quality':quality(1),'mean_cost':sum(s['cost'] for s in route)/len(route),
                             'baseline':step['cost']-.8*baseline_value(service,initial,search.policy),
                             'steps':[s['target'] for s in route]})
        simulations+=search.count
        if index%4==0 or index==count-1:
            print(json.dumps({'layouts':index+1,'total':count,'samples':len(rows),
                              'simulations':simulations,'seconds':round(monotonic()-started,1)}),flush=True)
    data={'version':1,'source':'synthetic_shared_physics_rollouts','layout_count':count,
          'physics_signature':service.signature,'human_policy':search.policy,'features':FEATURE_NAMES,
          'simulations':simulations,'rows':rows,'branches':branches,
          'label_definition':'Bounded rollout completion discounted by potting geometric tolerance first (both travel distances, cut angle and pocket entry), then ordinary position effort and cue access; small partial-progress credit. Not measured human probabilities or proof of impossibility.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    return data


def sigmoid(x):return 1/(1+np.exp(-np.clip(x,-30,30)))


def metrics(y,p):
    return {'samples':len(y),'mean_target':round(float(np.mean(y)),4),
            'mse':round(float(np.mean((p-y)**2)),5),
            'log_loss':round(float(-np.mean(y*np.log(np.clip(p,1e-8,1))+(1-y)*np.log(np.clip(1-p,1e-8,1)))),5)}


def train(service,data,output):
    seeds=sorted({r['layout_seed'] for r in data['rows']})
    # Fixed layout-level split before fitting/normalization; no shot leakage.
    assignments={s:('test' if (s-17001)%6==5 else 'validation' if (s-17001)%6==4 else 'train') for s in seeds}
    sets={k:[r for r in data['rows'] if assignments[r['layout_seed']]==k] for k in ('train','validation','test')}
    if any(len(v)<8 for v in sets.values()):raise ValueError('样本不足，需要更多独立布局')
    x=np.asarray([r['x'] for r in sets['train']]);y=np.asarray([r['y'] for r in sets['train']])
    mean=x.mean(axis=0);scale=np.maximum(x.std(axis=0),.05);z=(x-mean)/scale
    vx=(np.asarray([r['x'] for r in sets['validation']])-mean)/scale
    vy=np.asarray([r['y'] for r in sets['validation']])
    rng=np.random.default_rng(20261021)
    params=[rng.normal(0,.15,(len(FEATURE_NAMES),12)),np.zeros(12),rng.normal(0,.15,12),np.zeros(1)]
    m=[np.zeros_like(p) for p in params];v=[np.zeros_like(p) for p in params]
    best=None;best_loss=float('inf');trace=[];decay=.002
    for epoch in range(1,1601):
        w1,b1,w2,b2=params;h=np.tanh(z@w1+b1);p=sigmoid(h@w2+b2[0]);err=(p-y)/len(y)
        dh=(err[:,None]*w2)*(1-h*h)
        grads=[z.T@dh+decay*w1,dh.sum(axis=0),h.T@err+decay*w2,np.asarray([err.sum()])]
        for i,g in enumerate(grads):
            m[i]=.9*m[i]+.1*g;v[i]=.999*v[i]+.001*g*g
            params[i]-=.008*(m[i]/(1-.9**epoch))/(np.sqrt(v[i]/(1-.999**epoch))+1e-8)
        if epoch%20==0:
            w1,b1,w2,b2=params;vp=sigmoid(np.tanh(vx@w1+b1)@w2+b2[0])
            loss=metrics(vy,vp)['log_loss']
            trace.append({'epoch':epoch,'train':metrics(y,p),'validation':metrics(vy,vp)})
            if loss<best_loss:best_loss=loss;best=[p.copy() for p in params];best_epoch=epoch
    w1,b1,w2,b2=best
    def predict(a):return sigmoid(np.tanh(((a-mean)/scale)@w1+b1)@w2+b2[0])
    report={}
    prior=float(y.mean())
    for name,items in sets.items():
        xx=np.asarray([r['x'] for r in items]);yy=np.asarray([r['y'] for r in items])
        report[name]={'model':metrics(yy,predict(xx)),
                      'constant_baseline':metrics(yy,np.full(len(yy),prior)),
                      'layout_seeds':[s for s in seeds if assignments[s]==name]}
    selection={}
    for name in sets:
        groups={}
        for b in data['branches']:
            if assignments[b['layout_seed']]==name:groups.setdefault(b['layout_seed'],[]).append(b)
        baseline=learned=oracle=0;baseline_quality=[];learned_quality=[];baseline_cost=[];learned_cost=[]
        for branches in groups.values():
            old=min(branches,key=lambda b:b['baseline']);baseline+=old['clear']
            # Same candidate set; compare the effect of the learned value only.
            new=min(branches,key=lambda b:b['baseline']-1.2*float(predict(np.asarray(b['x']))));learned+=new['clear']
            baseline_quality.append(old['quality']);learned_quality.append(new['quality'])
            baseline_cost.append(old['mean_cost']);learned_cost.append(new['mean_cost'])
            oracle+=max(b['clear'] for b in branches)
        selection[name]={'layouts_with_candidates':len(groups),'baseline_clears':baseline,
                         'trained_ranking_clears':learned,'candidate_set_best_possible':oracle,
                         'baseline_quality':round(float(np.mean(baseline_quality)),4),
                         'trained_quality':round(float(np.mean(learned_quality)),4),
                         'baseline_mean_difficulty':round(float(np.mean(baseline_cost)),4),
                         'trained_mean_difficulty':round(float(np.mean(learned_cost)),4)}
    model={'version':MODEL_VERSION,'features':FEATURE_NAMES,'physics_signature':service.signature,
           'human_policy':data['human_policy'],'mean':mean.tolist(),'scale':scale.tolist(),
           'w1':w1.tolist(),'b1':b1.tolist(),'w2':w2.tolist(),'b2':float(b2[0]),
           'training':{'seed':20261021,'selected_epoch':best_epoch,'total_epochs':1600,
                       'layout_count':data['layout_count'],'sample_count':len(data['rows']),
                       'dataset_sha256':hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),
                       'source':data['source'],'label_definition':data['label_definition'],
                       'metrics':report,'candidate_ranking':selection,
                       'limitations':'Pilot synthetic data. Scores are rollout-policy values, not calibrated human success probabilities. No professional video training.'}}
    output.write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report_path=service.root/'artifacts'/'ai-training'/'report.json'
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps({'training':model['training'],'trace':trace},ensure_ascii=False,indent=2),encoding='utf-8')
    reproducible=service.root/'training'/'ai_stage1'
    reproducible.mkdir(parents=True,exist_ok=True)
    (reproducible/'dataset.json').write_text(json.dumps(data,ensure_ascii=False)+'\n',encoding='utf-8')
    (reproducible/'training-report.json').write_text(report_path.read_text(encoding='utf-8'),encoding='utf-8')
    print(json.dumps(model['training'],ensure_ascii=False,indent=2),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--layouts',type=int,default=180)
    parser.add_argument('--reuse',action='store_true');args=parser.parse_args()
    service=PlayService(table_profile='cbsa_2017')
    dataset=service.root/'artifacts'/'ai-training'/'rollouts.json'
    if args.reuse and not dataset.is_file():dataset=service.root/'training'/'ai_stage1'/'dataset.json'
    data=json.loads(dataset.read_text(encoding='utf-8')) if args.reuse and dataset.is_file() else generate(service,args.layouts,dataset)
    from billiards.human_stroke import load_policy
    if data['physics_signature']!=service.signature or data['human_policy']!=load_policy(service):
        raise ValueError('训练数据物理或普通杆法限制不一致')
    train(service,data,service.root/'configs'/'ai_value_model.json')


if __name__=='__main__':main()
