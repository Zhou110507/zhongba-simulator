"""Continuous collision detection for isolated sphere contacts and flat rails.

Sphere contacts are frictionless; cushions optionally couple spin and friction.
Coupled multi-contact
and zero-speed persistent contacts return explicit unsupported statuses. They
are not silently resolved in arbitrary object order.
"""

from bisect import bisect_right
from dataclasses import asdict, dataclass, replace
from math import isfinite

import numpy as np

from .model import Ball, Physics, Table, Vec2, validate_scene
from .motion import Motion, SPEED_EPS, advance, describe
from .cushion import CushionFailure, resolve_cushion

SPACE_EPS = 1e-9
TIME_EPS = 1e-10
GROUP_EPS = 1e-9


@dataclass(frozen=True)
class Event:
    time: float
    kind: str
    actors: tuple[str, ...]
    detail: str
    before: tuple[Ball, ...]
    after: tuple[Ball, ...]


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    balls: tuple[Ball, ...]
    motions: tuple[Motion, ...]


@dataclass(frozen=True)
class Result:
    initial: tuple[Ball, ...]
    final: tuple[Ball, ...]
    table: Table
    physics: Physics
    duration: float
    status: str
    events: tuple[Event, ...]
    segments: tuple[Segment, ...]

    def state_at(self, time: float) -> tuple[Ball, ...]:
        """Sample the same analytic model; event timestamps are right-continuous."""
        tolerance = 1e-12*max(1.0, self.duration)
        if not isfinite(time) or time < -tolerance or time > self.duration+tolerance:
            raise ValueError("Time must be within the recorded simulation")
        time = max(0.0, min(time, self.duration))
        if time == self.duration or not self.segments:
            return self.final
        index = bisect_right([s.start for s in self.segments], time)-1
        segment = self.segments[index]
        return tuple(advance(b, m, time-segment.start)
                     for b, m in zip(segment.balls, segment.motions))

    def to_dict(self, sample_hz: float = 60) -> dict:
        if not isfinite(sample_hz) or sample_hz <= 0:
            raise ValueError("Sampling frequency must be finite and positive")
        times = list(np.arange(0, self.duration, 1/sample_hz)) + [self.duration]
        return {"schema_version": 1, "engine_version": self.physics.version,
                "status": self.status, "duration": self.duration,
                "table": asdict(self.table), "physics": asdict(self.physics),
                "initial": [asdict(b) for b in self.initial],
                "final": [asdict(b) for b in self.final],
                "segments": [{"start": s.start, "end": s.end,
                              "balls": [asdict(b) for b in s.balls],
                              "motion": [{"phase": m.phase,
                                          "acceleration": asdict(m.acceleration),
                                          "angular_acceleration": asdict(m.angular_acceleration)}
                                         for m in s.motions]} for s in self.segments],
                "events": [asdict(e) for e in self.events],
                "samples": [{"time": float(t), "balls": [asdict(b) for b in self.state_at(t)]}
                            for t in times]}


@dataclass(frozen=True)
class Candidate:
    time: float
    kind: str
    indices: tuple[int, ...]
    detail: str = ""


def real_roots(coefficients, horizon):
    """Roots on a finite interval, rescaled to dimensionless time [0, 1]."""
    if horizon <= 0:
        return []
    coeff = np.asarray(coefficients, dtype=float)
    coeff = np.trim_zeros(coeff, "b")
    if len(coeff) <= 1:
        return []
    scale = min(horizon, 1e4)  # avoid gratuitous high-power overflow
    scaled = coeff * scale**np.arange(len(coeff))
    scaled = scaled / max(abs(scaled))
    roots = np.polynomial.polynomial.polyroots(scaled)
    values = []
    for z in roots:
        if abs(z.imag) <= 1e-9*max(1, abs(z.real)):
            t = float(z.real)*scale
            if -TIME_EPS <= t <= horizon+TIME_EPS:
                values.append(max(0.0, min(horizon, t)))
    return sorted(values)


def contact_candidates(balls, motions, table, horizon):
    candidates = []
    for i, b in enumerate(balls):
        a, r = motions[i].acceleration, b.spec.radius
        walls = (
            ("left", b.position.x-r, b.velocity.x, a.x),
            ("right", table.length-r-b.position.x, -b.velocity.x, -a.x),
            ("bottom", b.position.y-r, b.velocity.y, a.y),
            ("top", table.width-r-b.position.y, -b.velocity.y, -a.y),
        )
        for name, gap, vel, acc in walls:
            if gap <= SPACE_EPS and abs(vel) <= SPEED_EPS and acc < -SPEED_EPS:
                candidates.append(Candidate(0, "persistent_contact", (i,), name))
                continue
            for t in real_roots([gap, vel, 0.5*acc], horizon):
                if vel + acc*t < -SPEED_EPS:
                    candidates.append(Candidate(t, "ball_cushion", (i,), name))
                    break
        for j in range(i+1, len(balls)):
            other = balls[j]
            dp = other.position-b.position
            dv = other.velocity-b.velocity
            da = motions[j].acceleration-a
            diameter = r+other.spec.radius
            if (dp.norm()-diameter <= SPACE_EPS and
                    abs(dp.dot(dv)) <= SPEED_EPS*diameter and
                    dv.dot(dv)+dp.dot(da) < -SPEED_EPS):
                candidates.append(Candidate(0, "persistent_contact", (i,j)))
                continue
            coeff = [dp.dot(dp)-diameter**2, 2*dp.dot(dv),
                     dv.dot(dv)+dp.dot(da), dv.dot(da), 0.25*da.dot(da)]
            for t in real_roots(coeff, horizon):
                separation = dp + dv*t + da*(0.5*t*t)
                if separation.dot(dv+da*t) < -SPEED_EPS*diameter:
                    candidates.append(Candidate(t, "ball_ball", (i,j)))
                    break
    return candidates


