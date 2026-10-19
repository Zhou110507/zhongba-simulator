from math import radians, sin, cos, atan2, degrees, asin

import pytest

from billiards import Ball, Physics, Table, Vec2, Vec3, simulate
from billiards.cue import ShotInput, strike
from billiards.play import PlayService
from billiards.shot_analysis import first_contact_analysis


@pytest.mark.parametrize('cut_deg',[1,5,15,30])
@pytest.mark.parametrize('q',[.5,1,1.25])
def test_draw_direction_matches_closed_form_equal_mass_collision_and_slip_recovery(cut_deg,q):
    # Independent impulse balance: v_after=v-(1+e)/2*(v.n)n;
    # v_roll=(5*v_after+2*R*omega_planar)/7. No aim helper is used.
    radius,velocity,e = .028575,2,.95
    theta=radians(cut_deg)
    normal=Vec2(cos(theta),sin(theta))
    cue=Ball('cue',Vec2(10,10),Vec2(velocity,0),Vec3(0,-q*velocity/radius,0))
    target=Ball('1',cue.position+normal*(2*radius))
    result=simulate([cue,target],Table(100,100),Physics(),max_time=60)
    data=first_contact_analysis(result)
    vx=velocity*(1-(1+e)/2*cos(theta)**2)
    vy=-velocity*(1+e)/2*cos(theta)*sin(theta)
    expected_x=(5*vx-2*q*velocity)/7
    expected_y=5*vy/7
    expected=abs(degrees(atan2(-expected_y,-expected_x)))
    assert data['cut_angle_deg']==pytest.approx(cut_deg,abs=1e-9)
    assert data['observed_return_angle_deg']==pytest.approx(expected,abs=1e-8)
    assert data['free_roll_return_angle_deg']==pytest.approx(expected,abs=1e-8)


def test_small_aim_error_is_magnified_by_ball_spacing_and_matches_independent_geometry():
    service=PlayService()
    cue=strike(Ball('cue',Vec2(10,10)),ShotInput(.5,2.8,0,-.5),service.cue)
    result=simulate([cue,Ball('1',Vec2(10.75,10))],Table(100,100),service.physics,max_time=120)
    data=first_contact_analysis(result)
    assert data['aim_offset_deg']==pytest.approx(.5)
    expected_cut=degrees(asin(.75*sin(radians(.5))/(2*cue.spec.radius)))
    assert data['cut_angle_deg']==pytest.approx(expected_cut,abs=1e-9)
    assert 18.9 < data['observed_return_angle_deg'] < 19.0


def test_closer_low_shot_keeps_more_spin_and_returns_at_a_tighter_angle_for_same_cut():
    service=PlayService()
    values=[]
    for spacing in (.2,.75):
        cue=strike(Ball('cue',Vec2(10,10)),ShotInput(0,2.8,0,-.5),service.cue)
        # Fix the actual cut at 6 degrees rather than the cue's aiming offset.
        across=2*cue.spec.radius*sin(radians(6))
        result=simulate([cue,Ball('1',Vec2(10+spacing,10+across))],Table(100,100),service.physics,max_time=120)
        values.append(first_contact_analysis(result))
    assert values[0]['backspin_speed_ratio']>values[1]['backspin_speed_ratio']
    assert values[0]['observed_return_angle_deg']<values[1]['observed_return_angle_deg']
