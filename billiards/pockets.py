"""Explicit experimental rails, rounded jaws, channels and capture planes.

All geometry is shared by collision detection, validation and the viewer. The
rounded capsule ends are a prototype profile, not a measured JOY pocket shape.
"""

from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from math import isfinite, sqrt

from .cushion import resolve_cushion_normal
from .model import Vec2

SPACE_EPS = 1e-9
SPEED_EPS = 1e-10


@dataclass(frozen=True)
class Surface:
    id: str
    start: Vec2
    end: Vec2
    radius: float
    kind: str = "rail"

    def closest(self, position):
        axis = self.end-self.start
        fraction = max(0.0,min(1.0,(position-self.start).dot(axis)/axis.dot(axis)))
        return self.start+axis*fraction


@dataclass(frozen=True)
class Pocket:
    id: str
    mouth: Vec2
    outward: Vec2
    tangent: Vec2
    half_width: float
    depth: float
    entry_depth: float = 0.0

    @property
    def gate(self):
        return self.mouth+self.outward*self.depth


@dataclass(frozen=True)
class Outline:
    surfaces: tuple[Surface,...]
    pockets: tuple[Pocket,...]


def validate_geometry(table):
    spec = table.pockets
    side_radius = spec.side_jaw_radius if spec.side_jaw_radius is not None else spec.jaw_radius
    values = (spec.corner_mouth,spec.side_mouth,spec.jaw_radius,side_radius,spec.shelf_depth,spec.jaw_extension)
    if not all(isfinite(value) and value > 0 for value in values):
        raise ValueError("Pocket dimensions must be finite and positive")
    if spec.shelf_depth >= spec.jaw_extension:
        raise ValueError("Capture plane must lie inside the pocket channel")
    corner = spec.corner_mouth/sqrt(2)
    if 2*corner >= table.width or corner+spec.side_mouth/2+2*spec.jaw_radius >= table.length/2:
        raise ValueError("Pocket openings overlap")
    if spec.version == 'tangent-jaws-v2':
        end = (spec.corner_mouth+2*spec.jaw_radius)/sqrt(2)-spec.jaw_radius
        if 2*end >= table.width or end+spec.side_mouth/2+side_radius >= table.length/2:
            raise ValueError('Rounded pocket transitions overlap')


@lru_cache(maxsize=32)
def outline(table):
    validate_geometry(table)
    if table.pockets.version == 'tangent-jaws-v2':
        return tangent_outline(table)
    length,width,spec = table.length,table.width,table.pockets
    radius,corner,half = spec.jaw_radius,spec.corner_mouth/sqrt(2),spec.side_mouth/2
    surfaces = [
        Surface('bottom-left',Vec2(corner,-radius),Vec2(length/2-half-radius,-radius),radius),
        Surface('bottom-right',Vec2(length/2+half+radius,-radius),Vec2(length-corner,-radius),radius),
        Surface('top-left',Vec2(corner,width+radius),Vec2(length/2-half-radius,width+radius),radius),
        Surface('top-right',Vec2(length/2+half+radius,width+radius),Vec2(length-corner,width+radius),radius),
        Surface('left',Vec2(-radius,corner),Vec2(-radius,width-corner),radius),
        Surface('right',Vec2(length+radius,corner),Vec2(length+radius,width-corner),radius),
    ]
    diagonal = 1/sqrt(2)
    descriptions = (
        ('bottom-left',Vec2(corner/2,corner/2),Vec2(-diagonal,-diagonal),spec.corner_mouth),
        ('bottom-middle',Vec2(length/2,0),Vec2(0,-1),spec.side_mouth),
        ('bottom-right',Vec2(length-corner/2,corner/2),Vec2(diagonal,-diagonal),spec.corner_mouth),
        ('top-left',Vec2(corner/2,width-corner/2),Vec2(-diagonal,diagonal),spec.corner_mouth),
        ('top-middle',Vec2(length/2,width),Vec2(0,1),spec.side_mouth),
        ('top-right',Vec2(length-corner/2,width-corner/2),Vec2(diagonal,diagonal),spec.corner_mouth),
    )
    pockets = []
    for name,mouth,outward,mouth_width in descriptions:
        tangent = Vec2(-outward.y,outward.x)
        pocket = Pocket(name,mouth,outward,tangent,mouth_width/2,spec.shelf_depth)
        pockets.append(pocket)
        for sign in (-1,1):
            start = mouth+tangent*(sign*(mouth_width/2+radius))
            end = start+outward*spec.jaw_extension
            surfaces.append(Surface(f'jaw:{name}:{sign}',start,end,radius,'jaw'))
    return Outline(tuple(surfaces),tuple(pockets))


