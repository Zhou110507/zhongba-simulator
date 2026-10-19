"""UI-independent billiards physics. All quantities use SI units."""

from .model import Ball, BallSpec, Physics, Table, Vec2, Vec3
from .engine import simulate

__all__ = ["Ball", "BallSpec", "Physics", "Table", "Vec2", "Vec3", "simulate"]

