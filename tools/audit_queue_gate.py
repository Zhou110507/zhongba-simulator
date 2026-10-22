"""Deterministically make playback overtake one real-physics queue worker."""
from copy import deepcopy
import hashlib
import json
from threading import BoundedSemaphore,Event
from time import monotonic,sleep

from billiards import ai_jobs
from billiards.ai_cache import matches,model_stamp
from billiards.ai_rolling import readiness
from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.play import PlayService
from billiards.runout import Search


def main():
    service=PlayService(table_profile='cbsa_2017');games=GameStore(service)
    state=games.new({'scenario':'ai_endgame','ai_level':'expert'})
    path=service.root/'training/ai_stage3/integrated-audit.json'
    actions=next(row for row in json.loads(path.read_text(encoding='utf8'))['rows'] if row['case']=='endgame-cache')['actions']
    search=Search(service,seconds=30,evaluations=20);node=state;steps=[];forecasts=[]
    for action in actions:
        shot=action['action']['shot'];trial=search.forward(node,ShotInput(**shot));assert trial
        result,after,_=trial;assert not after['last_decision']['fouls']
        target=after['last_decision']['first_contacts'][0]
        steps.append({'target':target,'pocket':next(b.pocket for b in result.final if b.id==target),
                      'shot':shot,'cost':1.,'position_effort':.1,'verified':True})
        forecasts.append((node,after));node=after
    assert node['phase']=='finished' and node['winner']==state['turn']
    full={'status':'found','routes':[{'steps':steps,'clear_verified':True,'reasons':[]}],
          '_forecasts':[forecasts],'evaluations':search.count,'elapsed':0.}
    prefix=deepcopy(full);prefix['routes'][0].update(steps=steps[:3],clear_verified=False)
    prefix['_forecasts']=[forecasts[:3]]
    prefix['action']={'action':'shoot','shot':steps[0]['shot']}
    jobs=ai_jobs.AIJobs(games,BoundedSemaphore(1));stamp=model_stamp(service)
    jobs.jobs['audit']={'id':'audit','status':'found','created':monotonic(),'cancel':Event(),
        'game_id':state['id'],'revision':0,'source':state,'stamp':stamp,'analysis':prefix}
    entered=Event();release=Event();calls=[];rows=[];denied=[]
    original=ai_jobs.extend
    def slow(service,anchor,depth,**kwargs):
        calls.append({'anchor_matches_after_third':matches(anchor,forecasts[2][1]),'depth':depth})
        entered.set();assert release.wait(10)
        suffix=deepcopy(full);suffix['routes'][0]['steps']=steps[3:];suffix['_forecasts']=[forecasts[3:]]
        return suffix
    def execute(key):
        before=jobs.status({'id':key})['analysis'];gate=before['execution_gate']
        assert gate['ready']
        value=jobs.execute({'id':key,'prefetch':True});after=value['game_after']
        rows.append({'revision_after':after['revision'],'queue_before':[s['target'] for s in before['routes'][0]['steps']],
                     'gate_before':gate,'potted':after['last_decision']['potted'],'fouls':after['last_decision']['fouls']})
        assert not after['last_decision']['fouls']
        return value
    ai_jobs.extend=slow
    try:
        first=execute('audit');key=first['prefetch']['id'];assert entered.wait(1)
        tail=deepcopy(prefix['routes'][0]['steps'][1:])
        for attempt in range(3):
            current=jobs.status({'id':key})['analysis'];gate=current['execution_gate']
            assert gate['waiting'] and not gate['ready'] and gate['available']==2
            assert current['routes'][0]['steps']==tail
            try:jobs.execute({'id':key})
            except ValueError as error:denied.append({'attempt':attempt+1,'message':str(error),'revision':games.games[state['id']]['revision']})
            else:raise AssertionError('Second stroke overtook the fourth-stroke worker')
        release.set();deadline=monotonic()+3
        while monotonic()<deadline:
            status=jobs.status({'id':key})
            if status['analysis']['execution_gate']['ready'] and not jobs.continuations[state['id']]['extending']:break
            sleep(.005)
        assert status['analysis']['routes'][0]['steps'][:2]==tail
        for _ in range(3):
            value=execute(key)
            if value['game_after']['phase']=='finished':break
            key=value['prefetch']['id']
        assert value['game_after']['phase']=='finished' and len(rows)==4
        assert len(calls)==1 and jobs.metrics['searches']==0 and jobs.metrics['extensions']==1
        report={'version':'three-shot-execution-gate-v10','source_fixture':str(path.relative_to(service.root)).replace('\\','/'),
                'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'schedule':'Hold the fourth-stroke worker until three attempts to execute the second are rejected; then release it.',
                'scope':'Frozen real-physics/rules shots test queue timing; not new training or a strategy-quality/latency benchmark.',
                'game_id':state['id'],'physical_fixture_checks':search.count,'denied_early_execution':denied,
                'tail_workers':calls,'executions':rows,'metrics':jobs.metrics,'finished':True,
                'prefix_preserved':True,'initial_gate':readiness(prefix,state)}
        (service.root/'validation/three_shot_queue_v10.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(json.dumps(report,ensure_ascii=True),flush=True)
    finally:
        release.set();ai_jobs.extend=original


if __name__=='__main__':main()
