"""Bounded direct-first-hit inverse search, using the practice forward engine.

No separate approximate dynamics or altered cue/cloth parameters are used.
Failure within the sampling budget is not a claim of physical unreachability.
"""
from dataclasses import asdict, dataclass
from math import asin, atan2, degrees, hypot, radians, sin
from time import monotonic

from .cue import ShotInput, strike
from .engine import simulate
from .model import Ball, Vec2, validate_scene
from .play import _number
from .pockets import outline, unsupported_pocket


@dataclass(frozen=True)
class PlanRequest:
    balls: tuple
    shot: ShotInput
    target: str
    goal: Vec2
    radius: float
    pocket: str | None
    max_cushions: int
    allow_other: bool
    seconds: float
    evaluations: int


def decode_request(service, data):
    if not isinstance(data, dict):
        raise ValueError('需要反算请求')
    balls, shot = service.decode(data.get('scene'))
    target = data.get('target')
    if not isinstance(target, str) or not any(b.id == target and b.id != 'cue' and b.pocket is None for b in balls):
        raise ValueError('请选择台面上的目标球')
    if next(b for b in balls if b.id == 'cue').pocket is not None:
        raise ValueError('请先把白球放回台面')
    if any(unsupported_pocket(b, service.table) is not None for b in balls if b.id in ('cue', target)):
        raise ValueError('白球和指定目标球须放在有支撑的台面上')
    goal = data.get('goal')
    if not isinstance(goal, dict):
        raise ValueError('请指定白球终点')
    point = Vec2(_number(goal.get('x'), '终点 X'), _number(goal.get('y'), '终点 Y'))
    # Other balls may move; validate the goal against the table, not the initial rack.
    goal_ball = Ball('goal', point, spec=service.ball_spec)
    validate_scene((goal_ball,), service.table, service.physics)
    if unsupported_pocket(goal_ball, service.table) is not None:
        raise ValueError('白球终点不能位于落袋区域')
    radius = _number(goal.get('radius', .06), '终点容差')
    if not .01 <= radius <= .3:
        raise ValueError('终点容差须在 10–300 mm 之间')
    pocket = data.get('pocket')
    if pocket == '': pocket = None
    if pocket is not None and (not isinstance(pocket, str) or pocket not in {'any', *(p.id for p in outline(service.table).pockets)}):
        raise ValueError('未知目标球袋')
    cushions = data.get('max_cushions', 2)
    if isinstance(cushions, bool) or not isinstance(cushions, int) or not 0 <= cushions <= 4:
        raise ValueError('白球碰库上限须为 0–4 的整数')
    allow = data.get('allow_other', False)
    if not isinstance(allow, bool):
        raise ValueError('其他触球选项须为布尔值')
    seconds = _number(data.get('seconds', 12), '计算预算')
    evaluations = data.get('evaluations', 320)
    if not 2 <= seconds <= 30 or isinstance(evaluations, bool) or not isinstance(evaluations, int) or not 12 <= evaluations <= 1000:
        raise ValueError('计算预算须为 2–30 秒、12–1000 次')
    return PlanRequest(balls, shot, target, point, radius, pocket, cushions, allow, seconds, evaluations)


