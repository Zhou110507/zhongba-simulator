"""Frozen integrated play: blind break, real turns, continuation cache and kicks."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
import json
import random
from threading import BoundedSemaphore
from time import monotonic,sleep

from billiards.ai_jobs import AIJobs
from billiards.game import GameStore
from billiards.play import PlayService
from tools.train_tactics import tactical_layout


def play_case(name,initial,max_shots=6):
    service=PlayService(table_profile='cbsa_2017');games=GameStore(service)
    current=deepcopy(initial);games.games[current['id']]=current
    jobs=AIJobs(games,BoundedSemaphore(1));rows=[];future=None;started=monotonic()
    physical=0;reason='operation_budget'
    for _ in range(20):
        who=current['chooser'] if current['phase']=='choice' else current['turn']
        if current['phase']=='finished':reason='finished';break
        if who!=current.get('ai_player'):reason='turn_completed';break
        if physical>=max_shots:reason='practice_shot_budget';break
        wait_started=monotonic()
        job=future or jobs.start({'id':current['id'],'revision':current['revision']});future=None
        while True:
            status=jobs.status({'id':job['id']})
            if status['status']!='running':break
            assert monotonic()-wait_started<65,'AI job exceeded bounded budget'
            sleep(.02)
        assert status['status']=='found',status
        analysis=status['analysis'];assert 'action' in analysis
        before=current;value=jobs.execute({'id':job['id'],'prefetch':True})
        action=analysis['action'];row={'action':action,'model':analysis.get('model'),
             'tactic':analysis.get('tactic'),'cache_hit':analysis.get('cache_hit',False),
             'evaluations':analysis.get('evaluations',0),'wait_seconds':round(monotonic()-wait_started,3)}
        if 'result' in value:
            assert value['complete'] and value['rule_committed']
            current=value['game_after'];physical+=1;decision=current['last_decision']
            row.update(potted=decision['potted'],fouls=decision['fouls'],first_contacts=decision['first_contacts'],
                       final_balls=current['scene']['balls'],
                       cue_cushions=sum(e['kind']=='ball_cushion' and 'cue' in e['actors'] for e in value['result']['events']))
            if analysis.get('tactic') in ('safety','kick_attack'):assert not decision['fouls']
            if analysis.get('routes'):row['secondary_contacts']=analysis['routes'][0]['steps'][0].get('secondary_contacts',[])
        else:current=value
        future=value.get('prefetch')
        rows.append(row)
    if future:jobs.status({'id':future['id']},cancel=True)
    return {'case':name,'initial_scene':initial['scene'],'initial_groups':initial['groups'],
            'initial_break':initial['is_break'],'actions':rows,'physical_shots':physical,
            'stop_reason':reason,'winner':current['winner'],'metrics':jobs.metrics,
            'all_submitted_shots_complete':True,'seconds':round(monotonic()-started,2)}


def main():
    service=PlayService(table_profile='cbsa_2017');cases=[]
    for seed in range(510001,510013):cases.append((str(seed),tactical_layout(service,seed)))
    cases.append(('endgame-cache',GameStore(service).new({'scenario':'ai_endgame'})))
    cases.append(('blind-random-gap-break',GameStore(service).new({'seed':94001,'gap_mm':random.Random(94001).uniform(.1,.5),'breaker':0,'ai_player':0})))
    rows=[]
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(play_case,*case) for case in cases]
        for f in as_completed(futures):
            r=f.result();rows.append(r)
            print(json.dumps({'case':r['case'],'shots':r['physical_shots'],'stop':r['stop_reason'],'cache_hits':r['metrics']['cache_hits']}),flush=True)
    rows.sort(key=lambda r:r['case']);actions=[a for r in rows for a in r['actions']]
    output={'scope':'Frozen models, held-out tactical seeds, real AIJobs/GameStore actions; physical/engineering checks, not human success probabilities',
            'summary':{'cases':len(rows),'physical_shots':sum(r['physical_shots'] for r in rows),
                       'all_submitted_shots_complete':all(r['all_submitted_shots_complete'] for r in rows),
                       'cache_hits':sum(r['metrics']['cache_hits'] for r in rows),
                       'prefetches':sum(r['metrics']['prefetches'] for r in rows),
                       'legal_defense_actions':sum(a.get('tactic') in ('safety','kick_attack') and not a.get('fouls') for a in actions),
                       'best_effort_actions':sum(a.get('tactic')=='best_effort' for a in actions),
                       'position_contact_actions':sum(bool(a.get('secondary_contacts')) for a in actions)},'rows':rows}
    path=service.root/'training'/'ai_stage3'/'integrated-audit.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(output['summary']),flush=True)


if __name__=='__main__':main()
