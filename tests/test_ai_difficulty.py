from copy import deepcopy
import json
from statistics import mean,pstdev
from threading import BoundedSemaphore,Event
from time import monotonic

import pytest

from billiards.ai_cache import matches,model_stamp
from billiards.ai_difficulty import LEVELS,configuration,realize
from billiards.ai_jobs import AIJobs
from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.human_stroke import check_stroke,load_policy
from billiards.model import Ball,Vec2
from billiards.play import PlayService
from billiards.runout import Search,features


@pytest.fixture(scope='module')
def service():return PlayService(table_profile='cbsa_2017')


def first_shot(service):
    audit=json.loads((service.root/'training'/'ai_stage3'/'integrated-audit.json').read_text(encoding='utf8'))
    return next(r for r in audit['rows'] if r['case']=='endgame-cache')['actions'][0]['action']['shot']


@pytest.mark.parametrize('bad',[None,True,1,'easy','',[],{}])
def test_level_validation_does_not_mutate_match(service,bad):
    games=GameStore(service);state=games.new({'scenario':'ai_endgame'})
    with pytest.raises(ValueError):games.new({'ai_level':bad})
    with pytest.raises(ValueError):games.action({'id':state['id'],'revision':0,'action':'set_ai_level','ai_level':bad})
    assert games.get({'id':state['id']})==state


def test_levels_are_revisioned_persisted_and_legacy_defaults_to_original(service,tmp_path):
    games=GameStore(service,tmp_path);state=games.new({'scenario':'ai_endgame'})
    assert state['ai_level']=='expert'
    after=games.action({'id':state['id'],'revision':0,'action':'set_ai_level','ai_level':'novice'})
    assert after['revision']==1 and after['scene']==state['scene'] and after['groups']==state['groups']
    assert not matches(state,after)
    restored=GameStore(service,tmp_path).get({'id':state['id']})
    assert restored['ai_level']=='novice' and restored['ai_noise_seed']==after['ai_noise_seed']
    games.games[state['id']].pop('ai_level');games.games[state['id']].pop('ai_noise_seed');games._save(games.games[state['id']])
    legacy=GameStore(service,tmp_path).get({'id':state['id']})
    assert legacy['ai_level']=='expert' and legacy['ai_noise_seed']


def test_every_level_has_identical_planning_features_and_candidates(service):
    base=GameStore(service).new({'scenario':'ai_endgame'});reference=None
    for level in LEVELS:
        state=deepcopy(base);state['ai_level']=level
        search=Search(service,seconds=20,evaluations=60)
        values=search.candidates(state,attempts=8)
        row=(features(service,state,search.policy).tolist(),[step for _,step in values])
        if reference is None:reference=row
        else:assert row==reference


def test_original_tier_is_exact_and_sampling_is_reproducible_without_physics(service,monkeypatch):
    state=GameStore(service).new({'scenario':'ai_endgame'});shot=first_shot(service);before=deepcopy(shot)
    monkeypatch.setattr(Search,'forward',lambda *a,**k:pytest.fail('Noise searched shot outcomes'))
    for level in LEVELS:
        state['ai_level']=level
        actual,report=realize(service,state,shot)
        assert (actual,report)==realize(service,state,shot)
        assert shot==before and actual['tip_x']==shot['tip_x'] and actual['tip_y']==shot['tip_y']
        if level=='expert':assert actual==shot and report['angle_error_deg']==report['speed_error_fraction']==0
        else:assert actual!=shot


def test_gaussian_spread_matches_profiles_and_increases_for_lower_levels(service):
    state=GameStore(service).new({'scenario':'ai_endgame'});shot=first_shot(service);observed=[]
    for level in LEVELS[:-1]:
        state['ai_level']=level;angles=[];speeds=[]
        for seed in range(1024):
            state['ai_noise_seed']=str(seed);_,r=realize(service,state,shot)
            angles.append(r['angle_error_deg']);speeds.append(r['speed_error_fraction'])
        p=configuration(service)['levels'][level]
        assert abs(mean(angles))<p['angle_sigma_deg']*.15
        assert abs(mean(speeds))<p['speed_sigma_fraction']*.15
        assert pstdev(angles)==pytest.approx(p['angle_sigma_deg'],rel=.15)
        assert pstdev(speeds)==pytest.approx(p['speed_sigma_fraction'],rel=.15)
        observed.append((pstdev(angles),pstdev(speeds)))
    assert all(a[0]>b[0] and a[1]>b[1] for a,b in zip(observed,observed[1:]))


def test_noise_obeys_near_rail_and_break_speed_bounds(service):
    state=GameStore(service).new({'scenario':'ai_endgame','ai_level':'novice'})
    state['scene']=service.snapshot([Ball('cue',Vec2(.05,.6),spec=service.ball_spec),
                                     Ball('1',Vec2(.8,.6),spec=service.ball_spec),
                                     Ball('8',Vec2(2.,.9),spec=service.ball_spec)],ShotInput(0,1.8,0,.5))
    for seed in range(40):
        state['ai_noise_seed']=str(seed)
        actual,_=realize(service,state,{'angle_deg':0.,'cue_speed':1.8,'tip_x':0.,'tip_y':.5})
        assert 0<actual['cue_speed']<=1.8
        assert check_stroke(service.decode(state['scene'])[0],ShotInput(**actual),service.table,load_policy(service))['allowed']
    state=GameStore(service).new({'seed':1,'ai_player':0,'ai_level':'novice'})
    for seed in range(40):
        state['ai_noise_seed']=str(seed)
        actual,_=realize(service,state,{'angle_deg':0.,'cue_speed':5.,'tip_x':0.,'tip_y':0.})
        assert 0<actual['cue_speed']<=5.


