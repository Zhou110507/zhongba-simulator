"""Defense must not disable ordinary offense or its position-planning queue."""
from copy import deepcopy
import json
from threading import BoundedSemaphore, Event
from time import monotonic, sleep

import pytest

from billiards.ai_cache import matches, public_analysis
from billiards.ai_jobs import AIJobs, decide
from billiards.ai_rolling import endpoint, readiness
from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.play import PlayService
from billiards.runout import Search, shot_options
from billiards.tactics import choose_contact, recovered_pot_option, tactical_features


@pytest.fixture(scope='module')
def service():
    return PlayService(table_profile='cbsa_2017')


@pytest.mark.parametrize('comfortable', [False, True])
def test_robust_pots_are_retained_when_only_the_next_position_is_difficult(service, monkeypatch, comfortable):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    search=Search(service,trained=False,seconds=10,evaluations=20)
    option=shot_options(service,state,search.policy)[0]
    monkeypatch.setattr('billiards.runout.shot_options',lambda *a:[option])
    calls=[]
    def aimed(*args):
        leaves=4 if comfortable and calls else 0
        calls.append(leaves)
        return deepcopy(state),{'human_margin':{'allowed':True,'pot_passed':4,'leaf_passed':leaves}}
    monkeypatch.setattr(search,'aimed',aimed)
    candidates=search.candidates(state,attempts=2)
    assert candidates
    if comfortable:
        assert len(candidates)==1 and candidates[0][1]['human_margin']['leaf_passed']==4
        assert 'position_recovery' not in candidates[0][1]
    else:
        assert len(candidates)==2 and all(step['position_recovery'] for _,step in candidates)
        assert all(step['human_margin']['pot_passed']==4 for _,step in candidates)


def test_empty_offense_budget_resumes_the_same_search_before_defensive_fallback(service, monkeypatch):
    search=Search(service,trained=False,seconds=10,evaluations=20)
    calls=[]
    def solve(state,**kwargs):
        calls.append((id(search),search.cap,dict(search.aimed_trials)))
        if len(calls)==1:
            search.count=search.cap
            search.aimed_trials['retained']='candidate'
        return {'status':'not_found','routes':[],'horizon_complete':False,
                'horizon_limit':'budget_exhausted' if len(calls)==1 else 'no_robust_continuation_found'}
    monkeypatch.setattr(search,'solve',solve)
    result=search.plan({})
    assert len(calls)==2 and calls[0][0]==calls[1][0]
    assert calls[1][1]==2*calls[0][1] and calls[1][2]['retained']=='candidate'
    assert result['continued_for_horizon']


def test_cached_failures_do_not_keep_reusing_the_same_shortlist(service,monkeypatch):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    search=Search(service,trained=False,seconds=10,evaluations=20)
    option=shot_options(service,state,search.policy)[0]
    monkeypatch.setattr('billiards.runout.shot_options',lambda *a:[option])
    examined=set()
    def aimed(state,option,speed,tip_y,tip_x):
        profile=(speed,tip_y,tip_x)
        if profile in examined:search.reused_candidate_trials+=1
        else:examined.add(profile)
        return None
    monkeypatch.setattr(search,'aimed',aimed)
    assert search.candidates(state,attempts=2)==[] and len(examined)==2
    assert search.candidates(state,attempts=2)==[] and len(examined)==4


def test_empty_root_explores_remaining_profiles_before_claiming_no_attack(service,monkeypatch):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    after=deepcopy(state);after.update(phase='finished',winner=state['turn'])
    search=Search(service,trained=False,seconds=10,evaluations=20);calls=[]
    step={'target':'8','pocket':'top-right','shot':state['scene']['shot'],'cost':1.,
          'position_effort':.1,'human':{'notes':[]},'secondary_contacts':[],
          'next_shot':None,'_forecast_key':0}
    search.forecasts[0]=(state,after)
    def candidates(source,*,attempts):
        calls.append(attempts);search.aimed_trials[len(calls)]=None
        return [(after,step)] if len(calls)==3 else []
    monkeypatch.setattr(search,'candidates',candidates)
    monkeypatch.setattr(search,'forward',lambda *a,**k:None)
    result=search.solve(state)
    assert calls==[12,72,72]
    assert result['routes'][0]['clear_verified']


