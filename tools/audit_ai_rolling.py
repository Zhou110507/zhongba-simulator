"""Real-physics rolling queue audit; no model training or scripted suffix."""
from copy import deepcopy
import json
from threading import BoundedSemaphore,Event
from time import monotonic,sleep

from billiards.ai_cache import model_stamp
from billiards.ai_jobs import AIJobs
from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.play import PlayService
from billiards.runout import Search


def play(service,state,analysis,strokes):
    games=GameStore(service);games.games[state['id']]=deepcopy(state)
    jobs=AIJobs(games,BoundedSemaphore(1));key='initial'
    analysis['action']={'action':'shoot','shot':analysis['routes'][0]['steps'][0]['shot']}
    jobs.jobs[key]={'id':key,'status':'found','created':monotonic(),'cancel':Event(),
                    'source':deepcopy(state),'game_id':state['id'],'revision':state['revision'],
                    'stamp':model_stamp(service),'analysis':analysis}
    rows=[]
    for index in range(strokes):
        before=jobs.status({'id':key})['analysis'];value=jobs.execute({'id':key,'prefetch':True})
        assert value['complete'] and value['rule_committed'] and not value['game_after']['last_decision']['fouls']
        current=value['game_after'];future=value['prefetch'];key=future['id'];started=monotonic()
        while True:
            status=jobs.status({'id':key});a=status.get('analysis',{})
            if status['status']=='found' and (a['routes'][0]['clear_verified'] or
                                            len(a['routes'][0]['steps'])>=3 or
                                            a.get('rolling',{}).get('exhausted')):break
            assert monotonic()-started<30,status
            sleep(.02)
        assert status['status']=='found' and len(a['routes'][0]['steps'])>=3
        kept=before['routes'][0]['steps'][1:]
        assert a['routes'][0]['steps'][:len(kept)]==kept
        assert games.games[state['id']]['revision']==current['revision']
        rows.append({'executed_ordinal':index+1,'executed_shot':before['routes'][0]['steps'][0],
                     'retained_shots_unchanged':True,'immediate_prefetch':future,
                     'queued_after_refill':a['routes'][0]['steps'],
                     'extension_evaluations':a.get('extension_evaluations',0),
                     'refill_seconds':round(monotonic()-started,3),
                     'actual_revision':current['revision'],'actual_decision':current['last_decision'],
                     'actual_balls':current['scene']['balls']})
    jobs.status({'id':key},cancel=True)
    assert jobs.metrics['searches']==0
    return {'initial_scene':state['scene'],'initial_groups':state['groups'],
            'initial_queue':analysis['routes'][0]['steps'],'actions':rows,'metrics':jobs.metrics}


def main():
    service=PlayService(table_profile='cbsa_2017')
    # Current search produces exactly the initially available three-shot queue.
    demo=GameStore(service).new({'scenario':'ai_endgame'})
    plan=Search(service,seconds=60,evaluations=2400).solve(demo,max_depth=3)
    assert len(plan['routes'][0]['steps'])==3
    rows=[{'case':'fresh-three-ball-search',**play(service,demo,plan,1)}]
    # A historical seven-ball layout supplies only three re-certified prefix
    # shots. The 4th and 5th shots are newly searched, not taken from that file.
    old=json.loads((service.root/'training'/'ai_stage2'/'self-practice.json').read_text(encoding='utf8'))
    case=next(r for r in old['rows'] if r['case']=='68004')
    state=GameStore(service).new({'scenario':'ai_endgame'})
    state.update(scene=case['initial_scene'],groups=case['initial_groups'])
    search=Search(service,seconds=30,evaluations=20);node=state;forecasts=[];steps=[]
    for step in case['steps'][:3]:
        trial=search.forward(node,ShotInput(**step['shot']));assert trial and not trial[1]['last_decision']['fouls']
        after=trial[1];assert after['turn']==state['turn']
        forecasts.append((node,after));step=deepcopy(step);step['human']=trial[2];steps.append(step);node=after
    analysis={'status':'found','model':'short-runout-value-v4','routes':[{'steps':steps,'reasons':[],
              'clear_verified':False,'mean_cost':sum(s['cost'] for s in steps)/3}],
              '_forecasts':[forecasts],'evaluations':search.count,'elapsed':0.}
    rows.append({'case':'seven-ball-recertified-prefix',**play(service,state,analysis,2)})
    output={'scope':'Queue scheduling and actual shared physics; current model unchanged. Historical prefix is a regression fixture, not a new training or win-rate test.',
            'summary':{'cases':2,'physical_shots':3,'appended_shots':sum(r['metrics']['extended_steps'] for r in rows),
                       'foreground_researches':sum(r['metrics']['searches'] for r in rows),
                       'all_prefixes_unchanged':True,'all_actual_shots_legal':True},'rows':rows}
    path=service.root/'validation'/'ai_rolling.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(output['summary']),flush=True)


if __name__=='__main__':main()
