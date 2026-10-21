"""AI playability, genuine model provenance, revision isolation and real clears."""
from copy import deepcopy
from dataclasses import replace
from threading import BoundedSemaphore
from time import monotonic, sleep

import numpy as np
import pytest

from billiards.ai_jobs import AIJobs, decide
from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.human_stroke import check_stroke, load_policy
from billiards.model import Ball, Vec2
from billiards.play import PlayService
from billiards.runout import MODEL_VERSION, Search, ValueModel, features, shot_options


@pytest.fixture(scope='module')
def service():return PlayService(table_profile='cbsa_2017')


def access(service,positions,angle=0,tip=0,speed=1.1):
    balls=tuple(Ball(key,Vec2(x,y),spec=service.ball_spec) for key,x,y in positions)
    return check_stroke(balls,ShotInput(angle,speed,0,tip),service.table,load_policy(service))


def test_rear_snooker_is_a_cue_space_constraint_even_when_forward_ray_is_clear(service):
    result=access(service,[('cue',1.,.6),('1',1.6,.6),('9',.83,.6)])
    assert not result['allowed'] and any('后斯诺' in s for s in result['reasons'])
    assert access(service,[('cue',1.,.6),('1',1.6,.6),('9',.60,.6)])['allowed']
    assert access(service,[('cue',1.,.6),('1',1.6,.6),('9',.83,.72)])['allowed']


@pytest.mark.parametrize('tip,allowed',[(-.5,False),(0,False),(.3,False),(.5,True)])
def test_rear_rail_restricts_tip_to_gentle_high_strokes(service,tip,allowed):
    value=access(service,[('cue',.05,.6),('1',.8,.6)],tip=tip)
    assert value['allowed']==allowed
    assert value['notes']
    assert not access(service,[('cue',.05,.6),('1',.8,.6)],tip=.5,speed=2.2)['allowed']


def test_near_a_rail_does_not_ban_draw_when_stroking_parallel_with_clear_rear_space(service):
    assert access(service,[('cue',1.,.05),('1',1.7,.05)],tip=-.3)['allowed']


def test_double_hit_sensitive_close_stroke_is_excluded(service):
    result=access(service,[('cue',1.,.6),('1',1.+2*service.ball_spec.radius+.005,.6)])
    assert not result['allowed'] and any('二次击打' in s for s in result['reasons'])


def test_default_game_and_old_saved_games_remain_local_two_player(service,tmp_path):
    games=GameStore(service,tmp_path)
    state=games.new({'seed':0});assert state['ai_player'] is None
    key=state['id'];games.games[key].pop('ai_player');games._save(games.games[key])
    restored=GameStore(service,tmp_path).get({'id':key})
    assert restored.get('ai_player') is None and len(restored['scene']['balls'])==16
    assert games.preview({'id':key,'revision':0,'shot':state['scene']['shot']})['complete']


@pytest.mark.parametrize('value',[True,-1,2,'1',[],{}])
def test_ai_side_is_strictly_validated(service,value):
    with pytest.raises(ValueError):GameStore(service).new({'ai_player':value})


def test_ai_toggle_is_revisioned_and_does_not_change_scene_scores_or_rules(service):
    games=GameStore(service);before=games.new({'seed':5})
    after=games.action({'id':before['id'],'revision':0,'action':'set_ai','ai_player':1})
    assert after['revision']==1 and after['ai_player']==1
    assert before['scene']==after['scene'] and before['scores']==after['scores']
    with pytest.raises(ValueError,match='当前不是 AI'):games.ai_snapshot({'id':after['id'],'revision':1})


def test_trained_model_has_layout_separated_provenance_and_finite_values(service):
    model=ValueModel(service);assert model.data is not None
    train=model.data['training'];assert train['sample_count']>=100 and train['total_epochs']>=100
    splits=[set(train['metrics'][name]['layout_seeds']) for name in ('train','validation','test')]
    assert all(not a&b for i,a in enumerate(splits) for b in splits[i+1:])
    state=GameStore(service).new({'scenario':'ai_endgame'})
    score=model.score(features(service,state,load_policy(service)))
    assert np.isfinite(score) and 0<=score<=1
    assert train['source']=='synthetic_shared_physics_rollouts'


