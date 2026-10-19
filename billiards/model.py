"""Immutable scene inputs; the default dimensions follow CBSA January 2017.

Table coordinates run along the long side (x), short side (y), and upward (z).
The nominal mass is an explicit modelling choice, not a mandated standard mass.
"""

from dataclasses import dataclass
from math import hypot, isfinite


@dataclass(frozen=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        return Vec2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def dot(self, other):
        return self.x * other.x + self.y * other.y

    def norm(self):
        return hypot(self.x, self.y)


@dataclass(frozen=True)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True)
class BallSpec:
    radius: float = 0.028575
    mass: float = 0.163

    @property
    def inertia(self):
        return 0.4 * self.mass * self.radius**2


@dataclass(frozen=True)
class Ball:
    id: str
    position: Vec2
    velocity: Vec2 = Vec2()
    omega: Vec3 = Vec3()
    spec: BallSpec = BallSpec()
    pocket: str | None = None

    @property
    def slip(self):
        r = self.spec.radius
        return Vec2(self.velocity.x - r * self.omega.y,
                    self.velocity.y + r * self.omega.x)

    @property
    def energy(self):
        w = self.omega
        return (0.5 * self.spec.mass * self.velocity.dot(self.velocity)
                + 0.5 * self.spec.inertia * (w.x*w.x + w.y*w.y + w.z*w.z))


@dataclass(frozen=True)
class PocketSpec:
    corner_mouth: float = .085
    side_mouth: float = .085
    jaw_radius: float = .008
    shelf_depth: float = .045
    jaw_extension: float = .09
    version: str = "experimental-rounded-jaws-v1"
    calibration_status: str = "experimental_pending_verified_drawing"


@dataclass(frozen=True)
class Table:
    length: float = 2.540
    width: float = 1.270
    profile: str = "cbsa-2017-rectangular-test-bed"
    pockets: PocketSpec | None = None


@dataclass(frozen=True)
class Physics:
    gravity: float = 9.81
    sliding_friction: float = 0.20
    rolling_friction: float = 0.01  # effective translational deceleration / g
    spin_deceleration: float = 10.0  # phenomenological rad/s^2
    ball_restitution: float = 0.95
    cushion_restitution: float = 0.98
    cushion_model: str = "coupled_impulse"
    cushion_friction: float = 0.14
    cushion_contact_height_ratio: float = 1.4  # h/R, research reference, not a verified CBSA dimension
    cushion_steps: int = 512
    version: str = "phase-a-energetic-baseline-v3"


def validate_scene(balls, table, physics):
    if not balls:
        raise ValueError("Scene must contain at least one ball")
    if any(not isinstance(b.id, str) or not b.id for b in balls):
        raise ValueError("Ball IDs must be non-empty strings")
    if len({b.id for b in balls}) != len(balls):
        raise ValueError("Ball IDs must be unique")
    if not all(isfinite(x) and x > 0 for x in (table.length, table.width)):
        raise ValueError("Table dimensions must be finite and positive")
    if table.pockets is not None:
        from .pockets import validate_geometry
        validate_geometry(table)
    positive = (physics.gravity,)
    nonnegative = (physics.sliding_friction, physics.rolling_friction,
                   physics.spin_deceleration)
    if not all(isfinite(x) and x > 0 for x in positive):
        raise ValueError("Gravity must be finite and positive")
    if not all(isfinite(x) and x >= 0 for x in nonnegative):
        raise ValueError("Friction and spin decay must be finite and nonnegative")
    if not all(isfinite(x) and 0 <= x <= 1 for x in
               (physics.ball_restitution, physics.cushion_restitution)):
        raise ValueError("Restitution must be between zero and one")
    if physics.cushion_model not in ("frictionless", "coupled_impulse"):
        raise ValueError("Unknown cushion model")
    if not isfinite(physics.cushion_friction) or physics.cushion_friction < 0:
        raise ValueError("Cushion friction must be finite and nonnegative")
    if physics.cushion_model == "coupled_impulse":
        h = physics.cushion_contact_height_ratio
        if not isfinite(h) or not 1 <= h < 2:
            raise ValueError("Cushion contact height must satisfy 1 <= h/R < 2")
        s = h-1
        c = (1-s*s)**.5
        if physics.cushion_friction*c > s+1e-12:
            raise ValueError("This planar cushion model cannot support lift-off")
    if (not isinstance(physics.cushion_steps,int) or isinstance(physics.cushion_steps,bool)
            or physics.cushion_steps < 32):
        raise ValueError("Cushion integration requires at least 32 impulse steps")
    for b in balls:
        values = (b.position.x, b.position.y, b.velocity.x, b.velocity.y,
                  b.omega.x, b.omega.y, b.omega.z, b.spec.radius, b.spec.mass)
        if not all(isfinite(x) for x in values):
            raise ValueError("All ball quantities must be finite")
        r = b.spec.radius
        if r <= 0 or b.spec.mass <= 0:
            raise ValueError("Mass and radius must be positive")
        if b.pocket is not None:
            if not isinstance(b.pocket,str) or not b.pocket or b.velocity != Vec2() or b.omega != Vec3():
                raise ValueError("Pocketed balls must be stationary and identify a pocket")
            continue
        if table.pockets is not None:
            from .pockets import validate_position
            validate_position(b,table)
        elif not (r <= b.position.x <= table.length-r and
                  r <= b.position.y <= table.width-r):
            raise ValueError(f"Ball {b.id} is outside the cushion faces")
    for i, a in enumerate(balls):
        for b in balls[i+1:]:
            if a.pocket is None and b.pocket is None and (a.position-b.position).norm() < a.spec.radius+b.spec.radius-1e-10:
                raise ValueError(f"Balls {a.id} and {b.id} overlap")

