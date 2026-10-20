from dataclasses import replace
from math import cos, sin, pi

import pytest

from billiards import Ball, Physics, Vec2, Vec3, simulate
from billiards.cue import ShotInput, strike
from billiards.model import validate_scene
from billiards.play import PlayService
from billiards.pockets import outline


@pytest.fixture(scope='module')
def service():
    return PlayService()


def test_all_flat_rail_ends_are_exactly_tangent_to_a_rounded_jaw(service):
    surfaces = outline(service.table).surfaces
    rails,jaws = [s for s in surfaces if s.kind=='rail'],[s for s in surfaces if s.kind=='jaw']
    assert len(rails)==6 and len(jaws)==12
    for rail in rails:
        direction = rail.end-rail.start
        for endpoint in (rail.start,rail.end):
            matches = [jaw for jaw in jaws if abs((endpoint-jaw.start).norm()-jaw.radius)<1e-10
                       and abs((endpoint-jaw.start).dot(direction))<1e-10]
            assert len(matches)==1


@pytest.mark.parametrize('index',range(6))
def test_all_six_throats_have_the_declared_clear_width_and_capture(service,index):
    geometry = outline(service.table)
    pocket = geometry.pockets[index]
    jaws = [s for s in geometry.surfaces if s.id.startswith('jaw:'+pocket.id+':')]
    assert (jaws[1].start-jaws[0].start).norm()-2*jaws[0].radius == pytest.approx(2*pocket.half_width)
    ball = Ball('1',pocket.mouth-pocket.outward*.35,pocket.outward*3)
    result = simulate([ball],service.table,service.physics,max_time=2)
    assert result.final[0].pocket == pocket.id
    assert not any(e.kind=='ball_cushion' for e in result.events)


@pytest.mark.parametrize('theta',[0,pi/8,pi/4,3*pi/8,pi/2])
def test_rounded_side_jaw_normals_match_exact_circle_and_join_without_double_hit(service,theta):
    geometry = outline(service.table)
    jaw = next(s for s in geometry.surfaces if s.id=='jaw:bottom-middle:-1')
    # This jaw is the left side: inward normals cover the upper-right quadrant.
    n = Vec2(cos(theta),sin(theta))
    initial = Ball('cue',jaw.start+n*(jaw.radius+service.ball_spec.radius+.003),n*(-.4))
    physics = Physics(sliding_friction=0,rolling_friction=0,spin_deceleration=0,
                      cushion_model='frictionless',cushion_restitution=1)
    # Probe the full mathematical arc without the v3 absorbing support lip.
    table = replace(service.table,pockets=replace(service.table.pockets,version='tangent-jaws-v2'))
    result = simulate([initial],table,physics,max_time=.02)
    contacts = [e for e in result.events if e.kind=='ball_cushion']
    assert len(contacts)==1
    after = contacts[0].after[0]
    assert after.velocity.x == pytest.approx(.4*n.x,abs=1e-8)
    assert after.velocity.y == pytest.approx(.4*n.y,abs=1e-8)
    assert after.energy == pytest.approx(initial.energy,abs=1e-10)


def test_flared_entry_outside_rectangle_is_valid_until_capture_not_an_invisible_wall(service):
    ball = Ball('1',Vec2(service.table.length/2+.02,-.005))
    validate_scene([ball],service.table,service.physics)
    with pytest.raises(ValueError):
        validate_scene([replace(ball,position=Vec2(service.table.length/2+.06,-.005))],service.table,service.physics)


def test_opposite_pockets_and_jaw_curves_are_mirrored(service):
    geometry = outline(service.table)
    reflected = lambda p: Vec2(service.table.length-p.x,service.table.width-p.y)
    for pocket in geometry.pockets:
        other = next(p for p in geometry.pockets if (p.mouth-reflected(pocket.mouth)).norm()<1e-9)
        assert other.half_width==pocket.half_width
        assert other.entry_depth==pocket.entry_depth
    for surface in geometry.surfaces:
        if surface.kind=='jaw':
            assert any((other.start-reflected(surface.start)).norm()<1e-9 and
                       (other.end-reflected(surface.end)).norm()<1e-9 and other.radius==surface.radius
                       for other in geometry.surfaces)


@pytest.mark.parametrize('index',range(6))
def test_slow_ball_drops_at_support_lip_without_needing_to_reach_old_deep_gate(service,index):
    pocket = outline(service.table).pockets[index]
    velocity = pocket.outward*.05
    ball = Ball('1',pocket.gate-pocket.outward*.006,velocity,
                Vec3(-velocity.y/service.ball_spec.radius,velocity.x/service.ball_spec.radius,0))
    result = simulate([ball],service.table,service.physics)
    assert result.final[0].pocket==pocket.id
    event = next(e for e in result.events if e.kind=='ball_pocket')
    assert abs((event.before[0].position-pocket.gate).dot(pocket.outward))<1e-8


@pytest.mark.parametrize('index',range(6))
def test_stationary_ball_beyond_lip_falls_but_ball_on_supported_side_stays(service,index):
    pocket = outline(service.table).pockets[index]
    for displacement,expected in ((.001,pocket.id),(-.002,None)):
        ball = Ball('1',pocket.gate+pocket.outward*displacement)
        result = simulate([ball],service.table,service.physics)
        assert result.final[0].pocket==expected
        if expected:
            assert result.events[0].time==0


def test_flared_lip_accepts_a_clear_offset_entry_without_full_radius_throat_box(service):
    pocket = next(p for p in outline(service.table).pockets if p.id=='bottom-middle')
    # At this lip the inflated jaw circles leave >20 mm of centre clearance.
    ball = Ball('1',pocket.gate+pocket.tangent*.018-pocket.outward*.002,
                pocket.outward*.12)
    result = simulate([ball],service.table,service.physics)
    assert result.final[0].pocket==pocket.id


def test_weak_two_ball_shot_drops_in_new_profile_where_old_gate_left_it_in_the_hole(service):
    cue = strike(Ball('cue',Vec2(1.27,.096)),ShotInput(270,.25,0,-.5),service.cue)
    target = Ball('1',Vec2(1.27,.03))
    old_table = replace(service.table,pockets=replace(service.table.pockets,
                        version='tangent-jaws-v2',shelf_depth=.045))
    old = simulate([cue,target],old_table,service.physics)
    current = simulate([cue,target],service.table,service.physics)
    assert old.final[1].pocket is None
    assert old.final[1].position.y<-.01
    assert current.final[1].pocket=='bottom-middle'
    assert current.final[0].pocket is None
