"""Rule decisions tested independently from the forward physics solver."""
from copy import deepcopy
from math import sqrt

import pytest

from billiards.game import GameStore, free_table
from billiards.play import PlayService
from billiards.rules import HEAD, adjudicate, group, legal_ids, respot_ball


@pytest.fixture(scope='module')
def service():
    return PlayService(table_profile='cbsa_2017')


@pytest.fixture
def state(service):
    value=GameStore(service).new({})
    value.update(is_break=False,ball_in_hand=None)
    return value


def hit(ball='1',time=.2):
    return {'kind':'ball_ball','actors':['cue',ball],'time':time,'detail':''}


def rail(ball='cue',time=.4,detail='right'):
    return {'kind':'ball_cushion','actors':[ball],'time':time,'detail':detail}


def response(state,potted=(),events=None):
    initial=deepcopy(state['scene']['balls']);initial[0]['velocity']['x']=1
    final=deepcopy(state['scene']['balls'])
    for ball in final:
        if ball['id'] in potted:ball['pocket']='bottom-left'
    return {'complete':True,'snapshot':deepcopy(state['scene']),
            'result':{'initial':initial,'final':final,'segments':[],
                      'events':events if events is not None else [hit(),rail()]}}


def test_rack_dimensions_spots_tightness_and_numbers(service):
    state=GameStore(service).new({});balls=state['scene']['balls'];r=service.ball_spec.radius
    assert (service.table.length,service.table.width)==(2.54,1.27)
    assert {b['id'] for b in balls}=={'cue',*(str(n) for n in range(1,16))}
    assert state['foot_spot']=={'x':1.905,'y':.635}
    assert balls[1]['position']==state['foot_spot']
    assert balls[5]['id']=='8'
    assert balls[5]['position']=={'x':pytest.approx(1.905+2*sqrt(3)*r),'y':.635}
    assert {group(balls[11]['id']),group(balls[15]['id'])}=={'solid','stripe'}
    assert sum(abs(((a['position']['x']-b['position']['x'])**2+(a['position']['y']-b['position']['y'])**2)**.5-2*r)<1e-12
               for i,a in enumerate(balls[1:]) for b in balls[i+2:])==30
    service.decode(state['scene'])
    assert PlayService().table.width==1.26


@pytest.mark.parametrize('potted,rails,keep',[(('1',),0,True),((),4,False),(('8',),0,True)])
def test_legal_break_stays_open(service,state,potted,rails,keep):
    state.update(is_break=True,ball_in_hand='head')
    result=adjudicate(state,response(state,potted,[hit()]+[rail(str(i)) for i in range(1,rails+1)]),service)
    assert result['groups']==[None,None]
    assert result['turn']==(0 if keep else 1)
    assert result['phase']=='playing' and not result['last_decision']['fouls']
    assert result['last_decision']['respot_eight']==('8' in potted)


def test_break_counts_distinct_object_balls_and_warned_repeat_loses(service,state):
    state.update(is_break=True,ball_in_hand='head')
    shot=response(state,events=[hit()]+[rail('1',.3+i*.1) for i in range(4)]+[rail('cue')])
    result=adjudicate(state,shot,service)
    assert set(result['choices'])=={'rerack_self','rerack_opponent','accept_free'}
    assert result['last_decision']['break_object_cushions']==1
    state['break_warnings'][0]=1
    result=adjudicate(state,shot,service)
    assert result['winner']==1 and result['scores']==[0,1]


def test_break_scratch_and_eight_choices(service,state):
    state.update(is_break=True,ball_in_hand='head')
    out=adjudicate(state,response(state,('cue','1')),service)
    assert out['ball_in_hand']=='head' and out['needs_placement'] and out['turn']==1
    out=adjudicate(state,response(state,('cue','8')),service)
    assert out['choices']==['accept_head'] and out['winner'] is None
    out=adjudicate(state,response(state,('8',),[hit(),rail()]),service)
    assert out['turn']==0 and out['last_decision']['respot_eight']
    bad=response(state,('8',));bad['result']['initial'][0]['velocity']['x']=-1
    assert set(adjudicate(state,bad,service)['choices'])=={'accept_head','accept_position'}