def assess(result, request):
    cue = next(b for b in result.final if b.id == 'cue')
    target = next(b for b in result.final if b.id == request.target)
    contacts = [e for e in result.events if 'cue' in e.actors and e.kind in ('ball_ball', 'ball_cushion', 'ball_pocket')]
    first = contacts[0] if contacts else None
    first_ok = bool(first and first.kind == 'ball_ball' and request.target in first.actors)
    banks = sum(e.kind == 'ball_cushion' for e in contacts)
    ball_contacts = [e for e in contacts if e.kind == 'ball_ball']
    other = any(request.target not in e.actors for e in ball_contacts)
    pot_ok = request.pocket is None or (target.pocket is not None if request.pocket == 'any' else target.pocket == request.pocket)
    reasons = []
    if result.status != 'stopped': reasons.append('未完整停球：' + result.status)
    if not first_ok: reasons.append('未直击指定目标球')
    if cue.pocket is not None: reasons.append('白球落袋')
    if banks > request.max_cushions: reasons.append('白球碰库超限')
    if other and not request.allow_other: reasons.append('白球碰到其他目标球')
    if not pot_ok: reasons.append('目标球未按要求进袋')
    error = (cue.position-request.goal).norm()
    # Pocket-distance guidance helps an infeasible pot seed, but never certifies it.
    pot_distance = 0.
    if not pot_ok:
        pockets = [p for p in outline(result.table).pockets if request.pocket == 'any' or p.id == request.pocket]
        points = [target.position]
        for event in result.events:
            if request.target in event.actors:
                points.extend(b.position for b in event.before if b.id == request.target)
        pot_distance = min((point-(p.fall_center or p.gate)).norm() for point in points for p in pockets)
    return {'valid': not reasons, 'reasons': reasons, 'simulation_status': result.status, 'error_m': error,
            'cue_final': asdict(cue.position), 'target_pocket': target.pocket,
            'cue_cushions': banks, 'cue_ball_contacts': len(ball_contacts), 'inside': not reasons and error <= request.radius,
            'score': error + 5*len(reasons) + 3*pot_distance}


def _halton(index, base):
    value = 0.; weight = 1.
    while index:
        weight /= base
        value += weight*(index % base)
        index //= base
    return value


