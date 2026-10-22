"""Deterministic scheduling races plus shared-physics coverage in cache tests."""
from copy import deepcopy
from threading import BoundedSemaphore,Event
from time import monotonic,sleep

import pytest

from billiards.ai_cache import matches,model_stamp
from billiards.ai_jobs import AIJobs
from billiards.game import GameStore
from billiards.play import PlayService


def wait_for(predicate):
    deadline=monotonic()+3
    while monotonic()<deadline:
        value=predicate()
        if value:return value
        sleep(.005)
    raise AssertionError('Background queue did not reach expected state')


def pipeline(monkeypatch):
    service=PlayService(table_profile='cbsa_2017');games=GameStore(service)
    initial=games.new({'scenario':'ai_endgame'})
    states=[]
    for index in range(8):
        state=deepcopy(initial);state['revision']=index
        if index:state['last_decision']={'potted':[str(index)],'fouls':[]}
        next(b for b in state['scene']['balls'] if b['id']=='cue')['position']['x']+=index*.01
        if index==7:state.update(phase='finished',winner=state['turn'])
        states.append(state)
    steps=[{'target':str(i+1),'pocket':'top-right','shot':{'angle_deg':i,'cue_speed':1.,'tip_x':0.,'tip_y':0.},
            'cost':1.,'position_effort':.1,'verified':True} for i in range(7)]
    def segment(start,end):
        return {'status':'found','routes':[{'steps':deepcopy(steps[start:end]),'reasons':[],
                                          'clear_verified':end==7,'mean_cost':1.}],
                '_forecasts':[[deepcopy((states[i],states[i+1])) for i in range(start,end)]],
                'evaluations':10,'elapsed':.01,'model':'scheduling-fixture'}
    analysis=segment(0,3);analysis['action']={'action':'shoot','shot':steps[0]['shot']}
    jobs=AIJobs(games,BoundedSemaphore(1))
    jobs.jobs['initial']={'id':'initial','status':'found','created':monotonic(),'cancel':Event(),
                          'game_id':initial['id'],'revision':0,'source':deepcopy(initial),
                          'stamp':model_stamp(service),'analysis':analysis}
    committed=[]
    def action(data,**kwargs):
        current=games._checked(data);index=current['revision']
        assert data['shot']==steps[index]['shot']
        games.games[initial['id']]=deepcopy(states[index+1]);committed.append(index+1)
        return {'complete':True,'rule_committed':True,'result':{},'game_after':deepcopy(states[index+1])}
    monkeypatch.setattr(games,'action',action)
    monkeypatch.setattr('billiards.ai_jobs.decide',lambda *a,**k:pytest.fail('Cached prefix was re-searched'))
    monkeypatch.setattr('billiards.ai_jobs.repair',lambda *a,**k:None)
    return games,jobs,states,steps,segment,committed


def test_execution_one_adds_four_and_execution_two_adds_five_without_replanning_prefix(monkeypatch):
    games,jobs,states,steps,segment,committed=pipeline(monkeypatch)
    entered=[Event(),Event()];release=[Event(),Event()];calls=[]
    def extend(service,state,depth,**kwargs):
        i=len(calls);calls.append((state['revision'],depth));entered[i].set();assert release[i].wait(3)
        return segment(state['revision'],state['revision']+depth)
    monkeypatch.setattr('billiards.ai_jobs.extend',extend)
    try:
        value=jobs.execute({'id':'initial','prefetch':True});key=value['prefetch']['id']
        assert entered[0].wait(1) and calls==[(3,1)] and committed==[1]
        ready=jobs.status({'id':key});assert ready['status']=='found'
        assert ready['analysis']['routes'][0]['steps']==steps[1:3]  # retained, not executable yet
        assert not ready['analysis']['execution_gate']['ready']
        assert ready['analysis']['rolling']['extending']
        again=jobs.start({'id':states[1]['id'],'revision':1});assert again['id']==key
        assert len(calls)==1 and games.games[states[0]['id']]['revision']==1
        release[0].set()
        wait_for(lambda:len(jobs.status({'id':key})['analysis']['routes'][0]['steps'])==3)
        assert jobs.status({'id':key})['analysis']['routes'][0]['steps']==steps[1:4]
        second=jobs.execute({'id':key,'prefetch':True});key2=second['prefetch']['id']
        assert entered[1].wait(1) and calls==[(3,1),(4,1)] and committed==[1,2]
        release[1].set()
        wait_for(lambda:len(jobs.status({'id':key2})['analysis']['routes'][0]['steps'])==3)
        assert jobs.status({'id':key2})['analysis']['routes'][0]['steps']==steps[2:5]
        assert jobs.metrics['searches']==0 and jobs.metrics['extended_steps']==2
        assert games.games[states[0]['id']]['revision']==2  # prediction never commits
    finally:
        for e in release:e.set()