@pytest.mark.parametrize('first,potted,assigned,turn',[
    ('1',('1',),'solid',0),('9',('9',),'stripe',0),('1',('9',),None,1),
    ('9',('1',),None,1),('1',('1','9'),'solid',0),('1',(),None,1)])
def test_open_table_grouping(service,state,first,potted,assigned,turn):
    out=adjudicate(state,response(state,potted,[hit(first),rail()]),service)
    assert out['groups'][0]==assigned and out['turn']==turn


@pytest.mark.parametrize('events,potted,reason',[
    ([hit('8'),rail()],(),'首碰非法'),([rail()],(),'未碰到'),
    ([rail(time=.1),hit()],(),'触球后无'),([hit()],(),'触球后无'),
    ([hit(),rail()],('cue',),'白球落袋')])
def test_standard_fouls_give_all_table_ball_in_hand(service,state,events,potted,reason):
    out=adjudicate(state,response(state,potted,events),service)
    assert out['turn']==1 and out['ball_in_hand']=='all' and out['needs_placement']
    assert any(reason in text for text in out['last_decision']['fouls'])


def test_owned_group_and_simultaneous_legal_illegal_first(service,state):
    state['groups']=['solid','stripe']
    out=adjudicate(state,response(state,('1',),[hit('9'),hit('1')]),service)
    assert out['turn']==0 and not out['last_decision']['fouls']
    out=adjudicate(state,response(state,('9',),[hit('1')]),service)
    assert out['turn']==1 and not out['last_decision']['fouls']
    out=adjudicate(state,response(state,('9',),[hit('9')]),service)
    assert out['ball_in_hand']=='all'


def only_eight_remains(state):
    state['groups']=['solid','stripe']
    for b in state['scene']['balls']:
        if b['id'] in {str(i) for i in range(1,8)}:b['pocket']='bottom-left'


@pytest.mark.parametrize('early,scratch,winner',[(True,False,1),(False,False,0),(False,True,1)])
def test_eight_ball_win_or_loss(service,state,early,scratch,winner):
    if not early:only_eight_remains(state)
    out=adjudicate(state,response(state,('8','cue') if scratch else ('8',),[hit('8')]),service)
    assert out['phase']=='finished' and out['winner']==winner
    assert out['scores'][winner]==1


def test_last_own_ball_and_eight_same_shot_loses_but_scratch_without_eight_does_not(service,state):
    only_eight_remains(state)
    next(b for b in state['scene']['balls'] if b['id']=='1')['pocket']=None
    out=adjudicate(state,response(state,('1','8')),service)
    assert out['winner']==1
    only_eight_remains(state)
    out=adjudicate(state,response(state,('cue',),[hit('8')]),service)
    assert out['winner'] is None and out['ball_in_hand']=='all'


def test_frozen_cushion_must_leave_and_return(service,state):
    ball=next(b for b in state['scene']['balls'] if b['id']=='1')
    ball['position']={'x':service.table.length-service.ball_spec.radius,'y':.4}
    shot=response(state,events=[hit(),rail('1')])
    assert adjudicate(state,shot,service)['ball_in_hand']=='all'
    moved=deepcopy(shot['snapshot']['balls']);moved[1]['position']['x']-=.1
    shot['result']['segments']=[{'start':.2,'end':.3,'balls':moved,
                                'motion':[{'acceleration':{'x':0,'y':0}} for _ in moved]}]
    assert adjudicate(state,shot,service)['ball_in_hand'] is None


def test_frozen_legal_target_must_move(service,state):
    cue=state['scene']['balls'][0];target=state['scene']['balls'][1]
    target['position']={'x':cue['position']['x']+2*service.ball_spec.radius,'y':cue['position']['y']}
    shot=response(state,events=[hit('2'),rail()])
    assert '13.1' in adjudicate(state,shot,service)['last_decision']['clauses']
    shot['result']['final'][1]['position']['x']+=.01
    assert not adjudicate(state,shot,service)['last_decision']['fouls']


