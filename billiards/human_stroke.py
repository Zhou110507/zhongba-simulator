"""Conservative AI-only playability envelope; never changes forward physics.

Rear-ball interference is a horizontal shaft/sphere clearance test. Rail bridge
restrictions are an explicit engineering policy, not a 3-D rail/cue simulation.
Elevated draw, masse, jumps and double-hit-sensitive close strokes are excluded.
"""
import json
from math import cos, radians, sin, sqrt

from .model import Vec2
from .planner_routes import segment_distance


def load_policy(service):
    return json.loads((service.root/'configs'/'ai_human_policy.json').read_text(encoding='utf-8'))


def check_stroke(balls, shot, table, policy):
    cue = next(b for b in balls if b.id == 'cue')
    direction = Vec2(cos(radians(shot.angle_deg)), sin(radians(shot.angle_deg)))
    side = Vec2(direction.y, -direction.x)* (shot.tip_x*cue.spec.radius)
    contact = cue.position-direction*(cue.spec.radius*sqrt(max(0., 1-shot.tip_x**2-shot.tip_y**2)))+side
    rear = contact-direction*policy['rear_stroke_m']
    height = cue.spec.radius*(1+shot.tip_y)
    reasons = []; notes = []
    for other in balls:
        if other.id == 'cue' or other.pocket is not None: continue
        expanded = other.spec.radius+policy['shaft_radius_m']+policy['clearance_m']
        dz = height-other.spec.radius
        if abs(dz) < expanded and segment_distance(other.position, contact, rear) < sqrt(expanded**2-dz**2):
            reasons.append(f'后斯诺：{other.id}号球侵入水平球杆空间，需要当前不支持的抬杆')
        delta = other.position-cue.position
        if delta.norm() < cue.spec.radius+other.spec.radius+policy['close_ball_gap_m'] and delta.dot(direction) > .75*delta.norm():
            reasons.append(f'白球与{other.id}号球过近，普通出杆有二次击打风险')
    back = direction*(-1)
    distances = []
    for coordinate, component, extent in ((cue.position.x, back.x, table.length), (cue.position.y, back.y, table.width)):
        if component > 1e-9: distances.append((extent-coordinate)/component)
        elif component < -1e-9: distances.append(-coordinate/component)
    rail_distance = min(distances, default=10.)
    if rail_distance < policy['rail_bridge_distance_m']:
        notes.append('后方近库：保守限制为轻柔高杆，禁止普通低杆和中杆')
        if shot.tip_y < policy['rail_min_tip_y'] or abs(shot.tip_x) > .02:
            reasons.append('后方库边限制击点，仅接受保守高杆')
        if shot.cue_speed > policy['rail_max_cue_speed_mps']:
            reasons.append('后方近库，不推荐强力出杆')
    if shot.cue_speed > policy['max_normal_cue_speed_mps']:
        reasons.append('超过普通可复刻杆法的杆速上限')
    return {'allowed': not reasons, 'reasons': reasons, 'notes': notes,
            'rear_rail_distance_mm': round(rail_distance*1000, 1), 'policy_version': policy['version']}