@pytest.fixture(scope='module')
def recovered(service):
    fixture=json.loads((service.root/'tests/fixtures/ai-tactical-gate-deadlock.json').read_text(encoding='utf-8'))
    state=fixture['state'];shot=ShotInput(**fixture['analysis']['action']['shot'])
    search=Search(service,trained=False,seconds=20,evaluations=40)
    trial=search.forward(state,shot)
    assert trial and not trial[1]['last_decision']['fouls']
    result,after,human=trial
    first=next(e for e in result.events if e.kind=='ball_ball' and 'cue' in e.actors)
    target=next(b for b in result.final if b.id in after['last_decision']['potted'])
    distance=(next(b for b in result.initial if b.id=='cue').position-
              next(b for b in result.initial if b.id==target.id).position).norm()
    option=recovered_pot_option(service,{'length':distance},result,target)
    value=search.certify_pot(state,option,shot,trial,combination=True)
    assert value and value[1]['human_margin']['pot_passed']==4
    step={k:v for k,v in value[1].items() if k!='_forecast_key'}
    row={'shot':step['shot'],'after':after,'human':human,'position_step':step,
         'first_contact_cushions':0,'cushions':step['cue_cushions'],'control_risk':step['contact_cost'],
         'legal':True,'pot':True,'x':tactical_features(service,state,after,shot,result,search.policy).tolist()}
    return state,row,option,shot,trial


def attack_analysis(service,recovered,monkeypatch):
    state,row,*_=deepcopy(recovered)
    monkeypatch.setattr('billiards.tactics.contact_candidates',lambda *a,**k:[deepcopy(row)])
    return state,choose_contact(service,state)


def test_tactical_pot_has_a_real_forecast_and_requires_position_continuation(service,recovered,monkeypatch):
    state,analysis=attack_analysis(service,recovered,monkeypatch)
    assert analysis['tactic']=='attack' and analysis['planning_mode']=='offensive_recovery'
    assert analysis['verified_depth']==1 and analysis['requested_depth']==3
    assert matches(endpoint(analysis),recovered[1]['after'])
    gate=readiness(analysis,state)
    assert gate['kind']=='offense' and gate['available']==1 and not gate['ready']
    assert '_forecasts' not in public_analysis(analysis)


def test_recovered_attack_waits_for_tail_search_and_never_commits_twice(service,recovered,monkeypatch):
    state,analysis=attack_analysis(service,recovered,monkeypatch)
    games=GameStore(service);games.games[state['id']]=deepcopy(state)
    jobs=AIJobs(games,BoundedSemaphore(1));entered=Event();release=Event();calls=[]
    monkeypatch.setattr('billiards.ai_jobs.decide',lambda *a,**k:deepcopy(analysis))
    def extend(service,source,depth,**kwargs):
        calls.append((deepcopy(source),depth));entered.set()
        assert release.wait(5)
        return {'status':'not_found','routes':[]}
    monkeypatch.setattr('billiards.ai_jobs.extend',extend)
    monkeypatch.setattr('billiards.ai_jobs.repair',lambda *a,**k:None)
    try:
        key=jobs.start({'id':state['id'],'revision':state['revision']})['id']
        assert entered.wait(2)
        assert calls[0][1]==2 and matches(calls[0][0],endpoint(analysis))
        with pytest.raises(ValueError,match='等待前瞻补齐'):
            jobs.execute({'id':key})
        assert games.games[state['id']]['revision']==state['revision']
        release.set();deadline=monotonic()+3
        while monotonic()<deadline:
            gate=jobs.status({'id':key})['analysis']['execution_gate']
            if gate['ready']:break
            sleep(.005)
        assert gate['ready'] and gate['recovery']
        value=jobs.execute({'id':key})
        assert value['complete'] and value['rule_committed']
        assert value['game_after']['last_decision']['potted']==['5']
        assert not value['game_after']['last_decision']['fouls']
        with pytest.raises(ValueError):jobs.execute({'id':key})
        assert games.games[state['id']]['revision']==state['revision']+1
    finally:release.set()


def test_reentry_does_not_relax_the_existing_pot_perturbation_check(service,recovered,monkeypatch):
    state,_,option,shot,trial=deepcopy(recovered)
    search=Search(service,trained=False,seconds=10,evaluations=20)
    monkeypatch.setattr(search,'human_margin',lambda *a,**k:{'allowed':False,'pot_passed':3,'leaf_passed':4})
    assert search.certify_pot(state,option,shot,trial,combination=True) is None


@pytest.mark.parametrize('previous',['safety','escape'])
def test_previous_defense_never_selects_a_permanent_tactical_mode(service,monkeypatch,previous):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    state['history'].append({'tactic':previous,'potted':[],'fouls':[]})
    calls=[]
    def plan(search,source,**kwargs):
        calls.append((deepcopy(source),search.cap,search.deadline-search.started))
        return {'status':'found','routes':[{'steps':[{'shot':source['scene']['shot']}]}]}
    monkeypatch.setattr(Search,'plan',plan)
    monkeypatch.setattr('billiards.tactics.choose_contact',lambda *a,**k:pytest.fail('Skipped ordinary offensive search'))
    result=decide(service,state)
    assert result['routes'] and calls[0][1:]==(1800,30)
    assert matches(calls[0][0],state)
