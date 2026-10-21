"""Train escape/safety values from legal contact and bounded opponent replies."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
import hashlib
import json

import numpy as np

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.model import Ball,Vec2
from billiards.play import PlayService
from billiards.runout import Search
from billiards.tactics import FEATURES,VERSION,contact_candidates
from tools.train_runout import layout


def tactical_layout(service,seed):
    rng=np.random.default_rng(seed)
    if seed%3==2:return layout(service,seed,max_balls=3)
    state=GameStore(service).new({'scenario':'ai_endgame'})
    if seed%3==0:
        y=float(rng.uniform(.45,.8))
        points=[('cue',.48,y),('1',1.86,y),('9',1.12,y),('10',.95,.22),('8',2.25,1.05)]
    else:
        dx=float(rng.uniform(-.10,.10))
        points=[('cue',.45,.65),('1',1.3+dx,.63),('2',1.85,.75),('9',1.915,.75),('10',.7,.95),('8',2.05,.35)]
    state['scene']=service.snapshot([Ball(k,Vec2(x,y),spec=service.ball_spec) for k,x,y in points],ShotInput(0,1.1))
    if seed%2==0:
        for b in state['scene']['balls']:
            if b['id'] not in ('cue','8'):
                n=int(b['id']);b['id']=str(n+8 if n<8 else n-8)
        state['groups']=['solid','stripe']
    return state


def generate_case(seed):
    service=PlayService(table_profile='cbsa_2017');state=tactical_layout(service,seed)
    search=Search(service,trained=False,seconds=18,evaluations=180)
    candidates=contact_candidates(service,state,search,attempts=120)
    selected=[]
    for legal in (False,True):
        pool=[r for r in candidates if r['legal']==legal]
        if pool:
            indices=np.linspace(0,len(pool)-1,min(10,len(pool)),dtype=int)
            selected.extend(pool[int(i)] for i in indices)
    rows=[];simulations=search.count
    for row in selected:
        x=np.asarray(row['x']);after=deepcopy(row['after']);reply_pot=False
        if row['legal'] and not row['pot'] and after['phase']=='playing':
            reply=Search(service,trained=False,seconds=3,evaluations=30)
            pool=reply.candidates(after,attempts=6)
            reply_pot=bool(pool);simulations+=reply.count
        y=(.43+.23*x[8]+.15*x[5]+.12*max(0.,x[9])-.42*reply_pot if row['legal'] else .02)
        if row['legal'] and row['pot']:y=.72+.2*x[5]
        if x[15]:y=1.
        if x[4]:y=0.
        rows.append({'layout_seed':seed,'x':row['x'],'y':float(np.clip(y,0.,1.)),
                     'shot':row['shot'],'legal':row['legal'],'pot':row['pot'],
                     'opponent_reply_pot_found':reply_pot,'cushions':row['cushions']})
    return rows,simulations


def fit(service,data):
    rows=data['rows'];split=lambda seed:'test' if ((seed-310001)//3)%6==5 else 'validation' if ((seed-310001)//3)%6==4 else 'train'
    sets={k:[r for r in rows if split(r['layout_seed'])==k] for k in ('train','validation','test')}
    x=np.asarray([r['x'] for r in sets['train']]);y=np.asarray([r['y'] for r in sets['train']])
    mean=x.mean(0);scale=np.maximum(x.std(0),.05);z=(x-mean)/scale
    vx=(np.asarray([r['x'] for r in sets['validation']])-mean)/scale;vy=np.asarray([r['y'] for r in sets['validation']])
    rng=np.random.default_rng(20261022)
    params=[rng.normal(0,.1,(len(FEATURES),12)),np.zeros(12),rng.normal(0,.1,12),np.zeros(1)]
    m=[np.zeros_like(p) for p in params];v=[np.zeros_like(p) for p in params]
    sigmoid=lambda a:1/(1+np.exp(-np.clip(a,-30,30)))
    best=None;loss=float('inf');trace=[]
    for epoch in range(1,1001):
        w1,b1,w2,b2=params;h=np.tanh(z@w1+b1);p=sigmoid(h@w2+b2[0]);err=(p-y)/len(y)
        dh=err[:,None]*w2*(1-h*h)
        grads=[z.T@dh+.002*w1,dh.sum(0),h.T@err+.002*w2,np.asarray([err.sum()])]
        for i,g in enumerate(grads):
            m[i]=.9*m[i]+.1*g;v[i]=.999*v[i]+.001*g*g
            params[i]-=.008*(m[i]/(1-.9**epoch))/(np.sqrt(v[i]/(1-.999**epoch))+1e-8)
        if epoch%20==0:
            w1,b1,w2,b2=params;pred=sigmoid(np.tanh(vx@w1+b1)@w2+b2[0]);e=float(np.mean((pred-vy)**2))
            trace.append({'epoch':epoch,'validation_mse':e})
            if e<loss:loss=e;best=[p.copy() for p in params];chosen=epoch
    w1,b1,w2,b2=best;metrics={}
    for name,items in sets.items():
        xx=np.asarray([r['x'] for r in items]);yy=np.asarray([r['y'] for r in items]);p=sigmoid(np.tanh((xx-mean)/scale@w1+b1)@w2+b2[0])
        metrics[name]={'samples':len(items),'layout_seeds':sorted({r['layout_seed'] for r in items}),
                       'mse':float(np.mean((p-yy)**2)),'constant_mse':float(np.mean((y.mean()-yy)**2))}
    from billiards.human_stroke import load_policy
    model={'version':VERSION,'physics_signature':service.signature,'human_policy':load_policy(service),'features':FEATURES,
           'mean':mean.tolist(),'scale':scale.tolist(),'w1':w1.tolist(),'b1':b1.tolist(),'w2':w2.tolist(),'b2':float(b2[0]),
           'training':{'selected_epoch':chosen,'epochs':1000,'metrics':metrics,
                       'dataset_sha256':hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),
                       'limitations':'Synthetic contact outcomes and bounded opponent reply search, not measured human safety quality.'}}
    (service.root/'configs'/'ai_tactics_model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return {'model':model,'trace':trace}


def main():
    service=PlayService(table_profile='cbsa_2017');rows=[];simulations=0
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(generate_case,s) for s in range(310001,310073)]
        for i,f in enumerate(as_completed(jobs),1):
            r,n=f.result();rows+=r;simulations+=n
            if i%8==0:print(json.dumps({'tactics_layouts':i,'samples':len(rows),'simulations':simulations}),flush=True)
    rows.sort(key=lambda r:(r['layout_seed'],r['shot']['angle_deg'],r['shot']['cue_speed']))
    data={'features':FEATURES,'physics_signature':service.signature,'layout_count':72,'simulations':simulations,'rows':rows}
    package=service.root/'training'/'ai_stage3';package.mkdir(parents=True,exist_ok=True)
    (package/'tactics-dataset.json').write_text(json.dumps(data,ensure_ascii=False)+'\n',encoding='utf8')
    report=fit(service,data)
    (package/'tactics-training.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report['model']['training']),flush=True)


if __name__=='__main__':main()
