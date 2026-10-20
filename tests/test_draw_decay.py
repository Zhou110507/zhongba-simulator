"""A spinning ball can lose backspin while it is still sliding (TP B.8)."""
from math import cos, sin, sqrt

import pytest

from billiards.cue import ShotInput, strike
from billiards.engine import simulate
from billiards.model import Ball, Table, Vec2, Vec3
from billiards.motion import describe
from billiards.play import PlayService
from billiards.shot_analysis import cue_motion_report


@pytest.mark.parametrize('angle',[0,.7,2.1])
def test_zero_spin_precedes_natural_roll_and_does_not_end_sliding(angle):
    s=PlayService();r=s.ball_spec.radius;a=s.physics.sliding_friction*s.physics.gravity
    d=Vec2(cos(angle),sin(angle));speed=2.;spin=-50.
    initial=Ball('cue',Vec2(10,10),d*speed,Vec3(-d.y*spin,d.x*spin,0),s.ball_spec)
    zero=-spin*r/(2.5*a);roll=(speed-r*spin)/(3.5*a)
    result=simulate([initial],Table(100,100),s.physics,max_time=roll+.01)
    for t,sign in [(zero-.01,-1),(zero+.01,1)]:
        b=result.state_at(t)[0];w=b.omega.y*d.x-b.omega.x*d.y
        assert w*sign>0 and describe(b,s.physics).phase=='sliding'
        assert b.slip.norm()>0
    at_zero=result.state_at(zero)[0]
    assert abs(at_zero.omega.y*d.x-at_zero.omega.x*d.y)<1e-10
    assert describe(at_zero,s.physics).phase=='sliding'
    assert describe(result.state_at(roll+.005)[0],s.physics).phase=='rolling'


@pytest.mark.parametrize('center_distance',[.5,.75,1.])
@pytest.mark.parametrize('cue_speed',[2.,2.5,2.8])
def test_midrange_impact_spin_matches_published_drag_formula(center_distance,cue_speed):
    s=PlayService();shot=ShotInput(0,cue_speed,0,-.5)
    cue=strike(Ball('cue',Vec2(10,10),spec=s.ball_spec),shot,s.cue)
    target=Ball('1',Vec2(10+center_distance,10),spec=s.ball_spec)
    result=simulate([cue,target],Table(100,100),s.physics,max_time=2)
    report=cue_motion_report(result);contact=report['first_target_contact']
    r=cue.spec.radius;a=s.physics.sliding_friction*s.physics.gravity;v0=cue.velocity.x
    distance=center_distance-2*r
    slide_time=(v0-r*cue.omega.y)/(3.5*a)
    slide_distance=v0*slide_time-.5*a*slide_time**2
    if distance<slide_distance:
        expected_speed=sqrt(v0*v0-2*a*distance)
        expected_spin=cue.omega.y+2.5*(v0-expected_speed)/r
        assert contact['phase']=='sliding'
    else:
        roll_speed=v0-a*slide_time
        expected_speed=sqrt(roll_speed**2-2*s.physics.rolling_friction*s.physics.gravity*(distance-slide_distance))
        expected_spin=expected_speed/r
        assert contact['phase']=='rolling'
    assert contact['speed_m_s']==pytest.approx(expected_speed,abs=1e-10)
    assert contact['forward_spin_rad_s']==pytest.approx(expected_spin,abs=1e-9)
    assert contact['surface_slip_m_s']==pytest.approx(abs(expected_speed-r*expected_spin),abs=1e-10)
    if center_distance==.75 and cue_speed==2.:
        assert 0<contact['forward_spin_rad_s']<2 and contact['phase']=='sliding'
    if center_distance==.75 and cue_speed==2.5:
        assert contact['forward_spin_rad_s']<-40


def test_motion_observation_handles_network_contacts_without_an_isolated_angle_report():
    from billiards.rules import racked_balls
    s=PlayService(table_profile='cbsa_2017');source=racked_balls(s,0,0)
    balls=tuple(strike(b,ShotInput(0,4,0,-.5),s.cue) if b.id=='cue' else b for b in source)
    result=simulate(balls,s.table,s.physics,max_time=.6,max_events=6000)
    report=cue_motion_report(result)
    assert report['first_target_contact'] is not None
    assert report['first_target_contact']['phase']=='sliding'
    assert report['first_target_contact']['forward_spin_rad_s']<0