def resolve_pair(a, b, restitution):
    n = b.position-a.position
    n = n*(1/n.norm())
    speed = (b.velocity-a.velocity).dot(n)
    impulse = -(1+restitution)*speed/(1/a.spec.mass+1/b.spec.mass)
    return (replace(a, velocity=a.velocity-n*(impulse/a.spec.mass)),
            replace(b, velocity=b.velocity+n*(impulse/b.spec.mass)))


def resolve_wall(ball, name, table, restitution):
    p, v, r = ball.position, ball.velocity, ball.spec.radius
    if name == "left":
        return replace(ball, position=Vec2(r, p.y), velocity=Vec2(-restitution*v.x, v.y))
    if name == "right":
        return replace(ball, position=Vec2(table.length-r, p.y), velocity=Vec2(-restitution*v.x, v.y))
    if name == "bottom":
        return replace(ball, position=Vec2(p.x, r), velocity=Vec2(v.x, -restitution*v.y))
    return replace(ball, position=Vec2(p.x, table.width-r), velocity=Vec2(v.x, -restitution*v.y))


def coupled_contacts(contacts, balls, table, physics):
    """Include touching resting neighbours, not only currently approaching pairs."""
    for c in contacts:
        if c.kind != "ball_ball":
            continue
        for i in c.indices:
            b = balls[i]
            for j, other in enumerate(balls):
                if j not in c.indices and ((other.position-b.position).norm()
                                          <= other.spec.radius+b.spec.radius+SPACE_EPS):
                    return True
            r, p = b.spec.radius, b.position
            if min(p.x-r, p.y-r, table.length-r-p.x, table.width-r-p.y) <= SPACE_EPS:
                return True
    # Orthogonal frictionless rails at a rectangular corner commute; all other
    # shared-body contacts require a coupled solver and are explicitly rejected.
    for i, a in enumerate(contacts):
        for b in contacts[i+1:]:
            if set(a.indices) & set(b.indices):
                if a.kind != "ball_cushion" or b.kind != "ball_cushion":
                    return True
                if physics.cushion_model != "frictionless":
                    return True
    return False


def simulate(balls, table=Table(), physics=Physics(), *, max_time=60.0, max_events=10000):
    balls = tuple(balls)
    validate_scene(balls, table, physics)
    if not isfinite(max_time) or max_time <= 0:
        raise ValueError("max_time must be finite and positive")
    if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events <= 0:
        raise ValueError("max_events must be a positive integer")
    initial = balls
    events, segments = [], []
    time, iterations, status = 0.0, 0, "max_time"
    while True:
        motions = tuple(describe(b, physics) for b in balls)
        if all(m.phase == "stationary" for m in motions):
            status = "stopped"
            break
        if time >= max_time:
            break
        if iterations >= max_events:
            status = "max_events"
            break
        horizon = min(max_time-time, *(m.transition_time for m in motions))
        candidates = contact_candidates(balls, motions, table, horizon)
        for i, m in enumerate(motions):
            if m.transition_time <= horizon:
                candidates.append(Candidate(m.transition_time, "transition", (i,), m.transition))
        dt = min([horizon] + [c.time for c in candidates])
        group = [c for c in candidates if abs(c.time-dt) <= GROUP_EPS]
        if dt > 0:
            segments.append(Segment(time, time+dt, balls, motions))
            balls = tuple(advance(b, m, dt) for b, m in zip(balls, motions))
        time += dt
        contacts = [c for c in group if c.kind != "transition"]
        if any(c.kind == "persistent_contact" for c in contacts):
            status = "unsupported_persistent_contact"
            break
        if coupled_contacts(contacts, balls, table, physics):
            status = "unsupported_coupled_contact"
            break
        for c in group:
            if c.kind == "transition":
                events.append(Event(time, c.detail, (balls[c.indices[0]].id,), "",
                                    balls, balls))
        for c in contacts:
            before = balls
            changed = list(balls)
            if c.kind == "ball_ball":
                i, j = c.indices
                changed[i], changed[j] = resolve_pair(balls[i], balls[j], physics.ball_restitution)
            else:
                i = c.indices[0]
                if physics.cushion_model == "frictionless":
                    changed[i] = resolve_wall(balls[i], c.detail, table, physics.cushion_restitution)
                else:
                    try:
                        changed[i] = resolve_cushion(balls[i],c.detail,table,physics)
                    except CushionFailure:
                        status = "cushion_model_failure"
                        return Result(initial,balls,table,physics,time,status,
                                      tuple(events),tuple(segments))
            balls = tuple(changed)
            events.append(Event(time, c.kind, tuple(balls[i].id for i in c.indices),
                                c.detail, before, balls))
        iterations += 1
        if dt == 0 and not group:
            status = "numerical_failure"
            break
    return Result(initial, balls, table, physics, time, status, tuple(events), tuple(segments))