def solve(service, request, *, cancelled=lambda: False, progress=lambda value: None):
    started = monotonic(); deadline = started + request.seconds
    search_end = deadline - min(3., request.seconds*.25)
    cue = next(b for b in request.balls if b.id == 'cue')
    target = next(b for b in request.balls if b.id == request.target)
    delta = target.position-cue.position
    distance = delta.norm(); diameter = cue.spec.radius+target.spec.radius
    base = atan2(delta.y, delta.x)
    cache = {}; pool = []; count = 0; failures = {}; stage = '采样搜索'

    def stopped(): return cancelled() or monotonic() >= deadline

    def normalize(q):
        h, speed, tx, ty = q
        norm = hypot(tx, ty)
        if norm > service.cue.max_tip_offset:
            tx *= service.cue.max_tip_offset/norm; ty *= service.cue.max_tip_offset/norm
        return (max(-.97, min(.97, h)), max(.25, min(service.cue.max_speed, speed)), tx, ty)

    def shot_of(q):
        h, speed, tx, ty = normalize(q)
        return ShotInput(degrees(base+asin(h*diameter/distance)) % 360, speed, tx, ty)

    def forward(shot, *, full=False, stop=stopped):
        launched = strike(cue, shot, service.cue)
        initial = tuple(launched if b.id == 'cue' else b for b in request.balls)
        return simulate(initial, service.table, service.physics, max_time=60, max_events=6000,
                        cancel=stop, record_segments=full)

    def report():
        best = min((m['error_m'] for _, m in pool if m['valid']), default=None)
        progress({'stage': stage, 'evaluations': count, 'elapsed': round(monotonic()-started, 2),
                  'best_error_mm': None if best is None else round(best*1000, 1)})

    def evaluate(q):
        nonlocal count
        q = normalize(q); key = tuple(round(v, 9) for v in q)
        if key in cache: return cache[key]
        if cancelled() or monotonic() >= search_end or count >= request.evaluations-7: return None
        result = forward(shot_of(q), stop=lambda: cancelled() or monotonic() >= search_end)
        count += 1
        if result.status == 'cancelled': return None
        m = assess(result, request)
        if result.status != 'stopped': failures[result.status] = failures.get(result.status, 0)+1
        cache[key] = m; pool.append((q, m))
        report()
        return m

    def rank(item):
        q, m = item
        return (not m['valid'], m['score'])

    # Current aim is just one seed; a user need not already know the answer.
    seeds = [(sin(radians(request.shot.angle_deg)-base)*distance/diameter,
              request.shot.cue_speed, request.shot.tip_x, request.shot.tip_y)]
    impact_seeds = [0., -.35, .35, -.7, .7]
    if request.pocket is not None:
        for pocket in outline(service.table).pockets:
            if request.pocket != 'any' and pocket.id != request.pocket: continue
            direction = (pocket.fall_center or pocket.gate)-target.position
            direction = direction*(1/direction.norm())
            ghost = target.position-direction*diameter
            ray = ghost-cue.position
            h = sin(atan2(ray.y, ray.x)-base)*distance/diameter
            if direction.dot(ray) > 0 and abs(h) < .97: impact_seeds[:0] = [h, h-.02, h+.02]
    for h in impact_seeds:
        for speed, ty in ((1., 0.), (1.8, .45), (2.3, -.5), (2.6, -.5), (3.4, -.5), (1.4, -.25), (2.2, 0.)):
            seeds.append((h, speed, 0., ty))
    # Stratified deterministic exploration, including side spin.
    for i in range(1, 45):
        seeds.append((1.9*_halton(i, 2)-.95, .5+3.8*_halton(i, 3),
                      .7*(_halton(i, 5)-.5), 1.05*(_halton(i, 7)-.5)))
    for q in seeds:
        if evaluate(q) is None: break
    stage = '细化走位'
    starts = []
    for q, m in sorted(pool, key=rank):
        if all(sum((a-b)**2 for a, b in zip(q, s)) > .08 for s in starts): starts.append(q)
        if len(starts) == 4: break
    for q in starts:
        m = evaluate(q)
        if m is None: break
        steps = [.12, .4, .12, .12]
        while max(steps) > .003:
            improved = False
            for axis in range(4):
                for sign in (-1, 1):
                    trial = list(q); trial[axis] += sign*steps[axis]
                    v = evaluate(trial)
                    if v is None: break
                    if rank((trial, v)) < rank((q, m)):
                        q, m = normalize(trial), v; improved = True
                else: continue
                break
            else:
                if not improved: steps = [s*.5 for s in steps]
                if m['inside'] and m['error_m'] < min(.008, request.radius/4): break
                continue
            break
    stage = '同内核复验'; report()
    verified = []
    for q, m in sorted(pool, key=rank):
        if not m['valid'] or len(verified) >= 3 or stopped(): break
        shot = shot_of(q)
        if any(abs(shot.cue_speed-v['shot']['cue_speed']) < .2 and
               hypot(shot.tip_x-v['shot']['tip_x'], shot.tip_y-v['shot']['tip_y']) < .08 and
               abs(((shot.angle_deg-v['shot']['angle_deg']+180) % 360)-180) < .15 for v in verified): continue
        result = forward(shot, full=True); count += 1
        metrics = assess(result, request)
        if not metrics['valid']: continue
        metrics.pop('score')
        verified.append({'shot': asdict(shot), **metrics, 'verified': True,
                         'launch_speed': strike(cue, shot, service.cue).velocity.norm(),
                         'perturbations': None})
    # Small, explicit model perturbations; never label this a human success rate.
    stage = '微扰检查'; report()
    if verified and not stopped():
        v = verified[0]; source = v['shot']; trials = []
        for angle, speed in ((-.05, 1.), (.05, 1.), (0., .98), (0., 1.02)):
            if stopped(): break
            if source['cue_speed']*speed > service.cue.max_speed: continue
            shot = ShotInput(source['angle_deg']+angle, source['cue_speed']*speed, source['tip_x'], source['tip_y'])
            r = forward(shot); count += 1
            if r.status == 'cancelled': break
            a = assess(r, request)
            trials.append({'angle_delta': angle, 'speed_ratio': speed, 'inside': a['inside'],
                           'error_mm': round(a['error_m']*1000, 1), 'hard_valid': a['valid']})
        v['perturbations'] = trials or None
    state = ('cancelled' if cancelled() else 'found' if any(v['inside'] for v in verified)
             else 'approximate' if verified else 'incomplete' if pool and all(m['simulation_status'] != 'stopped' for _, m in pool)
             else 'not_found')
    return {'status': state, 'solutions': [] if state == 'cancelled' else verified,
            'evaluations': count, 'elapsed': round(monotonic()-started, 3),
            'goal': {**asdict(request.goal), 'radius': request.radius}, 'target': request.target,
            'model_signature': service.signature, 'numerical_failures': failures,
            'scope': 'direct-first-hit; full table; bounded search; no reachability proof'}