def tangent_outline(table):
    """Exact C1 union of flat noses and rounded capsule jaws.

    A flat nose ends at the top tangent of its jaw circle. The channel
    continues along the circle's other tangent. Radius does not change the
    minimum throat opening. No guessed near-touching capsule junctions.
    """
    length,width,spec = table.length,table.width,table.pockets
    corner_radius = spec.jaw_radius
    side_radius = spec.side_jaw_radius if spec.side_jaw_radius is not None else corner_radius
    end = (spec.corner_mouth+2*corner_radius)/sqrt(2)-corner_radius
    left = length/2-spec.side_mouth/2-side_radius
    right = length/2+spec.side_mouth/2+side_radius
    surfaces = [
        Surface('bottom-left',Vec2(end,0),Vec2(left,0),0),
        Surface('bottom-right',Vec2(right,0),Vec2(length-end,0),0),
        Surface('top-left',Vec2(end,width),Vec2(left,width),0),
        Surface('top-right',Vec2(right,width),Vec2(length-end,width),0),
        Surface('left',Vec2(0,end),Vec2(0,width-end),0),
        Surface('right',Vec2(length,end),Vec2(length,width-end),0),
    ]
    diagonal,centre = 1/sqrt(2),(end-corner_radius)/2
    descriptions = (
        ('bottom-left',Vec2(centre,centre),Vec2(-diagonal,-diagonal),spec.corner_mouth,corner_radius),
        ('bottom-middle',Vec2(length/2,-side_radius),Vec2(0,-1),spec.side_mouth,side_radius),
        ('bottom-right',Vec2(length-centre,centre),Vec2(diagonal,-diagonal),spec.corner_mouth,corner_radius),
        ('top-left',Vec2(centre,width-centre),Vec2(-diagonal,diagonal),spec.corner_mouth,corner_radius),
        ('top-middle',Vec2(length/2,width+side_radius),Vec2(0,1),spec.side_mouth,side_radius),
        ('top-right',Vec2(length-centre,width-centre),Vec2(diagonal,diagonal),spec.corner_mouth,corner_radius),
    )
    pockets = []
    for name,mouth,outward,opening,radius in descriptions:
        tangent = Vec2(-outward.y,outward.x)
        pockets.append(Pocket(name,mouth,outward,tangent,opening/2,spec.shelf_depth,-radius))
        for sign in (-1,1):
            start = mouth+tangent*(sign*(opening/2+radius))
            surfaces.append(Surface(f'jaw:{name}:{sign}',start,
                                    start+outward*spec.jaw_extension,radius,'jaw'))
    return Outline(tuple(surfaces),tuple(pockets))


def validate_position(ball, table):
    geometry = outline(table)
    position = ball.position
    for surface in geometry.surfaces:
        if (position-surface.closest(position)).norm() < ball.spec.radius+surface.radius-SPACE_EPS:
            raise ValueError(f"球 {ball.id} 与库边或袋角重叠")
    if 0 <= position.x <= table.length and 0 <= position.y <= table.width:
        return
    for pocket in geometry.pockets:
        displacement = position-pocket.mouth
        across_limit = (pocket.half_width-pocket.entry_depth if pocket.entry_depth < 0
                        else pocket.half_width-ball.spec.radius)
        if (pocket.entry_depth-SPACE_EPS <= displacement.dot(pocket.outward) <= pocket.depth+SPACE_EPS
                and abs(displacement.dot(pocket.tangent)) <= across_limit+SPACE_EPS):
            return
    raise ValueError(f"球 {ball.id} 在可玩区域之外")


def touches_surface(ball, table):
    return any((ball.position-surface.closest(ball.position)).norm()
               <= ball.spec.radius+surface.radius+SPACE_EPS for surface in outline(table).surfaces)


def _position(ball, acceleration, time):
    return ball.position+ball.velocity*time+acceleration*(.5*time*time)


