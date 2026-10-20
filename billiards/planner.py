"""Bounded multi-route inverse search, using the practice forward engine.

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
from .planner_routes import RAILS, prefix_rejector, rail_name, routes_for, segment_distance


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
    approach: str = 'direct'
    first_rail: str = 'any'
    second_rail: str = 'any'
    post_banks: int | None = None
    stability: str = 'basic'
    strategy: str = 'position'
    stroke: str = 'natural'


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
    radius = _number(goal.get('radius', .1), '目标区域半径')
    if not any(abs(radius-v) < 1e-12 for v in (.06, .08, .1, .12)):
        raise ValueError('目标区域半径可选 60、80、100、120 mm')
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
    approach = data.get('approach', 'direct')
    if not isinstance(approach, str) or approach not in ('direct', 'one_bank', 'two_bank', 'auto'):
        raise ValueError('未知首碰线路')
    first, second = data.get('first_rail', 'any'), data.get('second_rail', 'any')
    if not all(isinstance(v, str) and v in ('any', *RAILS) for v in (first, second)):
        raise ValueError('未知指定库边')
    post = data.get('post_banks')
    if post is not None and (isinstance(post, bool) or not isinstance(post, int) or not 0 <= post <= 4):
        raise ValueError('首碰后库数须为 0–4 或不限')
    minimum = {'direct': 0, 'one_bank': 1, 'two_bank': 2, 'auto': 0}[approach]
    if approach == 'auto': minimum = 2 if second != 'any' else 1 if first != 'any' else 0
    if cushions < minimum+(post or 0):
        raise ValueError('总碰库上限小于所要求的碰库次数')
    if approach == 'direct' and (first != 'any' or second != 'any'):
        raise ValueError('直击线路不能指定首碰前库边')
    if approach == 'one_bank' and second != 'any':
        raise ValueError('一库线路不能指定第二库')
    if approach == 'two_bank' and first == second and first != 'any':
        raise ValueError('当前两库搜索不支持连续选择同一条直库')
    stability = data.get('stability', 'basic')
    if stability not in ('basic', 'full'): raise ValueError('未知微扰设置')
    strategy = data.get('strategy', 'pot_first' if pocket and approach == 'direct' else 'position')
    stroke = data.get('stroke', 'natural')
    if strategy not in ('pot_first', 'position') or stroke not in ('natural', 'small_side', 'open'):
        raise ValueError('未知反算流程或杆法范围')
    if strategy == 'pot_first' and (pocket is None or approach != 'direct'):
        raise ValueError('普通进球走位需要白球直击，并选择目标袋或任意袋')
    return PlanRequest(balls, shot, target, point, radius, pocket, cushions, allow, seconds, evaluations,
                       approach, first, second, post, stability, strategy, stroke)


def assess(result, request, expected_route=None):
    cue = next(b for b in result.final if b.id == 'cue')
    target = next(b for b in result.final if b.id == request.target)
    contacts = [e for e in result.events if 'cue' in e.actors and e.kind in ('ball_ball', 'ball_cushion', 'ball_pocket')]
    first_index = next((i for i, e in enumerate(contacts) if e.kind in ('ball_ball', 'ball_pocket')), len(contacts))
    first = contacts[first_index] if first_index < len(contacts) else None
    pre = tuple(rail_name(e.detail) for e in contacts[:first_index] if e.kind == 'ball_cushion')
    post = tuple(rail_name(e.detail) for e in contacts[first_index:] if e.kind == 'ball_cushion')
    first_ok = bool(first and first.kind == 'ball_ball' and request.target in first.actors)
    counts = {'direct': (0,), 'one_bank': (1,), 'two_bank': (2,), 'auto': (0, 1, 2)}[request.approach]
    route_ok = (len(pre) in counts and 'jaw' not in pre and
                (expected_route is None or pre == expected_route) and
                (request.first_rail == 'any' or bool(pre) and pre[0] == request.first_rail) and
                (request.second_rail == 'any' or len(pre) == 2 and pre[1] == request.second_rail))
    banks = sum(e.kind == 'ball_cushion' for e in contacts)
    ball_contacts = [e for e in contacts if e.kind == 'ball_ball']
    other = any(request.target not in e.actors for e in ball_contacts)
    pot_ok = request.pocket is None or (target.pocket is not None if request.pocket == 'any' else target.pocket == request.pocket)
    reasons = []
    if result.status not in ('stopped', 'constraint_rejected'): reasons.append('未完整停球：' + result.status)
    if not first_ok: reasons.append('首次触球不是指定目标球')
    if not route_ok: reasons.append('首碰前碰库线路不符')
    if cue.pocket is not None: reasons.append('白球落袋')
    if banks > request.max_cushions: reasons.append('白球碰库超限')
    if request.post_banks is not None and len(post) != request.post_banks: reasons.append('首碰后碰库次数不符')
    if other and not request.allow_other: reasons.append('白球碰到其他目标球')
    if not pot_ok: reasons.append('目标球未按要求进袋')
    if request.strategy == 'pot_first':
        target_banks = [e for e in result.events if e.kind == 'ball_cushion' and request.target in e.actors]
        if any(not e.detail.startswith('jaw:'+str(target.pocket)+':') for e in target_banks):
            reasons.append('目标球未直接进袋')
        target_hits = [e for e in result.events if e.kind == 'ball_ball' and request.target in e.actors]
        if len(target_hits) != 1 or len(ball_contacts) > 1 and not request.allow_other:
            reasons.append('普通进球线路出现二次碰球')
    if result.status == 'constraint_rejected' and not reasons: reasons.append('路线约束已拒绝')
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
    # A chord-distance surrogate guides missed bank seeds only. Final acceptance
    # still depends on exact collision events, never on this geometric score.
    miss = 0.
    if not first_ok or not route_ok:
        target_start = next(b for b in result.initial if b.id == request.target).position
        previous = next(b for b in result.initial if b.id == 'cue').position
        paths = []; seen_banks = 0; wanted = len(expected_route or ())
        for event in result.events:
            current = next(b for b in event.before if b.id == 'cue').position
            if seen_banks == wanted: paths.append(segment_distance(target_start, previous, current))
            previous = next(b for b in event.after if b.id == 'cue').position
            if 'cue' in event.actors:
                if event.kind in ('ball_ball', 'ball_pocket'): break
                if event.kind == 'ball_cushion': seen_banks += 1
            if seen_banks > wanted: break
        miss = max(0., min(paths, default=2.)-2*cue.spec.radius)
    return {'valid': not reasons, 'reasons': reasons, 'simulation_status': result.status, 'error_m': error,
            'cue_final': asdict(cue.position), 'target_pocket': target.pocket,
            'approach_rails': pre, 'departure_rails': post,
            'cue_cushions': banks, 'cue_ball_contacts': len(ball_contacts),
            'goal_margin_m': request.radius+cue.spec.radius-error,
            'inside': not reasons and error <= request.radius+cue.spec.radius+1e-9,
            'score': (error if not reasons else .2*error) + 5*len(reasons) + 3*pot_distance + 15*miss}


def _halton(index, base):
    value = 0.; weight = 1.
    while index:
        weight /= base
        value += weight*(index % base)
        index //= base
    return value


def solve(service, request, *, cancelled=lambda: False, progress=lambda value: None):
    if request.strategy == 'pot_first':
        from .planner_pot import solve_pot
        return solve_pot(service, request, cancelled=cancelled, progress=progress)
    started = monotonic(); deadline = started + request.seconds
    full_stability = request.stability == 'full'
    reserve = 27 if full_stability else 7
    search_end = deadline-min(8. if full_stability else 3., request.seconds*(.35 if full_stability else .25))
    cue = next(b for b in request.balls if b.id == 'cue')
    target = next(b for b in request.balls if b.id == request.target)
    diameter = cue.spec.radius+target.spec.radius
    routes = routes_for(service, request)
    cache = {}; pool = []; count = 0; failures = {}; pruned = 0; stage = '采样搜索'
    search_counts = {}; search_started = monotonic()

    def stopped(): return cancelled() or monotonic() >= deadline

    def normalize(q):
        ri, h, speed, tx, ty = q
        norm = hypot(tx, ty)
        if norm > service.cue.max_tip_offset:
            tx *= service.cue.max_tip_offset/norm; ty *= service.cue.max_tip_offset/norm
        return (ri, max(-.97, min(.97, h)), max(.25, min(service.cue.max_speed, speed)), tx, ty)

    def shot_of(q):
        ri, h, speed, tx, ty = normalize(q); route = routes[ri]
        angle = route.angle + (h*6*len(route.rails) if route.rails else degrees(asin(h*diameter/route.length)))
        return ShotInput(angle % 360, speed, tx, ty)

    def forward(shot, *, full=False, stop=stopped, expected=None):
        launched = strike(cue, shot, service.cue)
        initial = tuple(launched if b.id == 'cue' else b for b in request.balls)
        return simulate(initial, service.table, service.physics, max_time=60, max_events=6000,
                        cancel=stop, record_segments=full,
                        reject_events=prefix_rejector(request, expected) if expected is not None else None)

    def report():
        best = min((m['error_m'] for _, m in pool if m['valid']), default=None)
        progress({'stage': stage, 'evaluations': count, 'elapsed': round(monotonic()-started, 2),
                  'routes': len(routes), 'best_error_mm': None if best is None else round(best*1000, 1)})

    def evaluate(q):
        nonlocal count, pruned
        q = normalize(q); key = tuple(round(v, 9) for v in q)
        if key in cache: return cache[key]
        if cancelled() or monotonic() >= search_end or count >= max(1, request.evaluations-reserve): return None
        result = forward(shot_of(q), stop=lambda: cancelled() or monotonic() >= search_end, expected=routes[q[0]].rails)
        count += 1
        label = '/'.join(routes[q[0]].rails) or 'direct'
        search_counts[label] = search_counts.get(label, 0)+1
        if result.status == 'cancelled': return None
        m = assess(result, request, routes[q[0]].rails)
        if result.status == 'constraint_rejected': pruned += 1
        elif result.status != 'stopped': failures[result.status] = failures.get(result.status, 0)+1
        cache[key] = m; pool.append((q, m)); report()
        return m

    def rank(item): return (not item[1]['valid'], item[1]['score'])

    seed_lists = []
    for ri, route in enumerate(routes):
        offset = ((request.shot.angle_deg-route.angle+180) % 360)-180
        h = offset/(6*len(route.rails)) if route.rails else sin(radians(offset))*route.length/diameter
        seeds = [(ri, h, request.shot.cue_speed, request.shot.tip_x, request.shot.tip_y)]
        impacts = [0., -.35, .35, -.7, .7] if not route.rails else [0., -.06, .06, -.14, .14, -.3, .3, -.6, .6]
        if request.pocket is not None and not route.rails:
            for pocket in outline(service.table).pockets:
                if request.pocket != 'any' and pocket.id != request.pocket: continue
                direction = (pocket.fall_center or pocket.gate)-target.position
                direction = direction*(1/direction.norm())
                ghost = target.position-direction*diameter; ray = ghost-cue.position
                h = sin(atan2(ray.y, ray.x)-radians(route.angle))*route.length/diameter
                if direction.dot(ray) > 0 and abs(h) < .97: impacts[:0] = [h, h-.02, h+.02]
        settings = ((1., 0.), (1.8, .45), (2.3, -.5), (2.6, -.5), (3.4, -.5), (1.4, -.25), (2.2, 0.)) if not route.rails else ((1.4, .35), (2.2, .35), (3., -.35))
        for h in impacts:
            for speed, ty in settings: seeds.append((ri, h, speed, 0., ty))
        for i in range(1, 45 if not route.rails else 17):
            seeds.append((ri, 1.9*_halton(i, 2)-.95, .5+3.8*_halton(i, 3),
                          .7*(_halton(i, 5)-.5), 1.05*(_halton(i, 7)-.5)))
        seed_lists.append(seeds)
    # Round robin prevents one route family consuming the entire coarse budget.
    for i in range(max(map(len, seed_lists), default=0)):
        exhausted = False
        for seeds in seed_lists:
            if i < len(seeds) and evaluate(seeds[i]) is None: exhausted = True; break
        if exhausted: break
    stage = '细化走位'; starts = []
    for q, m in sorted(pool, key=rank):
        if all(q[0] != old[0] or sum((a-b)**2 for a, b in zip(q[1:], old[1:])) > .08 for old in starts): starts.append(q)
        if len(starts) == (4 if len(routes) == 1 else 8): break
    for start_index, q in enumerate(starts):
        m = evaluate(q)
        if m is None: break
        steps = [.12, .4, .12, .12]; local_count = count
        # Share refinement across families; cache hits do not consume the budget.
        local_budget = max(36, (request.evaluations-reserve-count)//max(1, len(starts)-start_index)) if len(routes) > 1 else request.evaluations
        while max(steps) > .003 and count-local_count < local_budget:
            improved = False
            for axis in range(1, 5):
                for sign in (-1, 1):
                    trial = list(q); trial[axis] += sign*steps[axis-1]
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
    search_elapsed = monotonic()-search_started
    stage = '同内核复验'; report(); verified = []; selected = []
    ordered = sorted((item for item in pool if item[1]['valid']), key=rank)
    # Prefer in-region solutions, then distinct actual rail sequences, then
    # different stroke parameters. A route label alone never proves diversity.
    for inside in (True, False):
        group = [(q, m) for q, m in ordered if m['inside'] == inside]
        for unique_routes in (True, False):
            for q, m in group:
                if len(selected) >= 3: break
                shot = shot_of(q); signature = (m['approach_rails'], m['departure_rails'])
                if unique_routes and any((v[1]['approach_rails'], v[1]['departure_rails']) == signature for v in selected): continue
                if any(abs(shot.cue_speed-shot_of(v[0]).cue_speed) < .2 and
                       hypot(shot.tip_x-shot_of(v[0]).tip_x, shot.tip_y-shot_of(v[0]).tip_y) < .08 and
                       abs(((shot.angle_deg-shot_of(v[0]).angle_deg+180) % 360)-180) < .15 for v in selected): continue
                selected.append((q, m))
    verification_start = monotonic()
    for q, m in selected:
        if stopped() or count >= request.evaluations: break
        shot = shot_of(q); result = forward(shot, full=True); count += 1
        metrics = assess(result, request, routes[q[0]].rails)
        if not metrics['valid']: continue
        metrics.pop('score')
        verified.append({'shot': asdict(shot), **metrics, 'verified': True,
                         'launch_speed': strike(cue, shot, service.cue).velocity.norm(),
                         'perturbations': None, 'stability_complete': False})
    verification_elapsed = monotonic()-verification_start
    stage = '微扰检查'; report(); stability_start = monotonic()
    checks = [(-.05, 1., 0., 0.), (.05, 1., 0., 0.), (0., .98, 0., 0.), (0., 1.02, 0., 0.)]
    if full_stability: checks += [(0., 1., -.01, 0.), (0., 1., .01, 0.), (0., 1., 0., -.01), (0., 1., 0., .01)]
    tested = verified if full_stability else verified[:1]
    # Round robin gives every candidate evidence before extending any one trial.
    for angle, speed, tx, ty in checks:
        for v in tested:
            if stopped() or count >= request.evaluations: break
            source = v['shot']; x = source['tip_x']+tx; y = source['tip_y']+ty
            if source['cue_speed']*speed > service.cue.max_speed or hypot(x, y) > service.cue.max_tip_offset: continue
            shot = ShotInput(source['angle_deg']+angle, source['cue_speed']*speed, x, y)
            r = forward(shot); count += 1
            if r.status == 'cancelled': break
            a = assess(r, request, tuple(v['approach_rails']))
            if v['perturbations'] is None: v['perturbations'] = []
            v['perturbations'].append({'angle_delta': angle, 'speed_ratio': speed, 'tip_x_delta': tx, 'tip_y_delta': ty,
                                       'inside': a['inside'], 'error_mm': round(a['error_m']*1000, 1), 'hard_valid': a['valid']})
    for v in tested:
        trials = v['perturbations'] or []
        v['stability_expected'] = len(checks)
        v['stability_complete'] = len(trials) == len(checks)
        v['stability_passed'] = sum(t['inside'] for t in trials)
        v['stability_worst_mm'] = max((t['error_mm'] for t in trials), default=None)
    if full_stability:
        verified.sort(key=lambda v: (not v['inside'], not v['stability_complete'],
                      -v.get('stability_passed', 0) if v['stability_complete'] else 0,
                      v['error_m']+.02*hypot(v['shot']['tip_x'], v['shot']['tip_y'])+.001*v['shot']['cue_speed']+.005*v['cue_cushions']))
    state = ('cancelled' if cancelled() else 'found' if any(v['inside'] for v in verified)
             else 'approximate' if verified else 'incomplete' if pool and all(m['simulation_status'] not in ('stopped', 'constraint_rejected') for _, m in pool)
             else 'not_found')
    return {'status': state, 'solutions': [] if state == 'cancelled' else verified,
            'evaluations': count, 'elapsed': round(monotonic()-started, 3),
            'goal': {**asdict(request.goal), 'radius': request.radius}, 'target': request.target,
            'model_signature': service.signature, 'numerical_failures': failures,
            'performance': {'route_families': len(routes), 'search_evaluations': search_counts,
                            'pruned_evaluations': pruned,
                            'search_seconds': round(search_elapsed, 3), 'verification_seconds': round(verification_elapsed, 3),
                            'stability_seconds': round(monotonic()-stability_start, 3)},
            'scope': '0-2 pre-contact cushions; full table; bounded search; no reachability proof'}
