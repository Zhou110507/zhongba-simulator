from dataclasses import replace
from math import cos, isclose, sin, sqrt
import json
import random

import pytest

from billiards import Ball, BallSpec, Physics, Table, Vec2, Vec3, simulate
from billiards.engine import resolve_pair

LARGE = Table(1000, 500, "analytic-test")
IDEAL = Physics(sliding_friction=0, rolling_friction=0, spin_deceleration=0,
                ball_restitution=1, cushion_restitution=1,cushion_model="frictionless")
R = BallSpec().radius


def rolling(id="cue", x=10, y=10, vx=1, vy=0, wz=0):
    return Ball(id, Vec2(x,y), Vec2(vx,vy), Vec3(-vy/R, vx/R, wz))


@pytest.mark.parametrize("speed", [0.01, 0.5, 1.0, 4.0])
def test_rolling_stop_matches_analytic_distance(speed):
    p = Physics()
    start = rolling(vx=speed)
    result = simulate([start], LARGE, p)
    assert result.status == "stopped"
    assert result.duration == pytest.approx(speed/(p.rolling_friction*p.gravity))
    assert result.final[0].position.x == pytest.approx(10+speed**2/(2*p.rolling_friction*p.gravity))
    assert result.final[0].velocity == Vec2()
    assert result.final[0].omega == Vec3()


@pytest.mark.parametrize("angle", [0, 0.47, 1.7, 3.5])
def test_slide_transition_matches_independent_analytic_solution(angle):
    p, speed = Physics(), 1.2
    ts = 2*speed/(7*p.sliding_friction*p.gravity)
    b = Ball("cue", Vec2(10,10), Vec2(speed*cos(angle),speed*sin(angle)))
    result = simulate([b], LARGE, p, max_time=ts)
    end = result.final[0]
    distance = (speed+5*speed/7)*ts/2
    assert end.velocity.norm() == pytest.approx(5*speed/7)
    assert end.position.x == pytest.approx(10+distance*cos(angle))
    assert end.position.y == pytest.approx(10+distance*sin(angle))
    assert end.slip.norm() < 1e-12
    assert result.events[0].kind == "sliding_to_rolling"


def test_backspin_at_zero_translation_accelerates_ball():
    b = Ball("cue", Vec2(10,10), omega=Vec3(0,-30,0))
    r = simulate([b], LARGE, max_time=.05)
    assert r.final[0].velocity.x < 0
    assert r.final[0].position.x < 10
    assert r.final[0].energy < b.energy


@pytest.mark.parametrize("spin", [-40, 40])
def test_side_spin_decay_is_independent_of_planar_rolling(spin):
    b = rolling(vx=.1, wz=spin)
    r = simulate([b], LARGE)
    assert r.status == "stopped"
    assert r.duration == pytest.approx(4)
    assert r.final[0].position.y == 10
    assert r.final[0].position.x == pytest.approx(10+.1**2/(2*.01*9.81))
    assert r.final[0].omega == Vec3()


def test_pure_spin_stays_in_place_and_stops():
    b = Ball("cue", Vec2(1,.5), omega=Vec3(0,0,25))
    r = simulate([b])
    assert r.duration == 2.5
    assert r.final[0].position == b.position
    assert r.state_at(1)[0].omega.z == 15


def test_exact_coincident_slide_and_spin_stop():
    ts = 2/(7*.2*9.81)
    b = Ball("cue", Vec2(10,10), Vec2(1,0), Vec3(0,0,10*ts))
    r = simulate([b], LARGE)
    assert r.status == "stopped"
    assert abs(r.state_at(ts)[0].omega.z) < 1e-12


