"""Pot first, then plan position within the same verified potting family.

Aim is corrected from the simulated object-ball exit direction. Strength,
follow/draw and a small pocket-aperture offset are searched before optional side.
This is a deterministic optimizer and benchmark workflow, not a trained model.
"""
from dataclasses import asdict
from math import asin, atan2, degrees, hypot, sin, cos, sqrt
from time import monotonic

from .cue import ShotInput, strike
from .engine import simulate
from .model import Vec2
from .pockets import outline
from .planner import assess
from .planner_routes import prefix_rejector, segment_distance


def recommendation_key(value, radius, *, measured=False):
    """Tolerance is a region, not a licence to trade simple play for millimetres."""
    shot = value['shot']; error = value['error_m']
    side = 0 if abs(shot['tip_x']) <= .02 else 1 if abs(shot['tip_x']) <= .15 else 2
    strong = int(shot['cue_speed'] > 3.2)
    if not value['inside']: return (1, error, value['cue_cushions'], side, strong)
    stability = (not value.get('stability_complete', False), -value.get('stability_passed', 0)) if measured else (False, 0)
    effort = .12*abs(shot['tip_y'])+.04*shot['cue_speed']+abs(shot['tip_x'])
    return (0, value['cue_cushions'], side, strong, *stability, effort+error/max(radius, .01)*.02)