def boundary_candidates(ball, motion, table, horizon, roots):
    geometry = outline(table)
    acceleration = motion.acceleration
    candidates = []
    for surface in geometry.surfaces:
        axis = surface.end-surface.start
        length = axis.norm()
        direction = axis*(1/length)
        perpendicular = Vec2(-direction.y,direction.x)
        distance = ball.spec.radius+surface.radius
        relative = ball.position-surface.start
        times = []
        for sign in (-1,1):
            coefficients = [sign*relative.dot(perpendicular)-distance,
                            sign*ball.velocity.dot(perpendicular),.5*sign*acceleration.dot(perpendicular)]
            for time in roots(coefficients,horizon):
                position = _position(ball,acceleration,time)
                projection = (position-surface.start).dot(direction)
                speed = sign*(ball.velocity+acceleration*time).dot(perpendicular)
                if -SPACE_EPS <= projection <= length+SPACE_EPS and speed < -SPEED_EPS:
                    times.append(time)
                    break
        for endpoint,first in ((surface.start,True),(surface.end,False)):
            delta = ball.position-endpoint
            velocity = ball.velocity
            coefficients = [delta.dot(delta)-distance*distance,2*delta.dot(velocity),
                            velocity.dot(velocity)+delta.dot(acceleration),
                            velocity.dot(acceleration),.25*acceleration.dot(acceleration)]
            for time in roots(coefficients,horizon):
                position = _position(ball,acceleration,time)
                projection = (position-surface.start).dot(direction)
                on_cap = projection <= SPACE_EPS if first else projection >= length-SPACE_EPS
                if on_cap and (position-endpoint).dot(velocity+acceleration*time) < -SPEED_EPS*distance:
                    times.append(time)
                    break
        closest = surface.closest(ball.position)
        separation = ball.position-closest
        if (abs(separation.norm()-distance) <= SPACE_EPS
                and abs(separation.dot(ball.velocity)) <= SPEED_EPS*distance
                and ball.velocity.dot(ball.velocity)+separation.dot(acceleration) < -SPEED_EPS):
            candidates.append((0.0,'persistent_contact',surface.id))
        for time in sorted(times):
            position = _position(ball,acceleration,time)
            if any((position-other.closest(position)).norm() < ball.spec.radius+other.radius-SPACE_EPS
                   for other in geometry.surfaces if other.id != surface.id):
                continue
            normal = (surface.closest(position)-position)*(1/distance)
            duplicate = False
            for other_time,kind,other_id in candidates:
                if kind != 'ball_cushion' or abs(other_time-time) > 1e-9:
                    continue
                other = next(item for item in geometry.surfaces if item.id==other_id)
                other_normal = (other.closest(position)-position)*(1/(ball.spec.radius+other.radius))
                if (other_normal-normal).norm() < 1e-7:
                    duplicate = True
                    break
            if not duplicate:
                candidates.append((time,'ball_cushion',surface.id))
            break
    for pocket in geometry.pockets:
        gap = (ball.position-pocket.gate).dot(pocket.outward)
        velocity = ball.velocity.dot(pocket.outward)
        acc = acceleration.dot(pocket.outward)
        for time in roots([gap,velocity,.5*acc],horizon):
            position = _position(ball,acceleration,time)
            if (velocity+acc*time > SPEED_EPS and
                    abs((position-pocket.gate).dot(pocket.tangent)) <= pocket.half_width-ball.spec.radius+SPACE_EPS):
                candidates.append((time,'ball_pocket',pocket.id))
                break
    return candidates


def resolve_surface(ball, surface_id, table, physics):
    surface = next(surface for surface in outline(table).surfaces if surface.id==surface_id)
    closest = surface.closest(ball.position)
    normal = closest-ball.position
    normal = normal*(1/normal.norm())
    position = closest-normal*(ball.spec.radius+surface.radius)
    if physics.cushion_model == 'frictionless':
        velocity = ball.velocity-normal*((1+physics.cushion_restitution)*ball.velocity.dot(normal))
        return replace(ball,position=position,velocity=velocity)
    return resolve_cushion_normal(ball,normal,physics,position)


def geometry_dict(table):
    geometry = outline(table)
    return {'surfaces':[asdict(surface) for surface in geometry.surfaces],
            'pockets':[{**asdict(pocket),'gate':asdict(pocket.gate)} for pocket in geometry.pockets],
            'profile':asdict(table.pockets)}