def test_incomplete_physics_has_no_decision_and_respot_does_not_overlap(service,state):
    shot=response(state);shot['complete']=False
    with pytest.raises(ValueError):adjudicate(state,shot,service)
    scene=deepcopy(state['scene']);respot_ball(scene,'8',service)
    service.decode(scene)
    eight=next(b for b in scene['balls'] if b['id']=='8')
    assert eight['position']['x']>service.table.length-HEAD


@pytest.mark.parametrize('crossed',[False,True])
def test_head_ball_in_hand_cannot_hit_behind_string_before_crossing(service,state,crossed):
    state['ball_in_hand']='head'
    state['scene']['balls'][1]['position']={'x':.5,'y':.635}
    shot=response(state,events=[hit(time=.5),rail(time=.6)])
    initial=deepcopy(shot['result']['initial']);initial[0]['velocity']['x']=2 if crossed else .1
    shot['result']['segments']=[{'start':0,'end':.3,'balls':initial,
        'motion':[{'acceleration':{'x':0,'y':0}} for _ in initial]}]
    out=adjudicate(state,shot,service)
    assert any('未越过' in f for f in out['last_decision']['fouls']) is not crossed


@pytest.mark.parametrize('count',[0,1,7,15])
def test_free_table_count_seed_and_cue_location(service,count):
    data={'balls':[str(i) for i in range(1,count+1)],'cue':{'x':.5,'y':.4},'seed':112}
    a=free_table(service,data);b=free_table(service,data)
    assert a==b and len(a['scene']['balls'])==count+1
    assert a['scene']['balls'][0]['position']==data['cue']
    service.decode(a['scene'])


@pytest.mark.parametrize('change',[{'balls':['1','1']},{'balls':['16']},{'balls':[1]},
                                 {'cue':{'x':-1,'y':.3}},{'cue':{'x':True,'y':.3}}, {'seed':-1}])
def test_free_invalid_requests_rejected(service,change):
    data={'balls':['3','8','13'],'cue':{'x':.4,'y':.4},**change}
    with pytest.raises(ValueError):free_table(service,data)


def test_server_revision_placement_persistence_and_authority(service,monkeypatch):
    from pathlib import Path
    from uuid import uuid4
    directory=Path('artifacts/rules/test-matches')/uuid4().hex
    store=GameStore(service,directory);game=store.new({});key=game['id']
    with pytest.raises(ValueError,match='开球线后'):
        store.action({'id':key,'revision':0,'action':'place','x':1,'y':.4})
    game=store.action({'id':key,'revision':0,'action':'place','x':.4,'y':.4})
    assert game['revision']==1 and not game['needs_placement']
    with pytest.raises(ValueError,match='对局已更新'):
        store.action({'id':key,'revision':0,'action':'place','x':.3,'y':.4})
    assert GameStore(service,directory).get({'id':key})==game
    seen=[]
    def simulate(scene):
        seen.append(scene)
        shot=response(store.games[key],events=[hit()]);shot['complete']=False
        return shot
    monkeypatch.setattr(service,'shoot',simulate)
    data={'id':key,'revision':1,'action':'shoot','scene':{'balls':[]},'shot':game['scene']['shot']}
    preview=store.preview(data)
    assert len(seen[0]['balls'])==16 and not preview['complete']
    result=store.action(data)
    assert not result['rule_committed'] and len(seen)==1
    assert store.get({'id':key})==game


def test_weak_break_choices_and_warning_persist(service,monkeypatch):
    store=GameStore(service);game=store.new({})
    def fake(scene):
        value=response(store.games[game['id']],events=[hit()]);value['next_scene']=deepcopy(scene)
        return value
    monkeypatch.setattr(service,'shoot',fake)
    req={'id':game['id'],'revision':0,'action':'shoot','shot':game['scene']['shot']}
    after=store.action(req)['game_after']
    after=store.action({'id':game['id'],'revision':1,'action':'choice','choice':'rerack_opponent'})
    assert after['is_break'] and after['break_warnings']==[1,0]
    result=store.action({**req,'revision':2})['game_after']
    assert result['winner']==1 and result['scores']==[0,1]
    with pytest.raises(ValueError):store.action({**req,'revision':2})
    next_game=store.action({'id':game['id'],'revision':3,'action':'next_rack'})
    assert next_game['breaker']==1 and next_game['scores']==[0,1] and next_game['rack_number']==2
