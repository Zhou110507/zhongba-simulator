"""Analytic constant-acceleration motion up to the next state transition."""

from dataclasses import dataclass, replace
from math import copysign, inf

from .model import Ball, Physics, Vec2, Vec3

SPEED_EPS = 1e-10
SLIP_EPS = 1e-9


@dataclass(frozen=True)
class Motion:
    phase: str
    acceleration: Vec2
    angular_acceleration: Vec3
    transition_time: float
    transition: str | None


def describe(ball: Ball, physics: Physics) -> Motion:
    speed, slip, r = ball.velocity.norm(), ball.slip.norm(), ball.spec.radius
    az = (-copysign(physics.spin_deceleration, ball.omega.z)
          if abs(ball.omega.z) > SPEED_EPS else 0.0)
    spin_time = abs(ball.omega.z / az) if az else inf
    a, aw, limit, transition = Vec2(), Vec3(), inf, None
    if slip > SLIP_EPS:
        phase = "sliding"
        if physics.sliding_friction:
            a = ball.slip * (-physics.sliding_friction * physics.gravity / slip)
            aw = Vec3(2.5*a.y/r, -2.5*a.x/r)
            limit = slip / (3.5*physics.sliding_friction*physics.gravity)
            transition = "sliding_to_rolling"
    elif speed > SPEED_EPS:
        phase = "rolling"
        if physics.rolling_friction:
            a = ball.velocity * (-physics.rolling_friction*physics.gravity/speed)
            aw = Vec3(-a.y/r, a.x/r)
            limit = speed / (physics.rolling_friction*physics.gravity)
            transition = "rolling_to_rest"
    else:
        phase = "spinning" if abs(ball.omega.z) > SPEED_EPS else "stationary"
    if spin_time < limit:
        limit, transition = spin_time, "spin_to_rest"
    return Motion(phase, a, Vec3(aw.x, aw.y, az), limit, transition)


def advance(ball: Ball, motion: Motion, dt: float) -> Ball:
    a, w, aw = motion.acceleration, ball.omega, motion.angular_acceleration
    position = ball.position + ball.velocity*dt + a*(0.5*dt*dt)
    velocity = ball.velocity + a*dt
    omega = Vec3(w.x + aw.x*dt, w.y + aw.y*dt, w.z + aw.z*dt)
    # Remove floating-point residues at analytically known transitions only.
    if abs(dt-motion.transition_time) <= max(1e-12, abs(dt)*1e-12):
        if motion.transition == "sliding_to_rolling":
            omega = Vec3(-velocity.y/ball.spec.radius,
                         velocity.x/ball.spec.radius, omega.z)
        elif motion.transition == "rolling_to_rest":
            velocity, omega = Vec2(), Vec3(0, 0, omega.z)
        elif motion.transition == "spin_to_rest":
            omega = Vec3(omega.x, omega.y, 0)
    return replace(ball, position=position, velocity=velocity, omega=omega)