def test_execution_cannot_overtake_extension_or_consume_the_remaining_prefix(monkeypatch):
    _,jobs,states,steps,segment,committed=pipeline(monkeypatch)
    entered=Event();release=Event();calls=[]
    def extend(service,state,depth,**kwargs):
        calls.append(state['revision']);entered.set();assert release.wait(3)
        return segment(state['revision'],state['revision']+depth)
    monkeypatch.setattr('billiards.ai_jobs.extend',extend)
    try:
        key=jobs.execute({'id':'initial','prefetch':True})['prefetch']['id'];assert entered.wait(1)
        for _ in range(3):
            with pytest.raises(ValueError,match='等待前瞻补齐'):jobs.execute({'id':key,'prefetch':True})
        assert committed==[1]
        assert jobs.start({'id':states[1]['id'],'revision':1})['id']==key
        assert calls==[3]  # no duplicate search while waiting
        release.set()
        wait_for(lambda:jobs.status({'id':key})['status']=='found')
        wait_for(lambda:len(jobs.status({'id':key})['analysis']['routes'][0]['steps'])==3)
        assert jobs.status({'id':key})['analysis']['routes'][0]['steps']==steps[1:4]
        assert calls==[3] and jobs.metrics['searches']==0
    finally:release.set()


@pytest.mark.parametrize('change',['cancel','ball','model'])
def test_late_suffix_cannot_resurrect_cancelled_or_changed_table(monkeypatch,change):
    games,jobs,states,steps,segment,_=pipeline(monkeypatch)
    entered=Event();release=Event();finished=Event()
    def extend(*args,**kwargs):
        entered.set();assert release.wait(3);finished.set();return segment(3,4)
    monkeypatch.setattr('billiards.ai_jobs.extend',extend)
    try:
        key=jobs.execute({'id':'initial','prefetch':True})['prefetch']['id'];assert entered.wait(1)
        if change=='cancel':jobs.status({'id':key},cancel=True)
        elif change=='ball':games.games[states[0]['id']]['scene']['balls'][-1]['position']['y']+=.002
        else:monkeypatch.setattr('billiards.ai_jobs.model_stamp',lambda service:'changed-model')
        release.set();assert finished.wait(1)
        wait_for(lambda:not jobs.continuations[states[0]['id']]['extending'])
        assert jobs.jobs[key]['analysis']['routes'][0]['steps']==steps[1:3]
        assert jobs.metrics['extended_steps']==0
        with pytest.raises(ValueError):jobs.execute({'id':key})
    finally:release.set()


@pytest.mark.parametrize('suffix_error',[False,True,'repair'])
def test_exhausted_suffix_keeps_verified_pots_instead_of_switching_to_safety(monkeypatch,suffix_error):
    _,jobs,states,steps,_,committed=pipeline(monkeypatch)
    entered=Event();release=Event();fallback=Event()
    def extend(*a,**k):
        entered.set();assert release.wait(3)
        if suffix_error is True:raise RuntimeError('injected suffix failure')
        return {'status':'not_found','routes':[]}
    def tactic(service,state,**kwargs):
        assert state['revision']==1 and matches(state,states[1])
        assert not matches(state,states[3])  # future endpoint was never reached
        fallback.set()
        return {'status':'found','routes':[],'tactic':'attack',
                'action':{'action':'shoot','shot':steps[1]['shot']}}
    monkeypatch.setattr('billiards.ai_jobs.extend',extend);monkeypatch.setattr('billiards.tactics.choose_contact',tactic)
    if suffix_error=='repair':
        def broken_repair(*a,**k):raise RuntimeError('injected repair failure')
        monkeypatch.setattr('billiards.ai_jobs.repair',broken_repair)
    try:
        key=jobs.execute({'id':'initial','prefetch':True})['prefetch']['id'];assert entered.wait(1)
        with pytest.raises(ValueError,match='等待前瞻补齐'):jobs.execute({'id':key,'prefetch':True})
        release.set()
        wait_for(lambda:jobs.status({'id':key})['analysis']['execution_gate']['ready'])
        assert not fallback.is_set() and committed==[1]
        ready=jobs.status({'id':key})['analysis']
        assert ready['routes'][0]['steps']==steps[1:3]
        assert ready['execution_gate']['recovery'] and ready['execution_gate']['available']==2
        assert ready['offensive_recovery']['reason']=={False:'no_robust_continuation_found',True:'suffix_error','repair':'repair_error'}[suffix_error]
        jobs.execute({'id':key});assert committed==[1,2]
        assert jobs.metrics['searches']==0
    finally:release.set()


