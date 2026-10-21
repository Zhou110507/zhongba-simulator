"""Select a reusable break book across random positive rack micro-gaps."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
from dataclasses import replace
import json
from math import hypot
from pathlib import Path
import random

from billiards.break_policy import VERSION,profiles
from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.model import Vec2
from billiards.play import PlayService
from billiards.runout import Search


def trial(profile,seed):
    service=PlayService(table_profile='cbsa_2017')
    gap=random.Random(seed+700000).uniform(.10,.50)
    game=GameStore(service).new({'seed':seed,'gap_mm':gap,'breaker':0,'ai_player':0})
    game['scene']['balls'][0]['position']=deepcopy(profile['position'])
    initial=game['scene']['balls']
    gap_min=min(hypot(a['position']['x']-b['position']['x'],a['position']['y']-b['position']['y'])-
                a['spec']['radius']-b['spec']['radius'] for i,a in enumerate(initial[1:]) for b in initial[1:][i+1:])*1000
    assert gap_min>0,(seed,gap_min)
    search=Search(service,trained=False,seconds=45,evaluations=2)
    value=search.forward(game,ShotInput(**profile['shot']),opening=True)
    if value is None:return {'profile':profile['id'],'seed':seed,'gap_mm':gap,'min_pair_gap_mm':gap_min,'complete':False,'reward':-2.}
    result,after,_=value
    targets=[b for b in result.final if b.id!='cue']
    potted=[b.id for b in targets if b.pocket is not None]
    moved=sum(b.pocket is not None or (b.position-Vec2(**next(a['position'] for a in initial if a['id']==b.id))).norm()>.35 for b in targets)
    pairs=sum(a.pocket is None and b.pocket is None and (a.position-b.position).norm()<.13
              for i,a in enumerate(targets) for b in targets[i+1:])
    scratch=any(b.id=='cue' and b.pocket is not None for b in result.final)
    fouls=after['last_decision']['fouls']
    reward=1.4*bool(potted)+.2*min(3,len(potted))+.7*moved/15-.02*pairs-1.5*bool(fouls)-1.5*scratch
    return {'profile':profile['id'],'seed':seed,'gap_mm':gap,'min_pair_gap_mm':gap_min,
            'complete':True,'potted':potted,'moved_over_350mm':moved,'cluster_pairs':pairs,
            'scratch':scratch,'fouls':fouls,'reward':reward}


def summarize(rows):
    done=[r for r in rows if r['complete']];n=max(1,len(rows))
    return {'racks':len(rows),'complete':len(done),'pot_rate':sum(bool(r['potted']) for r in done)/n,
            'scratch_rate':sum(r['scratch'] for r in done)/n,
            'legal_rate':sum(not r['fouls'] for r in done)/n,
            'mean_moved':sum(r['moved_over_350mm'] for r in done)/n,
            'mean_reward':sum(r['reward'] for r in rows)/n}


def batch(candidates,seeds,workers):
    rows=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs=[pool.submit(trial,p,s) for p in candidates for s in seeds]
        for f in as_completed(jobs):
            rows.append(f.result())
            if len(rows)%12==0 or len(rows)==len(jobs):print(json.dumps({'break_trials':len(rows),'total':len(jobs)}),flush=True)
    return sorted(rows,key=lambda r:(r['profile'],r['seed']))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    service=PlayService(table_profile='cbsa_2017');candidates=profiles(service)
    training=batch(candidates,range(91001,91013),args.workers)
    ranked=sorted(candidates,key=lambda p:summarize([r for r in training if r['profile']==p['id']])['mean_reward'],reverse=True)
    selected=ranked[:2]
    validation=batch(selected,range(92001,92013),args.workers)
    held=batch(selected,range(93001,93025),args.workers)
    model={'version':VERSION,'physics_signature':service.signature,'selected':selected,
           'method':'finite-action offline reward selection; no live rack inspection',
           'random_gaps_mm':[.1,.5],'train_seeds':list(range(91001,91013)),
           'validation_seeds':list(range(92001,92013)),'held_out_seeds':list(range(93001,93025)),
           'training':{p['id']:summarize([r for r in training if r['profile']==p['id']]) for p in candidates},
           'held_out':{p['id']:summarize([r for r in held if r['profile']==p['id']]) for p in selected},
           'limitations':'Synthetic random-gap racks; tiny holdout, no real table probability claim. Cue-head speed stays within existing 5 m/s cap; no physics or speed mapping adjustment.'}
    package=service.root/'training'/'ai_stage3';package.mkdir(parents=True,exist_ok=True)
    (service.root/'configs'/'ai_break_model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (package/'break-training.json').write_text(json.dumps({'model':model,'trials':training,'validation_trials':validation,'held_out_trials':held},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'selected':selected,'held_out':model['held_out']}),flush=True)


if __name__=='__main__':main()
