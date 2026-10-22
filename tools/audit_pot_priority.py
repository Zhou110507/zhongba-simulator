"""Prospective unseen-layout comparison; this command never fits any model."""
from copy import deepcopy
import hashlib
import json
import subprocess
from time import perf_counter
import types

from billiards.game import GameStore
from billiards.play import APP_VERSION,PlayService
from billiards.tactics import choose_contact,opponent_threat
from billiards.human_stroke import load_policy
from tools.train_runout import layout

BASELINE='72cd5815e884accb69506243baaaa279292bf003'
SEEDS=tuple(range(960001,960013))  # locked before inspecting any outcomes


def hashes(root):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/'configs').glob('ai_*.json'))}


def recorded_seeds(value):
    found=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if 'seed' in key and isinstance(item,int):found.add(item)
            if 'seed' in key and isinstance(item,list):found.update(i for i in item if isinstance(i,int))
            found.update(recorded_seeds(item))
    elif isinstance(value,list):
        for item in value:found.update(recorded_seeds(item))
    return found


def main():
    service=PlayService(table_profile='cbsa_2017');before=hashes(service.root)
    known=set()
    for p in (service.root/'configs').glob('ai_*.json'):
        known.update(recorded_seeds(json.loads(p.read_text(encoding='utf8'))))
    assert not known.intersection(SEEDS)
    source=subprocess.check_output(['git','show',BASELINE+':billiards/tactics.py'],cwd=service.root).decode('utf8')
    old=types.ModuleType('billiards._tactics_v12');old.__package__='billiards';exec(source,old.__dict__)
    rows=[]
    for index,seed in enumerate(SEEDS):
        count=1+index%5;state=layout(service,seed,max_balls=5,ball_count=count)
        entry={'seed':seed,'own_balls':count,'versions':{}}
        # Same overall evaluation ceiling: v12 may use all 600 on contacts;
        # v13 allocates 480 to attack/contact, plus up to 120 to safety checks.
        # Wall limits are headroom, not speed benchmarks. No depth is reduced.
        for name,fn,cap in (('v12',old.choose_contact,600),('v13',choose_contact,480)):
            started=perf_counter();analysis=fn(service,deepcopy(state),seconds=120,evaluations=cap)
            elapsed=perf_counter()-started
            games=GameStore(service);games.games[state['id']]=deepcopy(state)
            value=games.action({'id':state['id'],'revision':state['revision'],**analysis['action']})
            after=value['game_after'];d=after['last_decision'];threat=opponent_threat(service,after,state['turn'],load_policy(service))
            own_pots=[k for k in d['potted'] if k in {str(i) for i in range(1,count+1)}] if seed%2 else [k for k in d['potted'] if k in {str(i+8) for i in range(1,count+1)}]
            entry['versions'][name]={'tactic':analysis['tactic'],'shot':analysis['action']['shot'],
                'complete':value['complete'],'committed':value['rule_committed'],'fouls':d['fouls'],
                'own_pots':own_pots,'won':after['winner']==state['turn'],'opponent_threat':threat,
                'evaluations':analysis['evaluations']+analysis.get('safety_evaluations',0),
                'elapsed_seconds':round(elapsed,3),'safety_check':analysis.get('safety_check')}
        rows.append(entry)
        print(json.dumps(entry,ensure_ascii=True),flush=True)
    assert before==hashes(service.root),'Validation must never tune or fit the models'
    summary={name:{'pot_cases':sum(bool(r['versions'][name]['own_pots']) or r['versions'][name]['won'] for r in rows),
                   'foul_cases':sum(bool(r['versions'][name]['fouls']) for r in rows),
                   'evaluations':sum(r['versions'][name]['evaluations'] for r in rows)} for name in ('v12','v13')}
    report={'version':APP_VERSION,'baseline_commit':BASELINE,'seeds':SEEDS,
            'seed_overlap_with_model_metadata':[], 'model_hashes_unchanged':True,'model_hashes':before,
            'scope':'12 prospective synthetic tactical layouts; no training or tuning, no human probability, no full-rack strength or latency claim.',
            'budget':'600 total evaluations per version; v13 reserves 120 for safety validation; 120 seconds headroom for contact search.',
            'summary':summary,'rows':rows}
    path=service.root/'validation/pot_priority_unseen_v13.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'summary':summary,'report':str(path)},ensure_ascii=True),flush=True)


if __name__=='__main__':main()
