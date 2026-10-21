from copy import deepcopy
import json
from threading import BoundedSemaphore,Event
from time import monotonic,sleep

import pytest

from billiards.ai_cache import matches,model_stamp
from billiards.ai_jobs import AIJobs,decide
from billiards.break_policy import decide_break
from billiards.game import GameStore
from billiards.play import PlayService
from billiards.runout import Search
from billiards.cue import ShotInput
from billiards.tactics import choose_contact
from tools.train_tactics import tactical_layout


@pytest.fixture(scope='module')
def service():return PlayService(table_profile='cbsa_2017')


@pytest.fixture(scope='module')
def planned(service):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    # Cache tests need a stable certified route, not a wall-clock-dependent
    # search success. Re-simulate the frozen audit's actual four shots here.
    audit=json.loads((service.root/'training'/'ai_stage3'/'integrated-audit.json').read_text(encoding='utf8'))
    actions=next(r for r in audit['rows'] if r['case']=='endgame-cache')['actions']
    search=Search(service,seconds=30,evaluations=20);node=state;steps=[];forecasts=[]
    for action in actions:
        shot=ShotInput(**action['action']['shot']);trial=search.forward(node,shot)
        assert trial and not trial[1]['last_decision']['fouls']
        physical,after,_=trial;target=after['last_decision']['first_contacts'][0]
        ball=next(b for b in physical.final if b.id==target)
        steps.append({'target':target,'pocket':ball.pocket,'shot':action['action']['shot'],
                      'cost':1.,'position_effort':.1,'verified':True})
        forecasts.append((node,after));node=after
    assert node['winner']==state['turn']
    result={'status':'found','routes':[{'steps':steps,'clear_verified':True,'reasons':[],'mean_cost':1.}],
            '_forecasts':[forecasts],'evaluations':search.count,'elapsed':0.}
    return state,result


def prepared(service,planned):
    state,result=deepcopy(planned);games=GameStore(service);games.games[state['id']]=state
    jobs=AIJobs(games,BoundedSemaphore(1))
    result['action']={'action':'shoot','shot':result['routes'][0]['steps'][0]['shot']}
    jobs.jobs['ready']={'id':'ready','status':'found','created':monotonic(),'cancel':Event(),
                        'game_id':state['id'],'revision':state['revision'],'source':deepcopy(state),
                        'stamp':model_stamp(service),'analysis':result}
    return games,jobs


def test_entire_verified_tail_reuses_without_search_and_can_finish_match(service,planned,monkeypatch):
    games,jobs=prepared(service,planned)
    def no_replanning(*args,**kwargs):raise AssertionError('A verified tail must not search again')
    monkeypatch.setattr('billiards.ai_jobs.decide',no_replanning)
    key='ready';count=0
    while True:
        value=jobs.execute({'id':key,'prefetch':True});count+=1
        assert value['complete'] and value['rule_committed']
        assert not value['game_after']['last_decision']['fouls']
        assert '_forecasts' not in value['ai_analysis']
        if value['game_after']['phase']=='finished':break
        future=value['prefetch'];assert future['status']=='found' and future['cache_hit']
        status=jobs.status({'id':future['id']})
        assert status['analysis']['evaluations']==0 and status['analysis']['cache_hit']
        assert '_forecasts' not in status['analysis'] and 'source' not in status
        key=future['id']
    assert count>=3 and jobs.metrics['cache_hits']==count-1


@pytest.mark.parametrize('ball_id',['cue','8','9'])
def test_changed_white_black_or_opponent_invalidates_prediction(service,planned,ball_id):
    state,result=planned
    predicted=result['_forecasts'][0][0][1]
    changed=deepcopy(predicted)
    next(b for b in changed['scene']['balls'] if b['id']==ball_id)['position']['x']+=.002
    assert not matches(predicted,changed)


def test_invalidated_tail_launches_a_fresh_job(service,planned,monkeypatch):
    games,jobs=prepared(service,planned);value=jobs.execute({'id':'ready'})
    current=value['game_after'];live=games.games[current['id']]
    next(b for b in live['scene']['balls'] if b['id']=='9')['position']['y']+=.002
    called=Event()
    def replacement(service,state,**kwargs):called.set();return {'status':'found','routes':[]}
    monkeypatch.setattr('billiards.ai_jobs.decide',replacement)
    jobs.start({'id':current['id'],'revision':current['revision']})
    assert called.wait(2) and jobs.metrics['invalidations']==1


def test_break_policy_never_reads_object_coordinates_or_runs_live_search(service,monkeypatch):
    class RackBall(dict):
        def __getitem__(self,key):
            if key!='id':raise AssertionError('Opening policy inspected the rack')
            return super().__getitem__(key)
    state=GameStore(service).new({'seed':3,'gap_mm':.2,'breaker':0,'ai_player':0})
    for i,b in enumerate(state['scene']['balls']):
        if b['id']!='cue':state['scene']['balls'][i]=RackBall(id=b['id'])
    monkeypatch.setattr(Search,'forward',lambda *a,**k:pytest.fail('Live break physics search'))
    monkeypatch.setattr(Search,'solve',lambda *a,**k:pytest.fail('Live break route search'))
    result=decide(service,state)
    assert result['status']=='found' and result['evaluations']==0 and result['rack_read'] is False
    first=result['action']
    state['seed']=987;state['gap_mm']=.5
    assert decide_break(service,state)['action']==first


