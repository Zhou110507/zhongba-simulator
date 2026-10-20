"""Explain first contact using recorded engine states, never an aiming shortcut."""

from math import atan2, degrees

from .model import Vec2
from .ball_contact import impact_report
from .motion import describe


def cue_motion_report(result):
    """Observe spin and slip independently of the isolated-impact angle report."""
    initial=next(b for b in result.initial if b.id=='cue')
    def state(ball):
        speed=ball.velocity.norm()
        direction=ball.velocity*(1/speed) if speed>1e-10 else Vec2()
        return {'speed_m_s':speed,'forward_spin_rad_s':ball.omega.y*direction.x-ball.omega.x*direction.y,
                'surface_slip_m_s':ball.slip.norm(),'phase':describe(ball,result.physics).phase}
    hit=next((e for e in result.events if e.kind=='ball_ball' and 'cue' in e.actors),None)
    before=next((b for b in hit.before if b.id=='cue'),None) if hit else None
    return {'initial':state(initial),'first_target_contact':state(before) if before else None,
            'first_target_contact_time_s':hit.time if hit else None,
            'prior_cushion':any(e.kind=='ball_cushion' and 'cue' in e.actors and e.time<hit.time for e in result.events) if hit else False}


def angle(a, b):
    if a.norm() < 1e-10 or b.norm() < 1e-10:
        return None
    return abs(degrees(atan2(a.x*b.y-a.y*b.x,a.dot(b))))


def first_contact_analysis(result):
    hit = next((e for e in result.events if e.kind=='ball_ball' and 'cue' in e.actors),None)
    if hit is None:
        return None
    if hit.detail.startswith(('cluster','hertz')):
        return None  # An isolated two-ball diagnostic cannot describe an island.
    cue = next(b for b in hit.before if b.id=='cue')
    target = next(b for b in hit.before if b.id in hit.actors and b.id!='cue')
    after = next(b for b in hit.after if b.id=='cue')
    target_after = next(b for b in hit.after if b.id==target.id)
    incoming = cue.velocity
    if incoming.norm() < 1e-10:
        return None
    normal = target.position-cue.position
    planar_spin = Vec2(cue.omega.y,-cue.omega.x)*cue.spec.radius
    ratio = -planar_spin.dot(incoming)/incoming.dot(incoming)
    # Free sliding recovery follows from linear and angular impulse balance.
    free_roll = after.velocity*(5/7)+Vec2(after.omega.y,-after.omega.x)*(2*cue.spec.radius/7)
    recovery = None
    for event in result.events:
        if event.time <= hit.time+1e-10 or 'cue' not in event.actors:
            continue
        if event.kind in ('ball_ball','ball_cushion','ball_pocket'):
            break
        if event.kind=='sliding_to_rolling':
            recovery = next(b.velocity for b in event.after if b.id=='cue')
            break
    initial_cue = next(b for b in result.initial if b.id=='cue')
    initial_target = next(b for b in result.initial if b.id==target.id)
    return {'target':target.id,'time_s':hit.time,
            'impact':impact_report(cue,target,target_after,result.physics),
            'aim_offset_deg':angle(initial_cue.velocity,initial_target.position-initial_cue.position),
            'cut_angle_deg':angle(incoming,normal),'backspin_speed_ratio':ratio,
            'immediate_direction_deg':angle(incoming,after.velocity),
            'free_roll_return_angle_deg':angle(incoming*(-1),free_roll),
            'observed_return_angle_deg':angle(incoming*(-1),recovery) if recovery is not None else None,
            'ball_separation_angle_deg':angle(target_after.velocity,recovery) if recovery is not None else None,
            'recovered_before_next_contact':recovery is not None,
            'definition':'Return angle is measured from the reverse incoming line, not the target-ball path. '
                         'Free-roll direction excludes intervening contacts; impact q=-R*omega_forward/v.'}