def test_endgame_search_replays_a_real_rule_valid_clear_with_human_constraints(service):
    games=GameStore(service);state=games.new({'scenario':'ai_endgame','seed':0})
    original=deepcopy(state)
    search=Search(service,seconds=45,evaluations=2400)
    result=search.solve(state)
    assert state==original and result['model']==MODEL_VERSION
    assert result['status']=='found' and result['endgame']
    route=result['routes'][0];assert route['clear_verified']
    assert next(s for s in route['steps'] if s['target']=='1')['pocket']=='bottom-middle'
    assert route['steps'][-1]['target']=='8'
    current=state
    for step in route['steps']:
        balls,_=service.decode(current['scene'])
        assert check_stroke(balls,ShotInput(**step['shot']),service.table,load_policy(service))['allowed']
        response=games.action({'id':current['id'],'revision':current['revision'],'action':'shoot','shot':step['shot']})
        assert response['rule_committed'] and response['complete']
        current=response['game_after']
        assert not current['last_decision']['fouls']
        assert sum(e['kind']=='ball_ball' and 'cue' in e['actors'] for e in response['result']['events'])==1
        assert step['cue_ball_contacts']==1 and step['cue_cushions']<=load_policy(service)['max_normal_cushions']
        assert 'clean_pot' in step and 'pocket_entry_cost' in step
    assert current['phase']=='finished' and current['winner']==state['ai_player']
    assert current['scores'][state['ai_player']]==1


def test_cancelled_search_returns_no_action_or_routes(service):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    result=decide(service,state,cancelled=lambda:True)
    assert result['status']=='cancelled' and result['routes']==[] and 'action' not in result


def test_stale_or_cancelled_ai_job_cannot_execute_and_releases_capacity(service):
    games=GameStore(service);state=games.new({'scenario':'ai_endgame'})
    slots=BoundedSemaphore(1);jobs=AIJobs(games,slots)
    job=jobs.start({'id':state['id'],'revision':0})
    jobs.status(job,cancel=True)
    deadline=monotonic()+3
    while jobs.status(job)['status']=='running' and monotonic()<deadline:sleep(.01)
    assert jobs.status(job)['status']=='cancelled'
    with pytest.raises(ValueError):jobs.execute(job)
    assert slots.acquire(blocking=False);slots.release()
    for payload in ({'id':[]},{'id':'missing'},[]):
        with pytest.raises(ValueError):jobs.status(payload)


def test_revision_change_prevents_a_previously_planned_ai_action(service):
    games=GameStore(service);state=games.new({'scenario':'ai_endgame'})
    jobs=AIJobs(games,BoundedSemaphore(1))
    jobs.jobs['ready']={'status':'found','cancel':__import__('threading').Event(),
                        'game_id':state['id'],'revision':0,
                        'analysis':{'action':{'action':'shoot','shot':state['scene']['shot']}}}
    games.action({'id':state['id'],'revision':0,'action':'set_ai','ai_player':None})
    with pytest.raises(ValueError,match='对局已更新'):jobs.execute({'id':'ready'})
    current=games.get({'id':state['id']})
    assert current['revision']==1 and not current['history']


def test_free_placement_and_rule_choice_are_explicit_ai_actions(service):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    state.update(needs_placement=True,ball_in_hand='all')
    before=deepcopy(state);result=decide(service,state)
    assert result['action']['action']=='place' and state==before
    state.update(phase='choice',choices=['choose_solid','choose_stripe'],chooser=state['turn'])
    assert decide(service,state)['action']['choice'] in state['choices']


@pytest.mark.parametrize('mirror',[False,True])
def test_near_pocket_cut_is_easier_than_long_straight_object_travel(service,mirror):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    if mirror:
        for b in state['scene']['balls']:
            b['position']={'x':service.table.length-b['position']['x'],'y':service.table.width-b['position']['y']}
    options=shot_options(service,state,load_policy(service))
    near=next(o for o in options if o['target']=='1' and o['pocket']==('top-middle' if mirror else 'bottom-middle'))
    far=next(o for o in options if o['target']=='1' and o['pocket']==('top-left' if mirror else 'bottom-right'))
    assert near['cut']>far['cut']
    assert near['object_distance']<far['object_distance']/3
    assert near['aim_half_window_deg']>3*far['aim_half_window_deg']
    assert near['cost']<far['cost']


def test_near_pocket_candidate_survives_the_old_sixty_five_degree_cut_limit(service):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    state['scene']['balls'][0]['position']={'x':.4040541086647289,'y':.6492344197767196}
    options=shot_options(service,state,load_policy(service))
    near=next(o for o in options if o['target']=='1' and o['pocket']=='bottom-middle')
    assert 65<near['cut']<78 and near['object_distance']<.45


def test_custom_layout_is_a_separate_editable_game_and_only_commits_valid_setup(service):
    games=GameStore(service);original=games.new({'scenario':'ai_endgame'})
    custom=games.new({'scenario':'ai_custom','scene':original['scene'],'ai_player':1})
    assert custom['id']!=original['id'] and custom['phase']=='setup'
    with pytest.raises(ValueError):games.ai_snapshot({'id':custom['id'],'revision':0})
    with pytest.raises(ValueError):games.action({'id':custom['id'],'revision':0,'action':'shoot','shot':custom['scene']['shot']})
    bad=deepcopy(custom['scene']);bad['balls']=[b for b in bad['balls'] if b['id']!='8']
    with pytest.raises(ValueError,match='8 号球'):
        games.action({'id':custom['id'],'revision':0,'action':'finish_setup','scene':bad})
    scene=deepcopy(custom['scene']);next(b for b in scene['balls'] if b['id']=='1')['position']={'x':1.2,'y':.35}
    finished=games.action({'id':custom['id'],'revision':0,'action':'finish_setup',
                           'scene':scene,'ai_group':'stripe','ai_player':1})
    assert finished['phase']=='playing' and finished['revision']==1
    assert finished['groups']==['solid','stripe'] and finished['scene']==scene
    assert games.get({'id':original['id']})==original
    assert games.ai_snapshot({'id':custom['id'],'revision':1})['scene']==scene


