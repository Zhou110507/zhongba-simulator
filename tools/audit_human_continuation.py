"""Compare the delivered planner with the previous committed implementation."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from types import ModuleType
import numpy as np

from billiards.game import GameStore
from billiards.play import PlayService
from billiards.runout import Search,shot_options
from tools.train_runout import layout

BASE='ae95046ec444a1dadd1095020a36e31607f9393f'


def summary(service,search,state,result):
    routes=result.get('routes',[])
    if not routes:return {'found':False,'steps':0,'evaluations':search.count,'seconds':result['elapsed']}
    route=routes[0];forecasts=result['_forecasts'][0];links=[];contacts=[];accessible=0
    for step,(_,after) in zip(route['steps'],forecasts):
        service.decode(after['scene'])
        options=shot_options(service,after,search.policy)
        best=options[0] if options else None
        links.append(best['cost'] if best else 8.)
        accessible+=bool(best and best['cost']<3. and not best['rear_restricted'] and .18<=best['distance']<=1.2)
        contacts.append(sum('cue' in p and step['target'] not in p for p in step['secondary_contacts']))
    return {'found':True,'steps':len(route['steps']),'targets':[s['target'] for s in route['steps']],
            'evaluations':search.count,'seconds':result['elapsed'],'next_cost_mean':float(np.mean(links)),
            'comfortable_leaves':accessible,'cue_other_contacts':sum(contacts),'clear':route['clear_verified'],
            'first_next_cost':links[0],
            'reused_simulations':result.get('reused_simulations',0)}


def main():
    service=PlayService(table_profile='cbsa_2017')
    old=ModuleType('billiards.audit_legacy');sys.modules[old.__name__]=old
    source=subprocess.check_output(['git','show',BASE+':billiards/runout.py']).decode('utf8')
    exec(compile(source,'legacy-runout.py','exec'),old.__dict__)
    fixture=json.loads((service.root/'tests'/'fixtures'/'ai-invalid-final-state.json').read_text(encoding='utf8'))
    cases=[('previous-user-layout',fixture['original']),('endgame',GameStore(service).new({'scenario':'ai_endgame'}))]
    cases += [(str(seed),layout(service,seed,ball_count=3)) for seed in range(980001,980005)]
    rows=[]
    for name,state in cases:
        row={'case':name}
        for label,cls,seconds,cap in [('before',old.Search,24,1500),('after',Search,12,600)]:
            search=cls(service,seconds=seconds,evaluations=cap)
            started=perf_counter();value=search.solve(deepcopy(state),max_depth=3)
            row[label]=summary(service,search,state,value);row[label]['wall_seconds']=perf_counter()-started
        rows.append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
        (service.root/'artifacts'/'ai-training'/'human-audit-progress.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    aggregate={}
    for label in ('before','after'):
        selected=[r[label] for r in rows];found=[r for r in selected if r['found']]
        aggregate[label]={'cases':len(rows),'found':len(found),'steps':sum(r['steps'] for r in selected),
                          'seconds':sum(r['wall_seconds'] for r in selected),'evaluations':sum(r['evaluations'] for r in selected),
                          'comfortable_leaves':sum(r['comfortable_leaves'] for r in found),
                          'cue_other_contacts':sum(r['cue_other_contacts'] for r in found),
                          'first_next_cost_mean':float(np.mean([r['first_next_cost'] for r in found])),
                          'next_cost_mean':float(np.mean([r['next_cost_mean'] for r in found]))}
    report={'baseline_commit':BASE,'maximum_depth':3,'seeds_disjoint_from_training':True,'rows':rows,'summary':aggregate,
            'limits':'Six-case engineering audit, not calibrated human win/clear probability. Budgets differ intentionally; every endpoint decoded with unchanged geometry validation.'}
    (service.root/'validation'/'human_continuation_v8.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(aggregate),flush=True)


if __name__=='__main__':main()
