"""Independent limits, symmetries, passivity and convergence for rail impacts."""

from dataclasses import replace
from math import atan2, cos, radians, sin
import random

import pytest

from billiards import Ball, Physics, Table, Vec2, Vec3, simulate
from billiards.cushion import resolve_cushion
from billiards.scenarios import acceptance_scenes
from billiards.diagnostics import cushion_observations

R = .028575
TABLE = Table()


@pytest.mark.parametrize("angle", [0,15,45,75])
@pytest.mark.parametrize("restitution", [.5,1.0])
def test_zero_friction_limit_matches_analytic_reflection(angle,restitution):
    v = Vec2(cos(radians(angle)),sin(radians(angle)))
    b = Ball("cue",Vec2(TABLE.length-R,.5),v)
    p = Physics(sliding_friction=0,cushion_friction=0,cushion_restitution=restitution)
    out = resolve_cushion(b,"right",TABLE,p)
    assert out.velocity.x == pytest.approx(-restitution*v.x,abs=1e-11)
    assert out.velocity.y == pytest.approx(v.y,abs=1e-11)
    assert out.omega == Vec3()
    if restitution == 1:
        assert atan2(abs(out.velocity.y),abs(out.velocity.x)) == pytest.approx(radians(angle),abs=1e-11)


def test_cushion_changes_horizontal_spin_instead_of_preserving_old_roll():
    b = Ball("cue",Vec2(TABLE.length-R,.5),Vec2(1,.3),Vec3(-.3/R,1/R,0))
    out = resolve_cushion(b,"right",TABLE,Physics())
    assert abs(out.omega.y-b.omega.y) > 1
    assert out.velocity.x < 0
    assert out.energy < b.energy


def test_opposite_side_spin_changes_rebound_in_opposite_directions():
    b = Ball("cue",Vec2(TABLE.length-R,.5),Vec2(1,0),Vec3(0,1/R,20))
    positive = resolve_cushion(b,"right",TABLE,Physics())
    negative = resolve_cushion(replace(b,omega=Vec3(0,1/R,-20)),"right",TABLE,Physics())
    assert positive.velocity.y*negative.velocity.y < 0
    assert positive.velocity.y == pytest.approx(-negative.velocity.y,abs=1e-12)
    assert positive.velocity.x == pytest.approx(negative.velocity.x,abs=1e-12)


def test_rotating_entire_collision_rotates_the_result():
    p, table = Physics(),Table(2,2)
    b = Ball("cue",Vec2(2-R,.5),Vec2(1,.3),Vec3(-.3/R,1/R,20))
    a = resolve_cushion(b,"right",table,p)
    rotated = replace(b,position=Vec2(1,2-R),velocity=Vec2(-.3,1),
                      omega=Vec3(-1/R,-.3/R,20))
    c = resolve_cushion(rotated,"top",table,p)
    assert c.velocity.x == pytest.approx(-a.velocity.y,abs=1e-12)
    assert c.velocity.y == pytest.approx(a.velocity.x,abs=1e-12)
    assert c.omega.x == pytest.approx(-a.omega.y,abs=1e-11)
    assert c.omega.y == pytest.approx(a.omega.x,abs=1e-11)
    assert c.omega.z == pytest.approx(a.omega.z,abs=1e-11)


def test_06_first_collision_converges_under_impulse_step_refinement():
    s = next(s for s in acceptance_scenes() if s["id"]=="rail")
    velocities = []
    for steps in (512,1024,2048):
        r = simulate(s["balls"],s["table"],replace(s["physics"],cushion_steps=steps),max_time=.5)
        event = next(e for e in r.events if e.kind=="ball_cushion")
        velocities.append(event.after[0].velocity)
    coarse = (velocities[1]-velocities[0]).norm()
    fine = (velocities[2]-velocities[1]).norm()
    assert fine < coarse
    assert (velocities[2]-velocities[0]).norm() < 3e-4


def test_side_spin_cannot_curve_free_flight_before_first_cushion():
    s = next(s for s in acceptance_scenes() if s["id"]=="rail")
    a = simulate(s["balls"],max_time=.3)
    b = replace(s["balls"][0],omega=replace(s["balls"][0].omega,z=0))
    r = simulate([b],max_time=.3)
    assert a.final[0].position == r.final[0].position
    assert a.final[0].velocity == r.final[0].velocity


@pytest.mark.parametrize("seed", range(20))
def test_cushion_is_passive_with_arbitrary_incoming_spin(seed):
    rng = random.Random(seed)
    b = Ball("cue",Vec2(TABLE.length-R,.6),Vec2(rng.uniform(.05,2.5),rng.uniform(-2,2)),
             Vec3(*(rng.uniform(-150,150) for _ in range(3))))
    out = resolve_cushion(b,"right",TABLE,replace(Physics(),cushion_restitution=1))
    assert out.energy <= b.energy+1e-10
    assert out.velocity.x <= 0


def test_rough_double_rail_contact_is_not_resolved_in_arbitrary_order():
    b = Ball("cue",Vec2(R+.2,R+.2),Vec2(-1,-1))
    r = simulate([b],physics=Physics(sliding_friction=0,rolling_friction=0),max_time=.3)
    assert r.status == "unsupported_coupled_contact"


def test_ideal_control_is_explicitly_truncated_and_has_equal_angles():
    s = next(s for s in acceptance_scenes() if s["id"]=="rail_mirror")
    r = simulate(s["balls"],s["table"],s["physics"],max_time=s["max_time"])
    audit = cushion_observations(r)
    assert r.status == "max_time"
    assert r.final[0].velocity.norm() > 0
    assert audit[0]["incident_deg"] == pytest.approx(audit[0]["immediate_deg"],abs=1e-10)
    assert all(m.acceleration==Vec2() for part in r.segments for m in part.motions)