def test_equal_mass_head_on_exchanges_velocities_without_changing_spin():
    a = Ball("cue", Vec2(.3,.6), Vec2(1,0), Vec3(0,2,3))
    b = Ball("1", Vec2(.8,.6))
    r = simulate([a,b], physics=IDEAL, max_time=.6)
    e = next(e for e in r.events if e.kind == "ball_ball")
    assert e.time == pytest.approx(.5-2*R)
    assert e.after[0].velocity.norm() == pytest.approx(0,abs=1e-12)
    assert e.after[1].velocity.x == pytest.approx(1)
    assert e.after[0].omega == a.omega
    assert r.state_at(e.time)[1].velocity.x == pytest.approx(1)


def test_unequal_mass_collision_matches_textbook_solution():
    a = Ball("cue", Vec2(10,10), Vec2(2,0), spec=BallSpec(mass=.16))
    b = Ball("1", Vec2(10+2*R,10), Vec2(-1,0), spec=BallSpec(mass=.17))
    aa, bb = resolve_pair(a,b,.8)
    expected = (.16*2+.17*(-1)-.17*.8*(2-(-1)))/.33
    assert aa.velocity.x == pytest.approx(expected)
    assert bb.velocity.x-aa.velocity.x == pytest.approx(.8*3)
    assert .16*aa.velocity.x+.17*bb.velocity.x == pytest.approx(.16*2-.17)


@pytest.mark.parametrize("angle", [.1,.5,1.0])
def test_glancing_elastic_collision_conserves_momentum_and_energy(angle):
    n = Vec2(cos(angle),sin(angle))
    a = Ball("a", Vec2(10,10), Vec2(2,.3), Vec3(1,2,3))
    b = Ball("b", a.position+n*(2*R), Vec2(-.2,0), Vec3(2,3,4))
    aa,bb = resolve_pair(a,b,1)
    assert aa.energy+bb.energy == pytest.approx(a.energy+b.energy)
    assert aa.velocity.x+bb.velocity.x == pytest.approx(a.velocity.x+b.velocity.x)
    assert aa.velocity.y+bb.velocity.y == pytest.approx(a.velocity.y+b.velocity.y)


def test_high_speed_collision_does_not_tunnel():
    a = Ball("cue",Vec2(.3,.5),Vec2(100,0))
    b = Ball("1",Vec2(.5,.5))
    r = simulate([a,b],physics=IDEAL,max_time=.003)
    e = next(e for e in r.events if e.kind == "ball_ball")
    assert e.time == pytest.approx((.2-2*R)/100,abs=1e-12)
    assert r.final[0].position.x < r.final[1].position.x


def test_accelerating_trajectory_collision_uses_quartic_ccd():
    # Arbitrary horizontal rotation produces both x and y acceleration.
    a = Ball("cue",Vec2(1,.5),Vec2(1,0),Vec3(30,0,0))
    from billiards.motion import describe, advance
    m = describe(a,Physics())
    contact = advance(a,m,.1)
    normal = contact.velocity*(1/contact.velocity.norm())
    b = Ball("1",contact.position+normal*(2*R))
    result = simulate([a,b],max_time=.12)
    e = next(e for e in result.events if e.kind == "ball_ball")
    assert e.time == pytest.approx(.1,abs=1e-9)
    assert (e.before[0].position-e.before[1].position).norm() == pytest.approx(2*R,abs=1e-10)


def test_tangent_touch_does_not_create_false_impulse():
    a = Ball("cue",Vec2(.3,.5),Vec2(1,0))
    b = Ball("1",Vec2(.8,.5+2*R))
    r = simulate([a,b],physics=IDEAL,max_time=.8)
    assert not any(e.kind == "ball_ball" for e in r.events)


@pytest.mark.parametrize("offset", [1e-4,1e-6,1e-8])
def test_near_tangent_hits_are_detected(offset):
    a = Ball("cue",Vec2(.3,.5),Vec2(10,0))
    b = Ball("1",Vec2(.8,.5+2*R-offset))
    r = simulate([a,b],physics=IDEAL,max_time=.08)
    e = next(e for e in r.events if e.kind == "ball_ball")
    assert e.time == pytest.approx((.5-sqrt((2*R)**2-(2*R-offset)**2))/10,abs=1e-9)


