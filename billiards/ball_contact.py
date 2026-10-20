"""Projected spin/throw impulse, based on Alciatore TP A.14, equations 5–17.

The three-dimensional surface slip sets the horizontal friction budget. Only
the horizontal impulse and vertical-axis spin transfer are resolved: no hop,
vertical contact impulse or transfer of draw/follow spin is claimed here.
"""

from dataclasses import replace
from math import atan2, degrees, exp, hypot

from .model import Vec2, Vec3


def contact_data(a, b, physics):
    n = b.position-a.position
    n = n*(1/n.norm())
    t = Vec2(-n.y,n.x)
    relative = a.velocity-b.velocity
    normal_speed = relative.dot(n)
    horizontal = relative.dot(t)+a.spec.radius*a.omega.z+b.spec.radius*b.omega.z
    vertical = (a.spec.radius*(a.omega.x*n.y-a.omega.y*n.x)
                +b.spec.radius*(b.omega.x*n.y-b.omega.y*n.x))
    slip = hypot(horizontal,vertical)
    inverse = 1/a.spec.mass+1/b.spec.mass
    normal_impulse = max(0.0,(1+physics.ball_restitution)*normal_speed/inverse)
    effective = inverse+a.spec.radius**2/a.spec.inertia+b.spec.radius**2/b.spec.inertia
    mu = (physics.ball_friction_a+physics.ball_friction_b*exp(-physics.ball_friction_c*slip)
          if physics.ball_friction_model=='alciatore' else physics.ball_friction)
    enabled = physics.ball_contact_model=='projected_throw'
    factor = min(mu*normal_impulse/slip,1/effective) if slip>1e-12 and enabled else 0.0
    tangential_impulse = factor*horizontal
    phase = ('none' if abs(tangential_impulse)<1e-14 else
             'sticking' if abs(tangential_impulse-horizontal/effective)<1e-12 else 'sliding')
    return {'normal':n,'tangent':t,'normal_speed_m_s':normal_speed,
            'horizontal_slip_m_s':horizontal,'vertical_slip_m_s':vertical,
            'surface_slip_m_s':slip,'friction_coefficient':mu if enabled else 0.0,
            'normal_impulse_Ns':normal_impulse,'tangential_impulse_Ns':tangential_impulse,
            'phase':phase,'model':physics.ball_contact_model}


def resolve_ball_contact(a, b, physics):
    data = contact_data(a,b,physics)
    n,t = data['normal'],data['tangent']
    jn,jt = data['normal_impulse_Ns'],data['tangential_impulse_Ns']
    impulse = n*jn+t*jt
    return (replace(a,velocity=a.velocity-impulse*(1/a.spec.mass),
                    omega=Vec3(a.omega.x,a.omega.y,a.omega.z-a.spec.radius*jt/a.spec.inertia)),
            replace(b,velocity=b.velocity+impulse*(1/b.spec.mass),
                    omega=Vec3(b.omega.x,b.omega.y,b.omega.z-b.spec.radius*jt/b.spec.inertia)))


def impact_report(a, b, after_b, physics):
    data = contact_data(a,b,physics)
    delta = after_b.velocity-b.velocity
    n,t = data.pop('normal'),data.pop('tangent')
    data['throw_angle_deg'] = degrees(atan2(delta.dot(t),delta.dot(n))) if delta.norm()>1e-12 else 0.0
    data['target_spin_after_rad_s'] = after_b.omega.z
    data['scope'] = 'Horizontal throw and z-spin transfer; vertical impulse and airborne motion omitted.'
    return data
