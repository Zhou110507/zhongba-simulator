"""Inspectable rebound angles, always measured from the rail normal."""

from dataclasses import asdict
from math import atan2, degrees


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
