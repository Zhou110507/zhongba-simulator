from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.model import Ball,Vec2
from billiards.play import PlayService
from billiards.runout import Search
from billiards.shot_prior import human_pot_cost,planning_policy,contact_cost


@pytest.fixture(scope='module')
def service():return PlayService(table_profile='cbsa_2017')


def test_expensive_three_step_continuation_does_not_collapse_to_cheap_one_step(service,monkeypatch):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    # Four own balls make the ordinary horizon exactly three, independently of
    # the endgame clear length. This is a planner selection regression, not a
    # substitute for the separate real-physics route tests.
    state['scene']['balls'].append(asdict(Ball('4',Vec2(1.4,.8),spec=service.ball_spec)))
    state['test_depth']=0
    search=Search(service,trained=False,seconds=20,evaluations=100)
    monkeypatch.setattr(search,'position_value',lambda *_:0.)
    monkeypatch.setattr(search,'forward',lambda *a,**k:None)
    def candidates(node,**kwargs):
        depth=node['test_depth']
        if depth>=3:return []
        after=deepcopy(node);after['test_depth']=depth+1
        key=len(search.forecasts);search.forecasts[key]=(node,after)
        step={'target':str(depth+1),'pocket':'top-right','cost':.1 if depth==0 else 100.,
              'position_effort':.1,'next_shot':{'cost':1.},'human':{'notes':[]},
              'secondary_contacts':[],'shot':asdict(ShotInput(0,.5)),'_forecast_key':key}
        return [(after,step)]
    monkeypatch.setattr(search,'candidates',candidates)
    result=search.solve(state)
    assert len(result['routes'][0]['steps'])==3
    assert result['requested_depth']==result['verified_depth']==3 and result['horizon_complete']


def test_budget_shortfall_continues_same_search_without_lowering_horizon(service,monkeypatch):
    search=Search(service,trained=False,seconds=10,evaluations=100)
    calls=[];before_deadline=search.deadline
    monkeypatch.setattr(search,'stopped',lambda:True)
    def solve(state,**kwargs):
        calls.append(kwargs)
        return {'routes':[{'steps':[{}]}],'horizon_complete':len(calls)==2}
    monkeypatch.setattr(search,'solve',solve)
    result=search.plan({},max_depth=3)
    assert result['horizon_complete'] and result['continued_for_horizon']
    assert calls==[{'max_depth':3},{'max_depth':3}]
    assert search.deadline>before_deadline and search.cap==200


def test_cancelled_planner_does_not_retry_for_horizon(service,monkeypatch):
    search=Search(service,trained=False,cancelled=lambda:True)
    calls=[]
    monkeypatch.setattr(search,'solve',lambda *a,**k:(calls.append(1) or {'routes':[],'status':'cancelled'}))
    assert search.plan({})['status']=='cancelled' and len(calls)==1


def test_budget_extension_starts_at_certified_endpoint_and_keeps_prefix(service,monkeypatch):
    search=Search(service,trained=False,seconds=10,evaluations=100)
    start=GameStore(service).new({'scenario':'ai_endgame'})
    anchor=deepcopy(start);anchor['audit_endpoint']=True
    final=deepcopy(anchor);final['audit_endpoint']='next'
    def step(target):return {'target':target,'shot':asdict(ShotInput(0,1.)),
                             'cost':1.,'position_effort':.1}
    prefix=[step('1'),step('2')];calls=[]
    def solve(state,*,max_depth=None):
        calls.append((state,max_depth))
        first=len(calls)==1;steps=deepcopy(prefix) if first else [step('3')]
        return {'status':'found','routes':[{'steps':steps,'clear_verified':False,'reasons':[]}],
                '_forecasts':[[(start,anchor),(anchor,anchor)] if first else [(anchor,final)]],
                'requested_depth':3 if first else 1,'verified_depth':len(steps),
                'horizon_complete':not first,'horizon_limit':'budget_exhausted' if first else None,
                'evaluations':0,'elapsed':0.}
    monkeypatch.setattr(search,'solve',solve);monkeypatch.setattr(search,'stopped',lambda:True)
    value=search.plan(start)
    assert calls==[(start,None),(anchor,1)]
    assert value['routes'][0]['steps'][:2]==prefix
    assert value['requested_depth']==value['verified_depth']==3 and value['horizon_complete']


def test_one_failed_execution_probe_disqualifies_an_exact_nominal_pot(service,monkeypatch):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    search=Search(service,trained=False,seconds=10,evaluations=20);calls=[]
    monkeypatch.setattr('billiards.runout.shot_options',lambda *a:[])
    def forward(before,shot):
        calls.append(shot)
        pocket=None if shot.angle_deg>.05 and shot.angle_deg<1 else 'top-right'
        result=SimpleNamespace(final=(Ball('1',Vec2(.5,.5),pocket=pocket),))
        after={**state,'last_decision':{'fouls':[]},'winner':None}
        return result,after,{}
    monkeypatch.setattr(search,'forward',forward)
    value=search.human_margin(state,ShotInput(0,1.),'1','top-right')
    assert len(calls)==4 and value['pot_passed']==3 and not value['allowed']


def test_narrow_pot_collision_stop_and_cue_jaw_position_have_large_costs():
    wide={'cost':1.,'pot_difficulty':.5,'aim_half_window_deg':.15}
    narrow={**wide,'aim_half_window_deg':.015}
    assert human_pot_cost(narrow)>human_pot_cost(wide)+2.
    assert contact_cost([['cue','9']],'1',[])>=5.
    assert contact_cost([['cue','9']],'1',['2'])>4.
    assert planning_policy()['cue_jaw_contact_cost']>=4.


def test_a_stable_pot_with_a_fragile_next_position_is_not_recommended(service,monkeypatch):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    search=Search(service,trained=False,seconds=10,evaluations=100)
    option={'target':'1','pocket':'top-right','angle':0.,'desired':Vec2(1,0)}
    monkeypatch.setattr('billiards.runout.shot_options',lambda *a:[option])
    value=(state,{'human_margin':{'pot_passed':4,'leaf_passed':2}})
    monkeypatch.setattr(search,'aimed',lambda *a,**k:deepcopy(value))
    assert search.candidates(state,attempts=1)==[]
    value[1]['human_margin']['leaf_passed']=3
    assert len(search.candidates(state,attempts=1))==1
