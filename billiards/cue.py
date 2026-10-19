"""Horizontal cue impulse with rotational effective mass and a bounded tip disk."""

from dataclasses import dataclass, replace
from math import cos, sin, radians, isfinite, hypot

from .model import Vec2, Vec3


@dataclass(frozen=True)
class CueSpec:
    effective_mass: float = .5
    restitution: float = .75
    max_speed: float = 1.8
    max_tip_offset: float = .55
    version: str = "horizontal-impulse-v1-uncalibrated"


@dataclass(frozen=True)
class ShotInput:
    angle_deg: float
    cue_speed: float
    tip_x: float = 0.0
    tip_y: float = 0.0


def strike(ball, shot, cue=CueSpec()):
    values = (shot.angle_deg,shot.cue_speed,shot.tip_x,shot.tip_y)
    if not all(isfinite(value) for value in values):
        raise ValueError("出杆参数必须是有限数值")
    if not (isfinite(cue.effective_mass) and cue.effective_mass > 0 and
            isfinite(cue.restitution) and 0 <= cue.restitution <= 1 and
            isfinite(cue.max_speed) and cue.max_speed > 0 and
            isfinite(cue.max_tip_offset) and 0 < cue.max_tip_offset < 1):
        raise ValueError("Invalid cue model parameters")
    if not 0 < shot.cue_speed <= cue.max_speed:
        raise ValueError(f"杆头速度必须在 0 到 {cue.max_speed} m/s 之间")
    if hypot(shot.tip_x,shot.tip_y) > cue.max_tip_offset+1e-12:
        raise ValueError("击点超出允许圆盘，请减小高低杆或左右击点")
    if ball.pocket is not None:
        raise ValueError("白球已落袋，请先重新摆放白球")
    if ball.velocity.norm() > 1e-9 or hypot(ball.omega.x,ball.omega.y) > 1e-9 or abs(ball.omega.z) > 1e-9:
        raise ValueError("白球须完全静止后才能出杆")
    angle = radians(shot.angle_deg%360)
    direction = Vec2(cos(angle),sin(angle))
    offset_squared = ball.spec.radius**2*(shot.tip_x**2+shot.tip_y**2)
    inverse_mass = 1/cue.effective_mass+1/ball.spec.mass+offset_squared/ball.spec.inertia
    impulse = (1+cue.restitution)*shot.cue_speed/inverse_mass
    velocity = direction*(impulse/ball.spec.mass)
    spin_scale = impulse*ball.spec.radius/ball.spec.inertia
    omega = Vec3(-direction.y*shot.tip_y*spin_scale,
                 direction.x*shot.tip_y*spin_scale,shot.tip_x*spin_scale)
    return replace(ball,velocity=velocity,omega=omega)
