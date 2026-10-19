"""Distance, spin retention and higher stroke range regressions from user feedback."""

from copy import deepcopy
from math import sqrt

import pytest

from billiards import Ball, Table, Vec2, Vec3, simulate
from billiards.cue import ShotInput, strike
from billiards.play import PlayService


@pytest.fixture(scope='module')
def service():
    return PlayService()


def test_one_metre_draw_retains_backspin_and_matches_independent_drag_formula(service):
    # Alciatore TP B.8 p.3: v(x)^2=v0^2-2 mu_s g x;
    # omega(x)=omega0 + 5(v0-v(x))/(2R). This is before any ball impact.
    initial = strike(Ball('cue',Vec2(10,10)),ShotInput(0,3.5,0,-.5),service.cue)
    result = simulate([initial,Ball('1',Vec2(11,10))],Table(1000,1000),service.physics,max_time=120)
    impact = next(e for e in result.events if e.kind=='ball_ball')
    before = next(b for b in impact.before if b.id=='cue')
    radius, v0 = initial.spec.radius, initial.velocity.x
    expected_v = sqrt(v0*v0-2*service.physics.sliding_friction*service.physics.gravity*(1-2*radius))
    expected_w = initial.omega.y+2.5*(v0-expected_v)/radius
    assert before.velocity.x == pytest.approx(expected_v,abs=1e-9)
    assert before.omega.y == pytest.approx(expected_w,abs=1e-8)
    assert before.omega.y < -50
    assert result.status == 'stopped'
    assert result.final[0].position.x < 9  # More than one metre return past its start.


def test_unobstructed_low_shot_does_not_spontaneously_reverse(service):
    initial = strike(Ball('cue',Vec2(10,10)),ShotInput(0,2.5,0,-.5),service.cue)
    result = simulate([initial],Table(1000,1000),service.physics,max_time=120)
    assert result.status=='stopped'
    assert all(result.state_at(result.duration*fraction/100)[0].velocity.x >= -1e-10 for fraction in range(101))


def test_same_one_metre_per_second_roll_matches_fast_cloth_stop_benchmark(service):
    radius = service.ball_spec.radius
    initial = Ball('cue',Vec2(10,10),Vec2(1,0),Vec3(0,1/radius,0),service.ball_spec)
    result = simulate([initial],Table(1000,1000),service.physics,max_time=120)
    assert result.status=='stopped'
    assert result.final[0].position.x-10 == pytest.approx(7.28119994175,abs=1e-8)
    assert result.duration == pytest.approx(14.5623998835,abs=1e-8)


def test_middle_power_is_a_medium_shot_and_travels_multiple_cushions(service):
    center = strike(Ball('cue',Vec2(.4,.42)),ShotInput(0,.5*service.cue.max_speed),service.cue)
    assert 2.8 < center.velocity.norm() < 3.6  # Reference medium pool speed ~7 mph.
    preset = next(p['scene'] for p in service.presets() if p['id']=='speed')
    response = service.shoot(preset)
    assert response['complete'] and not response['summary']['scratch']
    assert sum(e['kind']=='ball_cushion' for e in response['result']['events']) >= 3


@pytest.mark.parametrize('angle',[0,25,90,180])
@pytest.mark.parametrize('tip',[(0,0),(0,-.5),(.4,.2)])
def test_full_new_power_range_finishes_without_invalid_states(service,angle,tip):
    scene = deepcopy(next(p['scene'] for p in service.presets() if p['id']=='speed'))
    scene['shot'].update(angle_deg=angle,cue_speed=service.cue.max_speed,tip_x=tip[0],tip_y=tip[1])
    response = service.shoot(scene)
    assert response['complete'],response['result']['status']
    service.decode(response['next_scene'])
