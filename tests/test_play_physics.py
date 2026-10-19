from dataclasses import replace
from math import hypot

import pytest

from billiards import Ball, Physics, PocketSpec, Table, Vec2, Vec3, simulate
from billiards.cue import CueSpec, ShotInput, strike
from billiards.model import validate_scene
from billiards.pockets import outline

PLAY_TABLE = Table(2.54,1.26,'experimental-test',PocketSpec())


def test_center_cue_impulse_matches_one_dimensional_collision():
    cue = CueSpec()
    ball = Ball('cue',Vec2(.5,.5))
    result = strike(ball,ShotInput(0,1),cue)
    expected = (1+cue.restitution)/(1+ball.spec.mass/cue.effective_mass)
    assert result.velocity.x == pytest.approx(expected)
    assert result.velocity.y == 0
    assert result.omega == Vec3()
    assert result.energy < .5*cue.effective_mass


def test_tip_impulse_gives_correct_spin_and_rotational_effective_mass():
    ball = Ball('cue',Vec2(.5,.5))
    shot = ShotInput(0,1,.2,.4)
    result = strike(ball,shot)
    impulse = ball.spec.mass*result.velocity.x
    assert result.omega.y*ball.spec.inertia == pytest.approx(impulse*ball.spec.radius*.4)
    assert result.omega.z*ball.spec.inertia == pytest.approx(impulse*ball.spec.radius*.2)
    assert result.velocity.norm() < strike(ball,ShotInput(0,1)).velocity.norm()


def test_top_bottom_and_left_right_are_symmetric():
    ball = Ball('cue',Vec2(.5,.5))
    top = strike(ball,ShotInput(0,1,0,.45))
    bottom = strike(ball,ShotInput(0,1,0,-.45))
    left = strike(ball,ShotInput(0,1,-.45,0))
    right = strike(ball,ShotInput(0,1,.45,0))
    assert top.velocity == bottom.velocity
    assert top.omega.y == -bottom.omega.y
    assert left.velocity == right.velocity
    assert left.omega.z == -right.omega.z
    rotated = strike(ball,ShotInput(90,1,.2,.4))
    original = strike(ball,ShotInput(0,1,.2,.4))
    assert rotated.velocity.x == pytest.approx(0,abs=1e-12)
    assert rotated.velocity.y == pytest.approx(original.velocity.x)
    assert rotated.omega.x == pytest.approx(-original.omega.y)
    assert rotated.omega.z == original.omega.z


@pytest.mark.parametrize('shot',[ShotInput(0,0),ShotInput(0,2),ShotInput(0,1,.5,.5),
                                ShotInput(float('nan'),1)])
def test_invalid_shot_is_rejected(shot):
    with pytest.raises(ValueError):
        strike(Ball('cue',Vec2(.5,.5)),shot)


def test_follow_and_draw_are_produced_by_shot_then_shared_engine():
    table = Table(100,100)
    cue = Ball('cue',Vec2(10,10))
    target = Ball('1',Vec2(10.14,10))
    for tip,sign in ((.5,1),(-.5,-1)):
        result = simulate([strike(cue,ShotInput(0,1,0,tip)),target],table,
                          replace(Physics(),ball_restitution=1),max_time=.45)
        collision = next(event for event in result.events if event.kind=='ball_ball')
        assert collision.after[0].velocity.norm() < 1e-10
        assert result.final[0].velocity.x*sign > 0


@pytest.mark.parametrize('pocket_id',[pocket.id for pocket in outline(PLAY_TABLE).pockets])
def test_each_pocket_requires_crossing_its_capture_plane(pocket_id):
    pocket = next(pocket for pocket in outline(PLAY_TABLE).pockets if pocket.id==pocket_id)
    velocity = pocket.outward*.8
    ball = Ball('1',pocket.mouth-pocket.outward*.3,velocity,
                Vec3(-velocity.y/.028575,velocity.x/.028575,0))
    result = simulate([ball],PLAY_TABLE)
    assert result.status == 'stopped'
    assert result.final[0].pocket == pocket_id
    capture = next(event for event in result.events if event.kind=='ball_pocket')
    assert abs((capture.before[0].position-pocket.gate).dot(pocket.outward)) < 1e-8
    assert result.state_at(capture.time-1e-6)[0].pocket is None
    assert result.state_at(capture.time)[0].pocket == pocket_id
    assert result.final[0].energy == 0


def test_ball_near_pocket_is_not_deleted_by_a_large_capture_circle():
    ball = Ball('1',Vec2(PLAY_TABLE.length/2,.06))
    result = simulate([ball],PLAY_TABLE)
    assert result.final[0].pocket is None
    assert not result.events


def test_off_center_pocket_entry_hits_rounded_jaw():
    velocity = Vec2(0,-.8)
    ball = Ball('1',Vec2(PLAY_TABLE.length/2+.035,.3),velocity,Vec3(.8/.028575,0,0))
    result = simulate([ball],PLAY_TABLE,max_time=1)
    collision = next(event for event in result.events if event.kind=='ball_cushion')
    assert collision.detail.startswith('jaw:')
    assert collision.after[0].velocity.y > 0
    assert collision.after[0].energy <= collision.before[0].energy


def test_geometry_rejects_ball_in_solid_rail_or_outside_pocket_channel():
    for position in (Vec2(.5,.005),Vec2(-.2,.5)):
        with pytest.raises(ValueError):
            validate_scene([Ball('cue',position)],PLAY_TABLE,Physics())


def test_pocketed_ball_cannot_collide_and_cue_requires_respot():
    captured = Ball('cue',Vec2(1,.5),pocket='bottom-middle')
    with pytest.raises(ValueError,match='白球已落袋'):
        strike(captured,ShotInput(0,1))
    moving = Ball('1',Vec2(.7,.5),Vec2(1,0))
    result = simulate([captured,moving],PLAY_TABLE,max_time=.5)
    assert not any(event.kind=='ball_ball' for event in result.events)
    assert result.final[0].pocket == 'bottom-middle'


def test_high_speed_pocket_entry_does_not_tunnel_through_capture_plane():
    ball = Ball('1',Vec2(PLAY_TABLE.length/2,.3),Vec2(0,-20))
    physics = Physics(sliding_friction=0,rolling_friction=0,spin_deceleration=0)
    result = simulate([ball],PLAY_TABLE,physics,max_time=.1)
    assert result.final[0].pocket == 'bottom-middle'
    assert result.duration == pytest.approx(.345/20)


def test_replay_sampling_frequency_does_not_change_pocket_event_or_final_state():
    ball = Ball('cue',Vec2(PLAY_TABLE.length/2,.3),Vec2(0,-1))
    result = simulate([ball],PLAY_TABLE)
    coarse,fine = result.to_dict(12),result.to_dict(120)
    assert coarse['events'] == fine['events']
    assert coarse['final'] == fine['final']
    assert len(coarse['samples']) < len(fine['samples'])