def test_angle_error_cannot_introduce_rear_snooker_when_original_stroke_is_feasible(service,monkeypatch):
    state=GameStore(service).new({'scenario':'ai_endgame','ai_level':'novice'})
    state['scene']=service.snapshot([Ball(k,Vec2(x,y),spec=service.ball_spec) for k,x,y in
                                    [('cue',1.,.6),('1',1.7,.6),('9',.83,.698),('8',2.,1.)]],ShotInput(0,1.1))
    class Draw:
        def __init__(self,*a):self.calls=0
        def gauss(self,*a):self.calls+=1;return -30. if self.calls==1 else 0.
    monkeypatch.setattr('billiards.ai_difficulty.random.Random',Draw)
    shot,report=realize(service,state,{'angle_deg':0.,'cue_speed':1.1,'tip_x':0.,'tip_y':0.})
    assert report['angle_projection_scale']<1
    assert check_stroke(service.decode(state['scene'])[0],ShotInput(**shot),service.table,load_policy(service))['allowed']


def prepared(service,level):
    games=GameStore(service);state=games.new({'scenario':'ai_endgame','ai_level':level})
    games.games[state['id']]['ai_noise_seed']='0';state=games.get({'id':state['id']})
    shot=first_shot(service);search=Search(service,seconds=10,evaluations=4)
    after=search.forward(state,ShotInput(**shot))[1]
    # Only the first forecast is needed to establish that this tail must expire.
    steps=[{'target':'3','shot':shot,'cost':1.},{'target':'1','shot':shot,'cost':1.}]
    analysis={'status':'found','action':{'action':'shoot','shot':shot},
              'routes':[{'steps':steps,'reasons':[]}],'_forecasts':[[(state,after),(after,after)]]}
    jobs=AIJobs(games,BoundedSemaphore(1))
    jobs.jobs['ready']={'id':'ready','status':'found','created':monotonic(),'cancel':Event(),
                        'source':state,'game_id':state['id'],'revision':0,'stamp':model_stamp(service),'analysis':analysis}
    return games,jobs,state,shot,after


def test_actual_error_is_recorded_and_invalidates_ideal_tail_before_prefetch(service,monkeypatch):
    games,jobs,state,shot,predicted=prepared(service,'advanced');seen=[];calls=[]
    original=games._simulate
    def simulate(state,actual):calls.append(actual);return original(state,actual)
    monkeypatch.setattr(games,'_simulate',simulate)
    def replan(service,actual,**kwargs):seen.append(actual);return {'status':'found','routes':[]}
    monkeypatch.setattr('billiards.ai_jobs.decide',replan)
    value=jobs.execute({'id':'ready','prefetch':True})
    assert value['complete'] and value['rule_committed'] and len(calls)==1
    report=value['ai_execution'];actual=value['game_after']
    assert report['planned_shot']==shot and report['actual_shot']==value['snapshot']['shot']
    assert report['actual_shot']!=shot and not matches(predicted,actual)
    assert actual['last_decision']['ai_execution']==actual['history'][-1]['ai_execution']==report
    assert jobs.metrics['cache_hits']==0 and state['id'] not in jobs.continuations
    if actual['turn']==actual['ai_player'] and actual['phase']=='playing':
        deadline=monotonic()+2
        from time import sleep
        while not seen and monotonic()<deadline:sleep(.005)
        assert seen and matches(seen[0],actual)


def test_incomplete_shot_retry_reuses_same_error_and_manual_shot_is_unaffected(service,monkeypatch):
    games,jobs,state,shot,_=prepared(service,'novice');seen=[]
    def incomplete(data,**kwargs):
        seen.append((data['shot'],kwargs['ai_execution']))
        return {'complete':False,'rule_committed':False,'game_after':state,'result':{}}
    monkeypatch.setattr(games,'action',incomplete)
    jobs.execute({'id':'ready'});jobs.execute({'id':'ready'})
    assert seen[0]==seen[1]
    direct=GameStore(service);state=direct.new({'scenario':'ai_endgame','ai_level':'novice'})
    value=direct.action({'id':state['id'],'revision':0,'action':'shoot','shot':shot})
    assert value['snapshot']['shot']==shot and 'ai_execution' not in value['game_after']['last_decision']


def test_changing_tier_invalidates_old_ready_action(service):
    games,jobs,state,_,_=prepared(service,'novice')
    changed=games.action({'id':state['id'],'revision':0,'action':'set_ai_level','ai_level':'expert'})
    with pytest.raises(ValueError):jobs.execute({'id':'ready'})
    assert games.get({'id':state['id']})==changed