@pytest.mark.parametrize("wall,p,v", [
    ("left",Vec2(.3,.5),Vec2(-2,.1)),
    ("right",Vec2(2.2,.5),Vec2(2,.1)),
    ("bottom",Vec2(1,.3),Vec2(.1,-2)),
    ("top",Vec2(1,1),Vec2(.1,2)),
])
def test_each_cushion_reverses_normal_component(wall,p,v):
    b = Ball("cue",p,v,Vec3(1,2,3))
    r = simulate([b],physics=replace(IDEAL,cushion_restitution=.8),max_time=.2)
    e = next(e for e in r.events if e.kind == "ball_cushion")
    assert e.detail == wall
    end = e.after[0]
    if wall in ("left","right"):
        assert end.velocity.x == pytest.approx(-.8*v.x)
        assert end.velocity.y == v.y
    else:
        assert end.velocity.y == pytest.approx(-.8*v.y)
        assert end.velocity.x == v.x
    assert end.omega == b.omega
    assert end.energy <= b.energy


def test_rectangular_corner_contacts_are_commutative():
    b = Ball("cue",Vec2(R+.2,R+.2),Vec2(-1,-1))
    r = simulate([b],physics=IDEAL,max_time=.3)
    assert r.status == "max_time"
    assert len(r.events) == 2
    assert r.final[0].velocity == Vec2(1,1)


def test_coupled_contact_is_explicitly_unsupported():
    balls = [Ball("cue",Vec2(.3,.6),Vec2(1,0)),
             Ball("1",Vec2(.8,.6)),Ball("2",Vec2(.8+2*R,.6))]
    r = simulate(balls,physics=IDEAL,max_time=1)
    assert r.status == "unsupported_coupled_contact"
    assert not any(e.kind == "ball_ball" for e in r.events)


def test_persistent_zero_speed_contact_is_not_tunnelled():
    b = Ball("cue",Vec2(R,.6),omega=Vec3(0,-30,0))
    r = simulate([b])
    assert r.status == "unsupported_persistent_contact"
    assert r.duration == 0


def test_touching_and_separating_balls_do_not_recollide_at_zero_time():
    balls = [Ball("a",Vec2(.5,.6),Vec2(-1,0)),
             Ball("b",Vec2(.5+2*R,.6),Vec2(1,0))]
    r = simulate(balls,physics=IDEAL,max_time=.1)
    assert not r.events


def test_simulation_is_immutable_repeatable_and_sampling_independent():
    balls = (Ball("cue",Vec2(.4,.7),Vec2(1.7,.13),Vec3(0,-10,20)),
             Ball("1",Vec2(1.2,.7)))
    r1,r2 = simulate(balls),simulate(balls)
    assert r1 == r2
    assert balls[0].position == Vec2(.4,.7)
    coarse,fine = r1.to_dict(30),r1.to_dict(120)
    assert coarse["final"] == fine["final"]
    assert coarse["events"] == fine["events"]
    json.dumps(coarse,allow_nan=False)
    for s in coarse["samples"]:
        k = round(s["time"]*120)
        if k < len(fine["samples"])-1:
            assert s["balls"][0]["position"]["x"] == pytest.approx(fine["samples"][k]["balls"][0]["position"]["x"])


def test_event_and_time_limits_cannot_masquerade_as_stopped():
    b = rolling(x=1,y=.6,vx=3)
    assert simulate([b],max_time=.1).status == "max_time"
    assert simulate([b],max_events=1).status == "max_events"


@pytest.mark.parametrize("bad", [float("nan"),float("inf"),-1])
def test_invalid_numeric_inputs_fail_early(bad):
    with pytest.raises(ValueError):
        simulate([Ball("cue",Vec2(.3,.5))],max_time=bad)
    with pytest.raises(ValueError):
        simulate([Ball("cue",Vec2(.3,.5))],physics=Physics(sliding_friction=bad))