def test_offline_break_trials_use_strictly_positive_random_gaps(service):
    report=json.loads((service.root/'training'/'ai_stage3'/'break-training.json').read_text(encoding='utf8'))
    rows=report['trials']+report['held_out_trials']
    assert len(rows)>100 and len({r['gap_mm'] for r in rows})>20
    assert all(.1<=r['gap_mm']<=.5 and r['min_pair_gap_mm']>0 for r in rows)
    assert not set(report['model']['train_seeds'])&set(report['model']['held_out_seeds'])


def test_blocked_direct_ball_has_a_verified_multirail_reply(service):
    state=tactical_layout(service,410001)
    result=choose_contact(service,state,seconds=12,evaluations=700)
    assert result['status']=='found' and result['tactic'] in ('safety','kick_attack')
    assert result['cue_cushions']>=1 and result['predicted_fouls']==[]
    games=GameStore(service);games.games[state['id']]=state
    value=games.action({'id':state['id'],'revision':0,**result['action']})
    assert value['complete'] and not value['game_after']['last_decision']['fouls']


def test_no_verified_contact_still_produces_a_shot_without_claiming_legality(service,monkeypatch):
    monkeypatch.setattr('billiards.tactics.contact_candidates',lambda *a,**k:[])
    result=choose_contact(service,tactical_layout(service,410001))
    assert result['status']=='found' and result['action']['action']=='shoot'
    assert result['tactic']=='best_effort' and result['predicted_fouls']
    assert result['action']['shot']['cue_speed']<=service.cue.max_speed
    state=tactical_layout(service,410001);games=GameStore(service);games.games[state['id']]=state
    value=games.action({'id':state['id'],'revision':0,**result['action']})
    assert value['complete'] and value['rule_committed']


def test_cache_miss_prefetch_runs_before_next_client_turn_without_duplicate_worker(service,planned,monkeypatch):
    games,jobs=prepared(service,planned);jobs.jobs['ready']['analysis'].pop('_forecasts')
    called=Event();release=Event()
    def background(service,state,**kwargs):
        called.set();release.wait(2)
        return {'status':'found','routes':[],'action':{'action':'shoot','shot':state['scene']['shot']}}
    monkeypatch.setattr('billiards.ai_jobs.decide',background)
    try:
        value=jobs.execute({'id':'ready','prefetch':True})
        assert called.wait(1) and value['prefetch']['status']=='running'
        after=value['game_after']
        again=jobs.start({'id':after['id'],'revision':after['revision']})
        assert again['id']==value['prefetch']['id'] and again['reused_job']
        assert jobs.metrics['searches']==1
    finally:release.set()


def test_legal_k_releases_own_opponent_cluster_and_still_pots(service):
    from tools.train_runout import layout
    from billiards.runout import shot_options
    state=layout(service,17042);search=Search(service,trained=False,seconds=10,evaluations=30)
    option=next(o for o in shot_options(service,state,search.policy) if o['target']=='9' and o['pocket']=='bottom-left')
    value=search.aimed(state,option,2.5,.3,-.3)
    assert value and value[1]['breakout_gain']>0
    assert ['cue','10'] in value[1]['secondary_contacts'] and ['cue','2'] in value[1]['secondary_contacts']
    games=GameStore(service);games.games[state['id']]=state
    actual=games.action({'id':state['id'],'revision':0,'action':'shoot','shot':value[1]['shot']})
    assert actual['complete'] and not actual['game_after']['last_decision']['fouls']
    assert '9' in actual['game_after']['last_decision']['potted']


def test_real_physics_queue_adds_black_during_first_shot_and_executes_without_full_research(service,planned,monkeypatch):
    state,result=deepcopy(planned)
    result['routes'][0]['steps']=result['routes'][0]['steps'][:3]
    result['routes'][0]['clear_verified']=False;result['_forecasts'][0]=result['_forecasts'][0][:3]
    games,jobs=prepared(service,(state,result))
    monkeypatch.setattr('billiards.ai_jobs.decide',lambda *a,**k:pytest.fail('Re-searched known first shots'))
    value=jobs.execute({'id':'ready','prefetch':True});key=value['prefetch']['id']
    assert value['complete'] and not value['game_after']['last_decision']['fouls']
    assert value['game_after']['revision']==1
    deadline=monotonic()+20
    while monotonic()<deadline:
        status=jobs.status({'id':key})
        if status['analysis']['routes'][0]['clear_verified']:break
        sleep(.02)
    route=status['analysis']['routes'][0]
    assert route['clear_verified'] and route['steps'][:2]==result['routes'][0]['steps'][1:]
    assert [s['target'] for s in route['steps']]==['1','2','8']
    assert games.games[state['id']]['revision']==1  # appended black is still only a plan
    count=1
    while True:
        value=jobs.execute({'id':key,'prefetch':True});count+=1
        assert value['complete'] and not value['game_after']['last_decision']['fouls']
        if value['game_after']['phase']=='finished':break
        key=value['prefetch']['id']
    assert count==4 and jobs.metrics['searches']==0 and jobs.metrics['extended_steps']==1
