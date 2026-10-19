"""Inspectable rebound angles, always measured from the rail normal."""

from dataclasses import asdict, replace
from math import atan2, degrees, isfinite

from .cushion import resolve_cushion
from .model import Vec3
from .motion import advance, describe


def normal_angle(velocity, wall):
    normal,tangent = ((abs(velocity.x),abs(velocity.y)) if wall in ("left","right")
                      else (abs(velocity.y),abs(velocity.x)))
    return degrees(atan2(tangent,normal)) if normal+tangent > 1e-12 else None


def cushion_observations(result):
    rows = []
    for index,event in enumerate(result.events):
        if event.kind != "ball_cushion":
            continue
        id = event.actors[0]
        before = next(b for b in event.before if b.id==id)
        after = next(b for b in event.after if b.id==id)
        rolling,recovery = None,"no_recorded_rolling_transition"
        for following in result.events[index+1:]:
            if id not in following.actors:
                continue
            if following.kind in ("ball_cushion","ball_ball"):
                recovery = "another_collision_before_rolling"
                break
            if following.kind == "sliding_to_rolling":
                b = next(b for b in following.after if b.id==id)
                rolling = normal_angle(b.velocity,event.detail)
                recovery = "rolling_recovered"
                break
        rows.append({"time":event.time,"ball":id,"wall":event.detail,
                     "incident_deg":normal_angle(before.velocity,event.detail),
                     "immediate_deg":normal_angle(after.velocity,event.detail),
                     "rolling_deg":rolling,"recovery":recovery,
                     "velocity_before":asdict(before.velocity),"velocity_after":asdict(after.velocity),
                     "omega_before":asdict(before.omega),"omega_after":asdict(after.omega)})
    return rows


def _recover_rolling(ball, physics):
    initial = ball
    elapsed = 0.0
    for _ in range(4):
        if ball.slip.norm() <= 1e-9:
            return ball, elapsed, (ball.position-initial.position).norm()
        motion = describe(ball,physics)
        if not isfinite(motion.transition_time):
            break
        elapsed += motion.transition_time
        ball = advance(ball,motion,motion.transition_time)
    return None, None, None


def first_cushion_explanation(result):
    event = next((event for event in result.events
                  if event.kind=="ball_cushion" and "cue" in event.actors),None)
    if event is None:
        return None
    incoming = next(ball for ball in event.before if ball.id=="cue")
    cases = (
        ("current", "当前滚动入射", incoming, result.physics),
        ("no_side", "仅清除碰前侧旋", replace(incoming,omega=replace(incoming.omega,z=0)),result.physics),
        ("no_rotation", "仅清除碰前全部旋转", replace(incoming,omega=Vec3()),result.physics),
        ("legacy_energy", "旧能量参数 0.80", incoming,replace(result.physics,cushion_restitution=.80)),
    )
    rows = []
    for key,label,ball,physics in cases:
        outgoing = resolve_cushion(ball,event.detail,result.table,physics)
        rolling,duration,distance = _recover_rolling(outgoing,physics)
        motion = describe(outgoing,physics)
        rows.append({"id":key,"label":label,"energetic_restitution":physics.cushion_restitution,
                     "incoming":asdict(ball),"outgoing":asdict(outgoing),
                     "rolling":asdict(rolling) if rolling is not None else None,
                     "incident_deg":normal_angle(ball.velocity,event.detail),
                     "immediate_deg":normal_angle(outgoing.velocity,event.detail),
                     "rolling_deg":normal_angle(rolling.velocity,event.detail) if rolling is not None else None,
                     "recovery_time_s":duration,"recovery_distance_m":distance,
                     "slip_after":asdict(outgoing.slip),"acceleration_after":asdict(motion.acceleration)})
    return {"time":event.time,"wall":event.detail,"cases":rows}