def solve_pot(service, request, *, cancelled, progress):
    started = monotonic(); deadline = started+request.seconds
    search_end = deadline-min(4., request.seconds*.3)
    search_cap = max(1, request.evaluations-28)
    cue = next(b for b in request.balls if b.id == 'cue')
    target = next(b for b in request.balls if b.id == request.target)
    diameter = cue.spec.radius+target.spec.radius
    distance = (target.position-cue.position).norm()
    center = degrees(atan2(target.position.y-cue.position.y, target.position.x-cue.position.x))
    cone = degrees(asin(min(.999, diameter/distance)))
    pockets = []
    for pocket in outline(service.table).pockets:
        if request.pocket != 'any' and request.pocket != pocket.id: continue
        direction = (pocket.fall_center or pocket.gate)-target.position
        u = direction*(1/direction.norm()); ghost = target.position-u*diameter; ray = ghost-cue.position
        if ray.dot(u) <= .08*ray.norm(): continue
        blocked = min((min(segment_distance(b.position, cue.position, ghost),
                           segment_distance(b.position, target.position, pocket.mouth))-diameter
                       for b in request.balls if b.id not in ('cue', request.target) and b.pocket is None), default=1.)
        difficulty = 1-ray.dot(u)/ray.norm()+.08*direction.norm()
        pockets.append((blocked < 0, difficulty, pocket))
    pockets = [p for _, _, p in sorted(pockets, key=lambda v: v[:2])]
    count = 0; cache = {}; aims = {p.id: [] for p in pockets}; pool = []; failures = {}; pruned = 0
    stage = '建立直击进球基准'; baseline = None; baseline_count = 0

    def stop(): return cancelled() or monotonic() >= deadline

    def report():
        best = min((v['error_m'] for v in pool if v['valid']), default=None)
        progress({'stage': stage, 'evaluations': count, 'elapsed': round(monotonic()-started, 2),
                  'best_error_mm': None if best is None else round(best*1000, 1), 'routes': len(pockets)})

    def forward(shot, *, full=False, prune=True, search=True):
        nonlocal count, pruned
        key = tuple(round(v, 9) for v in asdict(shot).values())
        if not full and key in cache and (prune or cache[key].status == 'stopped'): return cache[key]
        if count >= (search_cap if search else request.evaluations) or cancelled() or monotonic() >= (search_end if search else deadline): return None
        launched = strike(cue, shot, service.cue)
        initial = tuple(launched if b.id == 'cue' else b for b in request.balls)
        result = simulate(initial, service.table, service.physics, max_time=60, max_events=6000,
                          record_segments=full, cancel=lambda: cancelled() or monotonic() >= (search_end if search else deadline),
                          reject_events=prefix_rejector(request, ()) if prune else None)
        count += 1
        if result.status == 'cancelled': return None
        if result.status == 'constraint_rejected': pruned += 1
        elif result.status != 'stopped': failures[result.status] = failures.get(result.status, 0)+1
        if not full: cache[key] = result
        return result

    def normalize(q):
        speed, ty, bias, tx = q
        side_limit = {'natural': 0., 'small_side': .15, 'open': .45}[request.stroke]
        tx = max(-side_limit, min(side_limit, tx))
        ty_limit = sqrt(max(0., service.cue.max_tip_offset**2-tx**2))
        return (max(.25, min(service.cue.max_speed, speed)), max(-ty_limit, min(ty_limit, ty)), max(-.85, min(.85, bias)), tx)

    def aimed(pocket, q):
        q = normalize(q); speed, ty, bias, tx = q
        aperture = max(.002, pocket.half_width-cue.spec.radius)*.8
        destination = (pocket.fall_center or pocket.gate)+pocket.tangent*(aperture*bias)
        delta = destination-target.position; desired = delta*(1/delta.norm())
        ghost = target.position-desired*diameter; ray = ghost-cue.position
        angle = degrees(atan2(ray.y, ray.x))
        if aims[pocket.id]:
            nearest = min(aims[pocket.id], key=lambda item: .3*abs(item[0][0]-speed)+abs(item[0][1]-ty)*.3+abs(item[0][2]-bias)+3*abs(item[0][3]-tx))
            # Transfer only the throw correction; keep the requested aperture point.
            angle += nearest[1]
        geometric = degrees(atan2(ray.y, ray.x)); previous = None; best = None
        for _ in range(4):
            offset = ((angle-center+180) % 360)-180
            angle = center+max(-.995*cone, min(.995*cone, offset))
            shot = ShotInput(angle % 360, speed, tx, ty)
            result = forward(shot)
            if result is None: return best
            event = next((e for e in result.events if e.kind == 'ball_ball' and 'cue' in e.actors), None)
            if event is None or request.target not in event.actors: return best
            after = next(b for b in event.after if b.id == request.target)
            if after.velocity.norm() < 1e-8:
                release = next((e for e in result.events if e.kind == 'elastic_release' and e.time >= event.time), None)
                if release: after = next(b for b in release.after if b.id == request.target)
            if after.velocity.norm() < 1e-8: return best
            outgoing = atan2(after.velocity.y, after.velocity.x)
            error = degrees(atan2(sin(outgoing-atan2(desired.y, desired.x)), cos(outgoing-atan2(desired.y, desired.x))))
            metrics = assess(result, request, ())
            value = {**metrics, 'shot': asdict(shot), 'q': q, 'pocket_id': pocket.id,
                     'aim_offset_mm': aperture*bias*1000}
            # Retain actual potted candidates even while correcting the centre aim.
            if metrics['valid']: pool.append(value)
            if best is None or (not metrics['valid'], abs(error)) < (not best['valid'], best['_aim_error']):
                best = {**value, '_aim_error': abs(error)}
            if abs(error) < .015:
                aims[pocket.id].append((q, ((angle-geometric+180) % 360)-180))
                report(); return value
            if previous is None:
                previous = (angle, error); angle += .025
            else:
                old_angle, old_error = previous
                derivative = (error-old_error)/(angle-old_angle) if abs(angle-old_angle) > 1e-10 else 0.
                previous = (angle, error)
                angle += max(-.35, min(.35, -error/derivative)) if abs(derivative) > 1e-5 else .025
        report(); return best

    for pocket in pockets:
        for speed in (.8, 1.1, 1.5):
            value = aimed(pocket, (speed, 0., 0., 0.))
            if value and value['valid']:
                if baseline is None or (value['cue_cushions'], speed) < (baseline['cue_cushions'], baseline['shot']['cue_speed']): baseline = value
                break
            if stop() or monotonic() >= search_end: break
    baseline_count = count
    stage = '保持进球 · 中高低杆走位'; report()
    settings = [(s, y, 0., 0.) for y in (0., .3, -.3, .5, -.5) for s in (.65, 1., 1.4, 1.9, 2.5, 3.2)]
    for q in settings:
        for pocket in pockets:
            if count >= search_cap or monotonic() >= search_end or cancelled(): break
            aimed(pocket, q)
        else: continue
        break

    # The central pocket line may scratch with follow. Seed both sides of the
    # actual potting aperture before local refinement, so a valid simple cut is
    # discoverable without jumping to kick shots or extreme spin.
    aperture_pockets = sorted(pockets, key=lambda p: min((v['error_m'] for v in pool if v['pocket_id'] == p.id), default=10.))[:2]
    for pocket in aperture_pockets:
        for speed, ty in ((.8, 0.), (1.4, .3), (1.4, -.3), (2., .3)):
            for bias in (-.55, .55):
                if count >= search_cap or monotonic() >= search_end or cancelled(): break
                aimed(pocket, (speed, ty, bias, 0.))

    def local(side=False):
        candidates = sorted((v for v in pool if v['valid']), key=lambda v: recommendation_key(v, request.radius))
        starts = []
        for v in candidates:
            if all(v['pocket_id'] != old['pocket_id'] or sum((a-b)**2 for a, b in zip(v['q'], old['q'])) > .06 for old in starts): starts.append(v)
            if len(starts) == 4: break
        for index, value in enumerate(starts):
            pocket = next(p for p in pockets if p.id == value['pocket_id']); q = value['q']
            steps = [.3, .12, .35, .07]; local_start = count
            allowance = max(20, (search_cap-count)//max(1, len(starts)-index))
            while max(steps[:3]) > .012 and count-local_start < allowance:
                improved = False
                for axis in range(4 if side else 3):
                    for sign in (-1, 1):
                        trial = list(q); trial[axis] += sign*steps[axis]
                        v = aimed(pocket, trial)
                        if v is None or count >= search_cap or monotonic() >= search_end or cancelled(): return
                        if v['valid'] and recommendation_key(v, request.radius) < recommendation_key(value, request.radius):
                            value = v; q = v['q']; improved = True
                if not improved: steps = [s*.5 for s in steps]

    local()
    if not any(v['inside'] for v in pool) and request.stroke != 'natural' and count < search_cap and monotonic() < search_end:
        stage = '保持进球 · 少量左右塞微调'; report()
        leaders = sorted((v for v in pool if v['valid']), key=lambda v: v['error_m'])[:4]
        for leader in leaders:
            pocket = next(p for p in pockets if p.id == leader['pocket_id'])
            for side in (-.08, .08, -.15, .15):
                q = list(leader['q']); q[3] = side; aimed(pocket, q)
        local(True)
        if request.stroke == 'open' and not any(v['inside'] for v in pool):
            stage = '保持进球 · 进阶击点'; report()
            for leader in leaders[:2]:
                pocket = next(p for p in pockets if p.id == leader['pocket_id'])
                for side in (-.3, .3, -.45, .45):
                    q = list(leader['q']); q[3] = side; aimed(pocket, q)
            local(True)

    search_elapsed = monotonic()-started; stage = '同内核完整复验'; report()
    selected = []; verified = []
    for value in sorted((v for v in pool if v['valid']), key=lambda v: recommendation_key(v, request.radius)):
        shot = value['shot']
        if any(abs(shot['cue_speed']-v['shot']['cue_speed']) < .15 and abs(shot['tip_y']-v['shot']['tip_y']) < .08 and
               abs(shot['tip_x']-v['shot']['tip_x']) < .06 and abs(((shot['angle_deg']-v['shot']['angle_deg']+180) % 360)-180) < .05 for v in selected): continue
        selected.append(value)
        if len(selected) == 3: break
    for value in selected:
        result = forward(ShotInput(**value['shot']), full=True, prune=False, search=False)
        if result is None: break
        metrics = assess(result, request, ())
        if not metrics['valid'] or result.status != 'stopped': continue
        metrics.pop('score')
        verified.append({**metrics, 'shot': value['shot'], 'verified': True, 'aim_offset_mm': value['aim_offset_mm'],
                         'launch_speed': strike(cue, ShotInput(**value['shot']), service.cue).velocity.norm(),
                         'perturbations': [], 'stability_complete': False, 'stability_passed': 0})
    verified_baseline = None
    if baseline and not stop():
        result = forward(ShotInput(**baseline['shot']), full=True, prune=False, search=False)
        if result is not None and result.status == 'stopped' and assess(result, request, ())['valid']:
            verified_baseline = {'shot': baseline['shot'], 'cue_final': baseline['cue_final'],
                                 'target_pocket': baseline['target_pocket'], 'cue_cushions': baseline['cue_cushions'],
                                 'verified': True, 'purpose': 'pot_reference_only'}
    stage = '方案扰动检查'; report()
    checks = [(-.05, 1., 0., 0.), (.05, 1., 0., 0.), (0., .98, 0., 0.), (0., 1.02, 0., 0.)]
    if request.stability == 'full': checks += [(0., 1., -.01, 0.), (0., 1., .01, 0.), (0., 1., 0., -.01), (0., 1., 0., .01)]
    for da, ds, dx, dy in checks:
        for value in verified:
            s = value['shot']; tx = s['tip_x']+dx; ty = s['tip_y']+dy; speed = s['cue_speed']*ds
            if hypot(tx, ty) > service.cue.max_tip_offset or speed > service.cue.max_speed: continue
            result = forward(ShotInput(s['angle_deg']+da, speed, tx, ty), prune=False, search=False)
            if result is None: break
            a = assess(result, request, ())
            value['perturbations'].append({'angle_delta': da, 'speed_ratio': ds, 'tip_x_delta': dx, 'tip_y_delta': dy,
                                           'inside': a['inside'], 'hard_valid': a['valid'], 'error_mm': round(a['error_m']*1000, 1)})
    for value in verified:
        trials = value['perturbations']; value['stability_expected'] = len(checks)
        value['stability_complete'] = len(trials) == len(checks)
        value['stability_passed'] = sum(t['inside'] for t in trials)
        value['stability_worst_mm'] = max((t['error_mm'] for t in trials), default=None)
        if not trials: value['perturbations'] = None
    verified.sort(key=lambda v: recommendation_key(v, request.radius, measured=True))
    state = ('cancelled' if cancelled() else 'found' if any(v['inside'] for v in verified) else 'approximate' if verified
             else 'incomplete' if failures and not pool else 'not_found')
    return {'status': state, 'solutions': [] if cancelled() else verified, 'baseline': None if cancelled() else verified_baseline,
            'evaluations': count, 'elapsed': round(monotonic()-started, 3), 'target': request.target,
            'goal': {**asdict(request.goal), 'radius': request.radius}, 'model_signature': service.signature,
            'numerical_failures': failures, 'strategy': 'pot_first', 'stroke': request.stroke,
            'performance': {'route_families': len(pockets), 'baseline_evaluations': baseline_count,
                            'potted_candidates': len(pool), 'pruned_evaluations': pruned,
                            'search_seconds': round(search_elapsed, 3)},
            'scope': 'direct cue hit; verified pot first; position second; post-contact cushions allowed; no reachability proof'}
