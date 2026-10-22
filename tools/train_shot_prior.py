"""Distil verified pot/continuation rollouts into a cheap stroke-order prior."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import gzip
import json
from pathlib import Path
from time import monotonic
import numpy as np

from billiards.play import PlayService
from billiards.runout import Search,shot_options,stroke_settings
from billiards.shot_prior import FEATURES,VERSION,inputs
from billiards.human_stroke import load_policy
from tools.train_runout import layout


def generate(seed):
    service=PlayService(table_profile='cbsa_2017');state=layout(service,seed,max_balls=5)
    search=Search(service,trained=False,seconds=150,evaluations=400)
    options=shot_options(service,state,search.policy);chosen=[];seen=set()
    for o in options:
        if o['target'] not in seen:chosen.append(o);seen.add(o['target'])
        if len(chosen)==2:break
    if len(chosen)<2:chosen=options[:2]
    rows=[]
    for oi,o in enumerate(chosen):
        for si,s in enumerate(stroke_settings()):
            if search.stopped():break
            result=search.aimed(state,o,s[0],s[2],s[1])
            if search.stopped():break  # exhausted work is not a failed pot label
            step=result[1] if result else None
            utility=float(np.exp(-.20*step['cost'])) if step else 0.
            rows.append({'seed':seed,'option':oi,'setting':si,'x':inputs(service,state,o,s),
                         'y':utility,'verified_pot':bool(step),'target':o['target'],'pocket':o['pocket'],
                         'shot':step['shot'] if step else None,
                         'continuation_cost':step['continuation_cost'] if step else None,
                         'contact_cost':step['contact_cost'] if step else None})
    return rows,search.count


def split(seed):return 'test' if seed%6==0 else 'validation' if seed%6==5 else 'train'


def ranking(rows,predictions):
    groups={}
    for r,p in zip(rows,predictions):groups.setdefault((r['seed'],r['option']),[]).append((r,p))
    prior=[];baseline=[];oracle=[]
    for group in groups.values():
        prior.append(max(r['y'] for r,p in sorted(group,key=lambda q:-q[1])[:4]))
        baseline.append(max(r['y'] for r,p in sorted(group,key=lambda q:q[0]['setting'])[:4]))
        oracle.append(max(r['y'] for r,p in group))
    return {'options':len(groups),'top4_utility':float(np.mean(prior)),
            'baseline_top4_utility':float(np.mean(baseline)),'oracle_utility':float(np.mean(oracle))}


def fit(service,rows):
    sets={k:[r for r in rows if split(r['seed'])==k] for k in ('train','validation','test')}
    if any(len(v)<30 for v in sets.values()):raise ValueError('独立布局样本不足')
    x=np.asarray([r['x'] for r in sets['train']]);y=np.asarray([r['y'] for r in sets['train']])
    mean=x.mean(0);scale=np.maximum(.05,x.std(0));z=(x-mean)/scale
    vx=(np.asarray([r['x'] for r in sets['validation']])-mean)/scale
    vy=np.asarray([r['y'] for r in sets['validation']])
    rng=np.random.default_rng(20261022)
    params=[rng.normal(0,.12,(len(FEATURES),24)),np.zeros(24),rng.normal(0,.12,24),np.zeros(1)]
    m=[np.zeros_like(p) for p in params];v=[np.zeros_like(p) for p in params]
    sigmoid=lambda a:1/(1+np.exp(-np.clip(a,-30,30)))
    best=None;best_quality=(-1.,-float('inf'));trace=[]
    for epoch in range(1,1601):
        w1,b1,w2,b2=params;h=np.tanh(z@w1+b1);p=sigmoid(h@w2+b2[0]);err=(p-y)/len(y)
        dh=err[:,None]*w2*(1-h*h)
        grads=[z.T@dh+.0005*w1,dh.sum(0),h.T@err+.0005*w2,np.asarray([err.sum()])]
        for i,g in enumerate(grads):
            m[i]=.9*m[i]+.1*g;v[i]=.999*v[i]+.001*g*g
            params[i]-=.006*m[i]/(1-.9**epoch)/(np.sqrt(v[i]/(1-.999**epoch))+1e-8)
        if epoch%20==0:
            w1,b1,w2,b2=params;vp=sigmoid(np.tanh(vx@w1+b1)@w2+b2[0])
            mse=float(np.mean((vp-vy)**2));rank=ranking(sets['validation'],vp)
            quality=(rank['top4_utility'],-mse)
            trace.append({'epoch':epoch,'validation_mse':mse,**rank})
            if quality>best_quality:best_quality=quality;best=[p.copy() for p in params];selected=epoch
    w1,b1,w2,b2=best;metrics={}
    for name,items in sets.items():
        xx=(np.asarray([r['x'] for r in items])-mean)/scale;yy=np.asarray([r['y'] for r in items])
        pred=sigmoid(np.tanh(xx@w1+b1)@w2+b2[0])
        metrics[name]={'samples':len(items),'seeds':sorted({r['seed'] for r in items}),
                       'mse':float(np.mean((pred-yy)**2)),**ranking(items,pred)}
    model={'version':VERSION,'features':FEATURES,'physics_signature':service.signature,
           'human_policy':load_policy(service),'mean':mean.tolist(),'scale':scale.tolist(),
           'w1':w1.tolist(),'b1':b1.tolist(),'w2':w2.tolist(),'b2':float(b2[0]),
           'training':{'selected_epoch':selected,'epochs':1600,'metrics':metrics,
                       'label':'Verified pot utility exp(-0.20 * cost), including next-shot comfort and secondary-contact cost; failed/unreliable results zero.',
                       'limits':'Small synthetic pilot; ranks candidates only. Every recommendation still requires full physics and rule validation.'}}
    return model,trace


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--layouts',type=int,default=72)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--reuse',action='store_true')
    args=parser.parse_args();service=PlayService(table_profile='cbsa_2017')
    directory=service.root/'training'/'ai_stage4';directory.mkdir(parents=True,exist_ok=True)
    path=directory/'shot-prior-dataset.json.gz';started=monotonic()
    if args.reuse:data=json.loads(gzip.decompress(path.read_bytes()).decode('utf8'))
    else:
        rows=[];simulations=0
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            jobs=[pool.submit(generate,s) for s in range(720001,720001+args.layouts)]
            for i,f in enumerate(as_completed(jobs),1):
                r,n=f.result();rows+=r;simulations+=n
                if i%6==0:print(json.dumps({'layouts':i,'rows':len(rows),'simulations':simulations,'seconds':round(monotonic()-started,1)}),flush=True)
        rows.sort(key=lambda r:(r['seed'],r['option'],r['setting']))
        data={'source':'shared_physics_offline_stroke_rollouts','layouts':args.layouts,
              'physics_signature':service.signature,'human_policy':load_policy(service),'simulations':simulations,'rows':rows}
        path.write_bytes(gzip.compress((json.dumps(data,ensure_ascii=False)+'\n').encode('utf8'),compresslevel=9,mtime=0))
    assert data['physics_signature']==service.signature and data['human_policy']==load_policy(service)
    model,trace=fit(service,data['rows'])
    model['training']['dataset_sha256']=hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest()
    model['training']['dataset_file']='training/ai_stage4/shot-prior-dataset.json.gz'
    (service.root/'configs'/'ai_shot_prior.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    report={'model':model,'trace':trace,'simulations':data['simulations'],'elapsed':monotonic()-started}
    (directory/'shot-prior-training.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(model['training'],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
