"""Frozen-policy runout practice: replan after every actual adjudicated stroke.

Never feeds evaluation seeds back into training. Includes both groups and full
seven-ball sets; failures and partial runs are recorded, never called clears.
"""
import argparse
from copy import deepcopy
import json
from time import monotonic

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.human_stroke import check_stroke, load_policy
from billiards.play import PlayService
from billiards.rules import legal_ids
from billiards.runout import Search, MODEL_VERSION, shot_options
from tools.train_runout import layout


def practice(service, initial, *, seconds=20, evaluations=1000):
    games=GameStore(service);current=deepcopy(initial)
    games.games[current['id']]=deepcopy(current)
    owner=current['turn'];policy=load_policy(service)
    rows=[];reason='stroke_limit';started=monotonic()
    for _ in range(9):
        result=Search(service,seconds=seconds,evaluations=evaluations).solve(current)
        if not result['routes']:
            reason='no_verified_pot';break
        step=deepcopy(result['routes'][0]['steps'][0])
        balls,_=service.decode(current['scene'])
        assert check_stroke(balls,ShotInput(**step['shot']),service.table,policy)['allowed']
        value=games.action({'id':current['id'],'revision':current['revision'],
                            'action':'shoot','shot':step['shot']})
        assert value['complete'] and value['rule_committed']
        current=value['game_after']
        assert not current['last_decision']['fouls']
        actual=next(b for b in current['scene']['balls'] if b['id']==step['target'])
        assert actual['pocket']==step['pocket']
        cue=next(b for b in current['scene']['balls'] if b['id']=='cue')
        assert abs(cue['position']['x']-step['cue_final']['x'])<1e-7
        assert abs(cue['position']['y']-step['cue_final']['y'])<1e-7
        options=shot_options(service,current,policy) if current['phase']=='playing' else []
        step.update(planning_evaluations=result['evaluations'],actual_revision=current['revision'],
                    next_best_cost=options[0]['cost'] if options else None)
        rows.append(step)
        if current['phase']=='finished':reason='cleared' if current['winner']==owner else 'lost';break
        if current['turn']!=owner:reason='turn_ended';break
    return {'initial_scene':initial['scene'],'initial_groups':initial['groups'],
            'own_ball_count':len(legal_ids(initial)),'clear':reason=='cleared','stop_reason':reason,
            'steps':rows,'all_replays_valid':True,'seconds':round(monotonic()-started,2)}


def practice_case(case, seconds, evaluations):
    name,state=case
    return {'case':name,**practice(PlayService(table_profile='cbsa_2017'),state,
                                  seconds=seconds,evaluations=evaluations)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--layouts',type=int,default=16)
    parser.add_argument('--seed',type=int,default=68001);parser.add_argument('--seconds',type=float,default=20)
    parser.add_argument('--evaluations',type=int,default=1000);parser.add_argument('--include-feedback',action='store_true')
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();service=PlayService(table_profile='cbsa_2017');rows=[]
    cases=[]
    for i in range(args.layouts):
        seed=args.seed+i
        state=layout(service,seed,max_balls=7,ball_count=7 if i%4==3 else 1+i%3)
        if i%8==7:
            for ball in state['scene']['balls']:
                if ball['id'] not in ('cue','8'):
                    key=int(ball['id']);ball['id']=str(key+8 if key<=7 else key-8)
            state['groups']=list(reversed(state['groups']))
        cases.append((str(seed),state))
    if args.include_feedback:
        reference=json.loads((service.root/'training'/'ai_stage2'/'feedback-reference.json').read_text(encoding='utf-8'))
        state=GameStore(service).new({'scenario':'ai_endgame'})
        state.update(scene=reference['source_scene'],groups=reference['source_groups'],
                     turn=reference['source_turn'],ai_player=reference['source_ai_player'])
        cases.append(('user-feedback-held-out',state))
    from concurrent.futures import ProcessPoolExecutor,as_completed
    with ProcessPoolExecutor(max_workers=max(1,args.workers)) as executor:
        jobs=[executor.submit(practice_case,case,args.seconds,args.evaluations) for case in cases]
        for job in as_completed(jobs):
            row=job.result();rows.append(row)
            print(json.dumps({k:row[k] for k in ('case','own_ball_count','clear','stop_reason','seconds')}
                             |{'strokes':len(row['steps'])},ensure_ascii=True),flush=True)
    rows.sort(key=lambda r:r['case'])
    steps=[s for r in rows for s in r['steps']]
    output={'model':MODEL_VERSION,'seconds_per_decision':args.seconds,'evaluations_per_decision':args.evaluations,
            'scope':'Frozen policy, held-out seeds, replan after every real GameStore.action; synthetic only, not human success probabilities',
            'summary':{'layouts':len(rows),'clears':sum(r['clear'] for r in rows),
                       'strokes':len(steps),'three_plus_rail_strokes':sum(s['cue_cushions']>=3 for s in steps),
                       'side_spin_strokes':sum(abs(s['shot']['tip_x'])>.02 for s in steps),
                       'clean_pots':sum(s['clean_pot'] for s in steps),
                       'mean_shot_cost':round(sum(s['cost'] for s in steps)/max(1,len(steps)),4),
                       'long_object_shots':sum(s['object_distance_mm']>1200 for s in steps),
                       'rear_rail_restricted_shots':sum(bool(s['human']['notes']) for s in steps),
                       'all_replays_valid':all(r['all_replays_valid'] for r in rows)},'rows':rows}
    path=service.root/'training'/'ai_stage2'/'self-practice.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(output['summary'],ensure_ascii=True),flush=True)


if __name__=='__main__':main()
