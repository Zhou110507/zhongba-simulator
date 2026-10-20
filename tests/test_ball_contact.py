from dataclasses import replace
from math import atan, cos, degrees, radians, sin
import random

import pytest

from billiards import Ball, Physics, Vec2, Vec3, simulate, Table
from billiards.ball_contact import contact_data, resolve_ball_contact


P = Physics(ball_contact_model='projected_throw',ball_friction_model='constant',ball_friction=.06)


def pair(vx=1,vy=0,wz=0,wy=0):
    a = Ball('cue',Vec2(1,1),Vec2(vx,vy),Vec3(0,wy,wz))
    return a,Ball('1',Vec2(1+2*a.spec.radius,1))


def test_constant_friction_half_ball_throw_matches_published_friction_limit():
    a,b = pair(cos(radians(30)),sin(radians(30)))
    aa,bb = resolve_ball_contact(a,b,replace(P,ball_restitution=1))
    assert degrees(atan(bb.velocity.y/bb.velocity.x))==pytest.approx(degrees(atan(.06)))
    assert bb.omega.z<0 and aa.omega.z<0


def test_sticking_cap_stops_slip_without_reversing_it():
    a,b = pair(1,.01)
    aa,bb = resolve_ball_contact(a,b,P)
    assert contact_data(aa,bb,P)['horizontal_slip_m_s']==pytest.approx(0,abs=1e-12)
    assert bb.velocity.y==pytest.approx(.01/7)


def test_gearing_spin_cancels_throw_even_with_a_cut():
    a,b = pair(1,.4)
    a = replace(a,omega=Vec3(0,0,-.4/a.spec.radius))
    aa,bb = resolve_ball_contact(a,b,P)
    assert bb.velocity.y==pytest.approx(0)
    assert bb.omega.z==0


def test_follow_and_draw_surface_slip_reduce_horizontal_throw_symmetrically():
    a,b = pair(1,.5)
    reference = replace(P,ball_friction_model='alciatore')
    values = []
    for ratio in (0,1,-1):
        spun = replace(a,omega=Vec3(0,ratio/a.spec.radius,0))
        values.append(resolve_ball_contact(spun,b,reference)[1].velocity.y)
    assert values[0]>values[1]>0
    assert values[1]==pytest.approx(values[2])


def test_speed_dependent_friction_fit_matches_the_three_published_marlow_points():
    reference = replace(P,ball_friction_model='alciatore')
    for slip,expected in ((.1*2**-.5,.11),(2**-.5,.06),(10*2**-.5,.01)):
        a,b = pair(1,slip)
        assert contact_data(a,b,reference)['friction_coefficient']==pytest.approx(expected,abs=.0006)


@pytest.mark.parametrize('seed',range(60))
def test_impulse_conserves_planar_momentum_and_angular_momentum_and_dissipates_energy(seed):
    rng=random.Random(seed)
    a,b=pair(rng.uniform(.01,3),rng.uniform(-2,2),rng.uniform(-150,150),rng.uniform(-100,100))
    a=replace(a,spec=replace(a.spec,mass=rng.uniform(.13,.19)))
    b=replace(b,velocity=Vec2(0,rng.uniform(-1,1)),omega=Vec3(0,12,rng.uniform(-50,50)))
    aa,bb=resolve_ball_contact(a,b,replace(P,ball_friction_model='alciatore'))
    momentum=lambda balls:(sum(q.spec.mass*q.velocity.x for q in balls),sum(q.spec.mass*q.velocity.y for q in balls))
    def angular(balls):
        return sum(q.spec.mass*(q.position.x*q.velocity.y-q.position.y*q.velocity.x)+q.spec.inertia*q.omega.z for q in balls)
    assert momentum((aa,bb))==pytest.approx(momentum((a,b)),abs=1e-12)
    assert angular((aa,bb))==pytest.approx(angular((a,b)),abs=1e-12)
    assert aa.energy+bb.energy<=a.energy+b.energy+1e-12
    old=contact_data(a,b,P)['horizontal_slip_m_s']
    new=contact_data(aa,bb,P)['horizontal_slip_m_s']
    assert old*new>=-1e-10
    swapped=resolve_ball_contact(b,a,replace(P,ball_friction_model='alciatore'))
    assert swapped[1].velocity.x==pytest.approx(aa.velocity.x)
    assert swapped[1].omega.z==pytest.approx(aa.omega.z)


def test_mirrored_side_spin_produces_mirrored_throw_and_target_spin():
    outputs=[]
    for sign in (-1,1):
        a,b=pair(wz=sign*30)
        outputs.append(resolve_ball_contact(a,b,P)[1])
    assert outputs[0].velocity.x==pytest.approx(outputs[1].velocity.x)
    assert outputs[0].velocity.y==pytest.approx(-outputs[1].velocity.y)
    assert outputs[0].omega.z==pytest.approx(-outputs[1].omega.z)


def test_new_default_still_has_an_explicit_frictionless_control():
    a,b=pair(1,.3,30)
    aa,bb=resolve_ball_contact(a,b,replace(P,ball_contact_model='frictionless'))
    assert bb.velocity.y==0 and bb.omega==b.omega and aa.omega==a.omega


def test_continuous_engine_records_spin_transfer_in_the_actual_contact_event():
    a,b=pair(wz=30)
    result=simulate([a,b],Table(),P,max_time=.001)
    event=next(e for e in result.events if e.kind=='ball_ball')
    assert event.time==pytest.approx(0)
    assert event.after[1].omega.z<0