def test_formal_game_cannot_be_rewritten_by_the_layout_commit_action(service):
    games=GameStore(service);state=games.new({'seed':0})
    with pytest.raises(ValueError):
        games.action({'id':state['id'],'revision':0,'action':'finish_setup','scene':state['scene']})
    assert games.get({'id':state['id']})==state


def feedback_state(service):
    import json
    data=json.loads((service.root/'training'/'ai_stage2'/'feedback-reference.json').read_text(encoding='utf8'))
    state=GameStore(service).new({'scenario':'ai_endgame'})
    state.update(scene=data['source_scene'],groups=data['source_groups'],turn=data['source_turn'])
    return state


def test_three_rail_position_is_allowed_and_leaves_better_shots_than_cheap_rail_stop(service):
    state=feedback_state(service);search=Search(service,trained=False,seconds=10,evaluations=100)
    options=shot_options(service,state,search.policy)
    three=search.aimed(state,next(o for o in options if o['target']=='3' and o['pocket']=='bottom-right'),3.2,.5)
    cheap=search.aimed(state,next(o for o in options if o['target']=='2' and o['pocket']=='top-right'),.75,0.)
    assert three and cheap
    assert three[1]['cue_cushions']>=3 and cheap[1]['cue_cushions']<three[1]['cue_cushions']
    assert three[1]['next_shot']['cost']<cheap[1]['next_shot']['cost']
    assert not three[1]['next_shot']['rear_restricted']
    assert check_stroke(service.decode(state['scene'])[0],ShotInput(**three[1]['shot']),service.table,search.policy)['allowed']


def test_route_balance_accepts_more_position_effort_for_easier_shots_but_keeps_effort_cost(service):
    search=Search(service,trained=False)
    done={'phase':'finished','winner':1,'turn':1}
    def route(pot,effort):
        step={'cost':pot+effort,'position_effort':effort,'next_shot':None}
        return done,[step],step['cost']
    assert search.route_cost(route(1.,.4))<search.route_cost(route(3.,.1))
    assert search.route_cost(route(1.,.1))<search.route_cost(route(1.,.4))


def test_moderate_side_and_firm_strokes_do_not_bypass_rail_or_rear_ball_limits(service):
    policy=load_policy(service)
    balls=service.decode(feedback_state(service)['scene'])[0]
    assert check_stroke(balls,ShotInput(0,3.2,.25,.4),service.table,policy)['allowed']
    rear=tuple(Ball(k,Vec2(x,y),spec=service.ball_spec) for k,x,y in [('cue',.05,.6),('1',.8,.6)])
    assert not check_stroke(rear,ShotInput(0,3.2,.25,-.3),service.table,policy)['allowed']


def test_verified_jaw_assisted_pot_is_kept_with_a_soft_entry_penalty(service):
    search=Search(service,trained=False,seconds=10,evaluations=30)
    first=ShotInput(25.454592179596894,1.1,-.25,0.)
    trial=search.forward(feedback_state(service),first);assert trial
    state=trial[1]
    option=next(o for o in shot_options(service,state,search.policy) if o['target']=='3' and o['pocket']=='bottom-right')
    shot=ShotInput(264.92098756494704,2.5,-.3,.3)
    physics=search.forward(state,shot)[0]
    collision=next(e for e in physics.events if e.kind=='ball_ball' and 'cue' in e.actors)
    outgoing=next(b for b in collision.after if b.id=='3').velocity
    option={**option,'angle':shot.angle_deg,'desired':outgoing*(1/outgoing.norm())}
    result=search.aimed(state,option,shot.cue_speed,shot.tip_y,shot.tip_x)
    assert result and result[1]['jaw_contacts']>=1 and not result[1]['clean_pot']
    assert 0<result[1]['pocket_entry_cost']<.4
    assert result[1]['verified'] and not result[0]['last_decision']['fouls']


def test_deployed_ai_can_open_a_normal_fifteen_ball_rule_match(service):
    games=GameStore(service);state=games.new({'seed':0,'breaker':0,'ai_player':0})
    result=decide(service,state)
    assert result['status']=='found' and result['model']==MODEL_VERSION
    assert result['action']['action']=='shoot' and result['action']['shot']['cue_speed']==4.
    value=games.action({'id':state['id'],'revision':0,**result['action']})
    assert value['complete'] and value['rule_committed']
    assert value['game_after']['revision']==1 and value['game_after']['history']