def test_invalid_geometry_and_duplicate_ids_fail_early():
    with pytest.raises(ValueError,match="overlap"):
        simulate([Ball("a",Vec2(.5,.5)),Ball("b",Vec2(.51,.5))])
    with pytest.raises(ValueError,match="unique"):
        simulate([Ball("a",Vec2(.5,.5)),Ball("a",Vec2(1,.5))])
    with pytest.raises(ValueError,match="outside"):
        simulate([Ball("a",Vec2(0,.5))])


def test_stationary_scene_and_invalid_sample_times():
    r = simulate([Ball("cue",Vec2(.5,.5))])
    assert r.status == "stopped" and r.duration == 0
    assert r.state_at(0) == r.final
    with pytest.raises(ValueError):
        r.state_at(.1)
    with pytest.raises(ValueError):
        r.to_dict(0)


@pytest.mark.parametrize("spin,expected_sign", [(-1,-1),(1,1)])
def test_draw_and_follow_emerge_from_remaining_spin(spin,expected_sign):
    # Initial spin is chosen so impact happens before the sliding transition.
    b = Ball("cue",Vec2(.5,.6),Vec2(1.5,0),Vec3(0,spin*1.5/R,0))
    target = Ball("1",Vec2(.62,.6))
    r = simulate([b,target],physics=replace(Physics(),ball_restitution=1),max_time=.12)
    collision = next(e for e in r.events if e.kind == "ball_ball")
    after = r.state_at(min(collision.time+.01,r.duration))[0]
    assert after.velocity.x*expected_sign > 0


def test_stun_requires_zero_horizontal_rotation_at_impact():
    impact_time, v0, deceleration = .04, 1.5, .2*9.81
    distance = v0*impact_time-.5*deceleration*impact_time**2
    omega = -2.5*deceleration*impact_time/R
    cue = Ball("cue",Vec2(.5,.6),Vec2(v0,0),Vec3(0,omega,0))
    target = Ball("1",Vec2(.5+distance+2*R,.6))
    r = simulate([cue,target],physics=replace(Physics(),ball_restitution=1))
    impact = next(e for e in r.events if e.kind == "ball_ball")
    assert impact.time == pytest.approx(impact_time)
    assert r.final[0].position.x == pytest.approx(.5+distance,abs=1e-10)
    assert r.final[0].velocity.norm() < 1e-10


def test_sampling_endpoint_tolerates_machine_roundoff_only():
    r = simulate([rolling(vx=.77)],LARGE)
    assert r.state_at(r.duration+1e-14) == r.final
    with pytest.raises(ValueError):
        r.state_at(r.duration+1e-6)


@pytest.mark.parametrize("seed", range(30))
def test_random_scenes_keep_bounds_separation_and_passive_energy(seed):
    rng = random.Random(seed)
    balls = []
    while len(balls) < 3:
        p = Vec2(rng.uniform(.1,2.4),rng.uniform(.1,1.16))
        if any((p-b.position).norm() < .12 for b in balls):
            continue
        balls.append(Ball(str(len(balls)),p,Vec2(rng.uniform(-2,2),rng.uniform(-2,2)),
                          Vec3(rng.uniform(-50,50),rng.uniform(-50,50),rng.uniform(-50,50))))
    r = simulate(balls)
    assert r.status == "stopped"
    previous = sum(b.energy for b in balls)
    for t in [r.duration*i/150 for i in range(151)]:
        state = r.state_at(t)
        energy = sum(b.energy for b in state)
        assert energy <= previous+1e-9
        previous = energy
        for i,b in enumerate(state):
            assert R-1e-8 <= b.position.x <= r.table.length-R+1e-8
            assert R-1e-8 <= b.position.y <= r.table.width-R+1e-8
            for other in state[i+1:]:
                assert (b.position-other.position).norm() >= 2*R-1e-8
