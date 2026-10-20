"""Unfolded ball-centre rail geometry supplies seeds, never physical verdicts."""
from dataclasses import dataclass
from itertools import product
from math import atan2, degrees

from .model import Vec2

RAILS = ('top', 'bottom', 'left', 'right')


def rail_name(detail):
    if detail.startswith('jaw:'): return 'jaw'
    for name in RAILS:
        if detail == name or detail.startswith(name+'-'): return name
    return 'jaw'


def mirror(point, rail, bounds):
    left, right, bottom, top = bounds
    if rail == 'left': return Vec2(2*left-point.x, point.y)
    if rail == 'right': return Vec2(2*right-point.x, point.y)
    if rail == 'bottom': return Vec2(point.x, 2*bottom-point.y)
    return Vec2(point.x, 2*top-point.y)


def image(point, rails, bounds):
    for rail in reversed(rails): point = mirror(point, rail, bounds)
    return point


def segment_distance(point, a, b):
    d = b-a
    t = max(0., min(1., (point-a).dot(d)/d.dot(d))) if d.dot(d) else 0.
    return (point-(a+d*t)).norm()


def prefix_rejector(request, expected):
    """Only prune event prefixes that cannot satisfy immutable hard constraints."""
    seen = 0; pre = []; hit = False; banks = 0; post = 0; target_hits = 0
    def rejected(events):
        nonlocal seen, hit, banks, post, target_hits
        while seen < len(events):
            event = events[seen]; seen += 1
            if request.strategy == 'pot_first' and request.target in event.actors:
                if event.kind == 'ball_cushion' and not event.detail.startswith('jaw:'): return True
                if event.kind == 'ball_ball':
                    target_hits += 1
                    if target_hits > 1: return True
            if 'cue' not in event.actors: continue
            if event.kind == 'ball_pocket': return True
            if event.kind == 'ball_cushion':
                banks += 1
                if banks > request.max_cushions: return True
                if not hit:
                    pre.append(rail_name(event.detail))
                    if tuple(pre) != expected[:len(pre)]: return True
                else:
                    post += 1
                    if request.post_banks is not None and post > request.post_banks: return True
            if event.kind == 'ball_ball':
                if not hit:
                    if request.target not in event.actors or tuple(pre) != expected: return True
                    hit = True
                elif request.target not in event.actors and not request.allow_other: return True
        return False
    return rejected


@dataclass(frozen=True)
class Route:
    rails: tuple[str, ...]
    image: Vec2
    length: float
    angle: float
    points: tuple[Vec2, ...]
    clearance: float


def routes_for(service, request):
    cue = next(b for b in request.balls if b.id == 'cue')
    target = next(b for b in request.balls if b.id == request.target)
    r = cue.spec.radius
    bounds = (r, service.table.length-r, r, service.table.width-r)
    counts = {'direct': (0,), 'one_bank': (1,), 'two_bank': (2,), 'auto': (0, 1, 2)}[request.approach]
    found = []
    for count in counts:
        if count+(request.post_banks or 0) > request.max_cushions: continue
        for rails in product(RAILS, repeat=count):
            if count == 0 and (request.first_rail != 'any' or request.second_rail != 'any'): continue
            if count == 1 and request.second_rail != 'any': continue
            if count == 2 and rails[0] == rails[1]: continue
            if rails and request.first_rail != 'any' and rails[0] != request.first_rail: continue
            if count == 2 and request.second_rail != 'any' and rails[1] != request.second_rail: continue
            virtual = image(target.position, rails, bounds)
            delta = virtual-cue.position
            position = cue.position; direction = delta*(1/delta.norm()); points = [position]
            possible = True
            for expected in rails:
                times = []
                for rail, axis, coordinate in (('left', 'x', bounds[0]), ('right', 'x', bounds[1]),
                                                ('bottom', 'y', bounds[2]), ('top', 'y', bounds[3])):
                    velocity = getattr(direction, axis)
                    t = (coordinate-getattr(position, axis))/velocity if velocity else -1
                    if t > 1e-8: times.append((t, rail))
                if not times: possible = False; break
                t, actual = min(times)
                if actual != expected: possible = False; break
                position = position+direction*t; points.append(position)
                direction = Vec2(-direction.x, direction.y) if actual in ('left', 'right') else Vec2(direction.x, -direction.y)
            if not possible: continue
            points.append(target.position)
            clearance = min((segment_distance(b.position, a, z)-b.spec.radius-r
                             for a, z in zip(points, points[1:]) for b in request.balls
                             if b.id not in ('cue', request.target) and b.pocket is None), default=1.)
            found.append(Route(rails, virtual, delta.norm(), degrees(atan2(delta.y, delta.x)), tuple(points), clearance))
    return sorted(found, key=lambda route: (route.clearance < 0, len(route.rails), -route.clearance, route.length))
