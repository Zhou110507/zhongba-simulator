"""Independent equal-budget baseline/model comparisons and replay verification."""
import argparse
from copy import deepcopy
import json
from time import monotonic

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.human_stroke import check_stroke, load_policy
from billiards.play import PlayService
from billiards.runout import Search
from tools.train_runout import layout


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--layouts',type=int,default=12)
    parser.add_argument('--seed',type=int,default=78001)
    parser.add_argument('--evaluations',type=int,default=1800)
    parser.add_argument('--seconds',type=float,default=30)
    args=parser.parse_args();service=PlayService(table_profile='cbsa_2017');policy=load_policy(service)
    rows=[];started=monotonic()
    for seed in range(args.seed,args.seed+args.layouts):
        initial=layout(service,seed)
        row={'seed':seed}
        for name,trained in (('baseline',False),('trained',True)):
            result=Search(service,seconds=args.seconds,evaluations=args.evaluations,trained=trained).solve(initial)
            route=result['routes'][0] if result['routes'] else None
            valid=True;current=deepcopy(initial);costs=[]
            games=GameStore(service)
            games.games[current['id']]=deepcopy(current)
            if route:
                for step in route['steps']:
                    balls,_=service.decode(current['scene'])
                    valid &= check_stroke(balls,ShotInput(**step['shot']),service.table,policy)['allowed']
                    value=games.action({'id':current['id'],'revision':current['revision'],
                                        'action':'shoot','shot':step['shot']})
                    valid &= value['complete'] and value['rule_committed']
                    current=value['game_after'];valid &= not current['last_decision']['fouls']
                    costs.append(step['cost'])
                valid &= bool(route['clear_verified'])==(current['winner']==initial['turn'])
            assert valid, (seed,name)
            row[name]={'clear':bool(route and route['clear_verified']),
                       'steps':len(route['steps']) if route else 0,
                       'mean_difficulty':sum(costs)/len(costs) if costs else None,
                       'evaluations':result['evaluations'],'replay_valid':valid,
                       'first_distance_mm':route['steps'][0]['distance_mm'] if route else None,
                       'first_cut':route['steps'][0]['cut_degrees'] if route else None,
                       'perturbations':route.get('perturbations') if route else None}
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    summary={}
    for name in ('baseline','trained'):
        found=[r[name] for r in rows if r[name]['steps']]
        summary[name]={'layouts':len(rows),'routes':len(found),'clears':sum(r['clear'] for r in found),
                       'mean_difficulty':sum(r['mean_difficulty'] for r in found)/len(found) if found else None,
                       'all_replays_valid':all(r[name]['replay_valid'] for r in rows)}
    output={'scope':f'Independent synthetic layouts, equal {args.evaluations}-simulation/{args.seconds}-second budgets; up to five rails and moderate side; no human success claim',
            'seconds':round(monotonic()-started,1),'summary':summary,'rows':rows}
    path=service.root/'artifacts'/'ai-training'/'independent-audit.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    package=service.root/'training'/'ai_stage2'
    package.mkdir(parents=True,exist_ok=True)
    (package/'independent-audit.json').write_text(path.read_text(encoding='utf-8'),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