@pytest.mark.parametrize('change',['cancel','ball','model'])
def test_offensive_repair_waits_and_rejects_stale_results(monkeypatch,change):
    games,jobs,states,steps,_,committed=pipeline(monkeypatch)
    entered=Event();release=Event();calls=[]
    monkeypatch.setattr('billiards.ai_jobs.extend',lambda *a,**k:{'status':'not_found','routes':[]})
    def repair(service,prefix,state,**kwargs):
        calls.append(state['revision']);entered.set();assert release.wait(3)
        return None
    monkeypatch.setattr('billiards.ai_jobs.repair',repair)
    try:
        key=jobs.execute({'id':'initial','prefetch':True})['prefetch']['id'];assert entered.wait(1)
        for _ in range(3):
            status=jobs.status({'id':key})['analysis']
            assert status['rolling']['fallback_pending'] and status['execution_gate']['waiting']
            assert jobs.start({'id':states[1]['id'],'revision':1})['id']==key
            with pytest.raises(ValueError,match='等待前瞻补齐'):jobs.execute({'id':key})
        if change=='cancel':jobs.status({'id':key},cancel=True)
        elif change=='ball':games.games[states[0]['id']]['scene']['balls'][-1]['position']['y']+=.002
        else:monkeypatch.setattr('billiards.ai_jobs.model_stamp',lambda service:'changed-model')
        release.set();wait_for(lambda:not jobs.continuations[states[0]['id']]['extending'])
        assert 'offensive_recovery' not in jobs.jobs[key]['analysis']
        with pytest.raises(ValueError):jobs.execute({'id':key})
        assert calls==[1] and committed==[1] and jobs.metrics['searches']==0
    finally:release.set()


def test_cancelling_a_waiting_extension_releases_worker_and_allows_new_think(monkeypatch):
    _,jobs,states,_,segment,_=pipeline(monkeypatch)
    entered=Event();release=Event()
    def extend(*a,**k):entered.set();assert release.wait(3);return segment(3,4)
    monkeypatch.setattr('billiards.ai_jobs.extend',extend)
    try:
        key=jobs.execute({'id':'initial','prefetch':True})['prefetch']['id'];assert entered.wait(1)
        jobs.status({'id':key},cancel=True);release.set()
        wait_for(lambda:not jobs.continuations[states[0]['id']]['extending'])
        assert jobs.jobs[key]['cancel'].is_set()
        assert jobs.slots.acquire(timeout=1);jobs.slots.release()
        called=Event()
        def fresh(*a,**k):called.set();return {'status':'found','routes':[]}
        monkeypatch.setattr('billiards.ai_jobs.decide',fresh)
        again=jobs.start({'id':states[1]['id'],'revision':1})
        assert again['id']!=key and called.wait(1)
    finally:release.set()


def test_busy_cpu_does_not_block_ready_prefix_and_poll_retries_refill(monkeypatch):
    _,jobs,_,_,segment,_=pipeline(monkeypatch);entered=Event()
    def extend(service,state,depth,**kwargs):entered.set();return segment(3,4)
    monkeypatch.setattr('billiards.ai_jobs.extend',extend)
    assert jobs.slots.acquire(timeout=1)
    value=jobs.execute({'id':'initial','prefetch':True});key=value['prefetch']['id']
    assert value['prefetch']['status']=='found' and not entered.is_set()
    jobs.slots.release();jobs.status({'id':key})
    assert entered.wait(1)
    wait_for(lambda:len(jobs.status({'id':key})['analysis']['routes'][0]['steps'])==3)


@pytest.mark.parametrize('end',[4,5])
def test_tail_repair_preserves_earlier_queued_stroke_and_requests_full_depth(monkeypatch,end):
    from billiards import ai_rolling
    _,_,states,steps,segment,_=pipeline(monkeypatch)
    prefix=segment(1,3);calls=[]
    def suffix(service,source,depth,**kwargs):
        calls.append((source,depth));return segment(2,end)
    monkeypatch.setattr(ai_rolling,'extend',suffix)
    result=ai_rolling.repair(None,prefix,states[1],cancelled=lambda:False,progress=lambda _:None)
    assert matches(calls[0][0],states[2]) and calls[0][1]==3
    if end==4:
        assert result is None  # three verified strokes do not certify a four-shot endgame
        return
    assert result['repaired_tail'] and result['repair_retained_steps']==1
    assert result['routes'][0]['steps']==steps[1:5]
    assert result['_forecasts'][0][0]==prefix['_forecasts'][0][0]
    assert result['requested_depth']==4 and result['verified_depth']==4
    assert prefix['routes'][0]['steps']==steps[1:3]  # immutable source
