"""Continuous collision detection for isolated sphere contacts and flat rails.

Sphere contacts optionally include projected throw and vertical-axis spin transfer.
The optional cluster solver handles ball networks and bounded ball support.
Other persistent contacts return explicit unsupported statuses.
"""

from bisect import bisect_right
from dataclasses import asdict, dataclass, replace
from math import isfinite, sqrt, copysign

import numpy as np

from .model import Ball, Physics, Table, Vec2, Vec3, validate_scene
from .motion import Motion, SPEED_EPS, advance, describe
from .cushion import CushionFailure, resolve_cushion
from .ball_contact import resolve_ball_contact

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
        if not self.segments and time < self.duration:
            raise ValueError('Trajectory segments were not recorded; only final state and events are available')
        if time == self.duration or not self.segments:
            return self.final
        index = bisect_right([s.start for s in self.segments], time)-1
        segment = self.segments[index]
        return tuple(advance(b, m, time-segment.start)
                     for b, m in zip(segment.balls, segment.motions))

    def to_dict(self, sample_hz: float | None = 60, *, compact=False) -> dict:
        if sample_hz is not None and (not isfinite(sample_hz) or sample_hz <= 0):
            raise ValueError("Sampling frequency must be finite and positive")
        times = list(np.arange(0, self.duration, 1/sample_hz)) + [self.duration] if sample_hz is not None else []
        if compact:
            # Playback needs one contact snapshot for the ghost, not two full
            # copies of all 16 balls at every support impulse.
            def ball_data(b):
                return {'id':b.id,'position':{'x':b.position.x,'y':b.position.y},
                        'velocity':{'x':b.velocity.x,'y':b.velocity.y},
                        'omega':{'x':b.omega.x,'y':b.omega.y,'z':b.omega.z},
                        'spec':{'radius':b.spec.radius,'mass':b.spec.mass},'pocket':b.pocket}
            events=[];first=False
            for e in self.events:
                entry={'time':e.time,'kind':e.kind,'actors':e.actors,'detail':e.detail}
                if not first and 'cue' in e.actors and e.kind in ('ball_ball','ball_cushion','ball_pocket'):
                    entry['before']=[ball_data(b) for b in e.before if b.id in e.actors];first=True
                events.append(entry)
            return {'schema_version':1,'detail':'playback-v2','engine_version':self.physics.version,
                    'status':self.status,'duration':self.duration,'table':asdict(self.table),'physics':asdict(self.physics),
                    'initial':[ball_data(b) for b in self.initial],'final':[ball_data(b) for b in self.final],
                    # Lossless numeric rows avoid repeating field names, IDs and
                    # immutable specs at every contact microsecond contact sample.
                    'segments':[s.packed() if hasattr(s,'packed') else [s.start,s.end,
                                 [[b.position.x,b.position.y,b.velocity.x,b.velocity.y,b.omega.x,b.omega.y,b.omega.z,b.pocket] for b in s.balls],
                                 [[m.phase,m.acceleration.x,m.acceleration.y,m.angular_acceleration.x,m.angular_acceleration.y,m.angular_acceleration.z] for m in s.motions]] for s in self.segments],
                    'events':events,'samples':[]}
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
    coefficients=list(coefficients)
    while coefficients and coefficients[-1]==0:coefficients.pop()
    if len(coefficients)<=1:return []
    if len(coefficients)<=3:
        c,b=coefficients[:2]
        if len(coefficients)==2:roots=[-c/b]
        else:
            a=coefficients[2];discriminant=b*b-4*a*c
            if discriminant<0:return []
            q=-.5*(b+copysign(sqrt(discriminant),b))
            roots=[q/a,c/q] if q else [-b/(2*a)]
        return sorted(max(0.0,min(horizon,t)) for t in roots if -TIME_EPS<=t<=horizon+TIME_EPS)
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
        if b.pocket is not None:
            continue
        a, r = motions[i].acceleration, b.spec.radius
        if table.pockets is not None:
            from .pockets import boundary_candidates
            candidates.extend(Candidate(time,kind,(i,),detail) for time,kind,detail in
                              boundary_candidates(b,motions[i],table,horizon,real_roots))
        walls = () if table.pockets is not None else (
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
            if other.pocket is not None:
                continue
            diameter = r+other.spec.radius
            dx=other.position.x-b.position.x;dy=other.position.y-b.position.y
            vx=other.velocity.x-b.velocity.x;vy=other.velocity.y-b.velocity.y
            ax=motions[j].acceleration.x-a.x;ay=motions[j].acceleration.y-a.y
            reach=(vx*vx+vy*vy)**.5*horizon+.5*(ax*ax+ay*ay)**.5*horizon*horizon
            if dx*dx+dy*dy>(diameter+reach+SPACE_EPS)**2:continue
            dp=Vec2(dx,dy);dv=Vec2(vx,vy);da=Vec2(ax,ay)
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
                if other.pocket is None and j not in c.indices and ((other.position-b.position).norm()
                                          <= other.spec.radius+b.spec.radius+SPACE_EPS):
                    return True
            r, p = b.spec.radius, b.position
            if table.pockets is not None:
                from .pockets import touches_surface
                if touches_surface(b,table):
                    return True
            elif min(p.x-r, p.y-r, table.length-r-p.x, table.width-r-p.y) <= SPACE_EPS:
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


def island_touches_cushion(contacts,balls,table):
    """Do not apply a ball-only impulse solve to a connected frozen rail."""
    indices={i for c in contacts for i in c.indices}
    changed=True
    while changed:
        changed=False
        for i,b in enumerate(balls):
            if i in indices or b.pocket is not None:continue
            if any((b.position.x-balls[j].position.x)**2+(b.position.y-balls[j].position.y)**2<=(b.spec.radius+balls[j].spec.radius+SPACE_EPS)**2 for j in indices):
                indices.add(i);changed=True
    for i in indices:
        b=balls[i];p=b.position;r=b.spec.radius
        if table.pockets is not None:
            from .pockets import touches_surface
            if touches_surface(b,table):return True
        elif min(p.x-r,p.y-r,table.length-r-p.x,table.width-r-p.y)<=SPACE_EPS:return True
    return False


def simulate(balls, table=Table(), physics=Physics(), *, max_time=60.0, max_events=10000,cancel=None,record_segments=True,reject_events=None):
    """Forward solve; light recording keeps final/events, not replay samples.

    A cooperative cancellation predicate is checked at event and Hertz steps.
    Cancelled results are incomplete and must not be applied as a finished shot.
    reject_events may abort an impossible constraint prefix; this also produces
    an incomplete result and is only intended for inverse candidate pruning.
    """
    balls = tuple(balls)
    validate_scene(balls, table, physics)
    if not isfinite(max_time) or max_time <= 0:
        raise ValueError("max_time must be finite and positive")
    if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events <= 0:
        raise ValueError("max_events must be a positive integer")
    initial = balls
    events, segments = [], []
    if table.pockets is not None:
        from .pockets import unsupported_pocket
        for i, ball in enumerate(balls):
            pocket = unsupported_pocket(ball,table)
            if pocket is not None:
                before, changed = balls, list(balls)
                changed[i] = replace(ball,velocity=Vec2(),omega=Vec3(),pocket=pocket)
                balls = tuple(changed)
                events.append(Event(0.0,'ball_pocket',(ball.id,),pocket,before,balls))
    time, iterations, status = 0.0, 0, "max_time"
    while True:
        if cancel is not None and cancel():
            status='cancelled'
            break
        if reject_events is not None and reject_events(events):
            status='constraint_rejected'
            break
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
            if record_segments:segments.append(Segment(time, time+dt, balls, motions))
            balls = tuple(advance(b, m, dt) for b, m in zip(balls, motions))
        time += dt
        contacts = [c for c in group if c.kind != "transition"]
        if any(c.kind == "persistent_contact" for c in contacts):
            if (physics.contact_solver in ('cluster','hybrid_hertz') and all(len(c.indices)==2 for c in contacts)
                    and not island_touches_cushion(contacts,balls,table)):
                from .cluster import resolve_cluster, touching_pairs, project_positions, ClusterFailure
                positive=[c.time for c in candidates if c.time>1e-12]
                step=min(.002,horizon,max_time-time,*positive)
                if step<=1e-12:
                    status='cluster_model_failure'
                    break
                before=balls
                plastic=touching_pairs(balls)
                if record_segments:segments.append(Segment(time,time+step,balls,motions))
                stepped=tuple(advance(b,m,step) for b,m in zip(balls,motions))
                try:
                    stepped=project_positions(stepped)
                    balls,pairs=resolve_cluster(stepped,physics,plastic_pairs=plastic,allow_zero=True)
                except ClusterFailure:
                    status='cluster_model_failure'
                    break
                time+=step
                for i,j in pairs:
                    events.append(Event(time,'ball_ball',(balls[i].id,balls[j].id),'cluster-support',before,balls))
                iterations+=1
                continue
            status = "unsupported_persistent_contact"
            break
        if physics.contact_solver=='hybrid_hertz' and contacts and all(c.kind=='ball_ball' for c in contacts):
            from .elastic import nearby_network, burst, ElasticFailure, ElasticCancelled
            if nearby_network(contacts,balls) and elastic_window_clear(balls,table,.008):
                before=balls
                try:
                    elapsed,balls,micro,onsets=burst(balls,physics,limit=min(.008,max_time-time),cancel=cancel,record_segments=record_segments)
                except ElasticCancelled:
                    status='cancelled'
                    break
                except ElasticFailure:
                    status='elastic_model_failure'
                    break
                segments.extend(s.shifted(time) for s in micro)
                for onset,a,b,values in onsets:
                    events.append(Event(time+onset,'ball_ball',(a,b),'hertz-onset',values,values))
                time+=elapsed
                events.append(Event(time,'elastic_release',tuple(b.id for b in balls),'hertz-burst',before,balls))
                iterations+=1
                continue
        if coupled_contacts(contacts, balls, table, physics):
            if (physics.contact_solver in ('cluster','hybrid_hertz') and any(c.kind=='ball_ball' for c in contacts)
                    and all(c.kind in ('ball_ball','ball_cushion') for c in contacts)):
                from .cluster import resolve_network, ClusterFailure
                try:
                    balls,operations=resolve_network(balls,table,physics)
                except ClusterFailure:
                    status='cluster_model_failure'
                    break
                for kind,actors,detail,before,after in operations:
                    events.append(Event(time,kind,actors,detail,before,after))
                iterations+=1
                continue
            status = "unsupported_coupled_contact"
            break
        for c in group:
            if c.kind == "transition":
                events.append(Event(time, c.detail, (balls[c.indices[0]].id,), "",
                                    balls, balls))
        for c in contacts:
            before = balls
            changed = list(balls)
            if c.kind == "ball_pocket":
                i = c.indices[0]
                changed[i] = replace(balls[i],velocity=Vec2(),omega=Vec3(),pocket=c.detail)
            elif c.kind == "ball_ball":
                i, j = c.indices
                changed[i], changed[j] = resolve_ball_contact(balls[i], balls[j], physics)
            else:
                i = c.indices[0]
                if table.pockets is not None:
                    from .pockets import resolve_surface
                    try:
                        changed[i] = resolve_surface(balls[i],c.detail,table,physics)
                    except CushionFailure:
                        return Result(initial,balls,table,physics,time,"cushion_model_failure",
                                      tuple(events),tuple(segments))
                elif physics.cushion_model == "frictionless":
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


def elastic_window_clear(balls,table,window):
    """Conservative global energy bound excludes rails/pockets during a burst."""
    active=[b for b in balls if b.pocket is None]
    reach=sqrt(2*sum(b.energy for b in active)/min(b.spec.mass for b in active))*window+1e-5
    if table.pockets is not None:
        from .pockets import outline
        surfaces=outline(table).surfaces
        return all(s.distance_squared(b.position)>(b.spec.radius+s.radius+reach)**2 for b in active for s in surfaces)
    return all(min(b.position.x,b.position.y,table.length-b.position.x,table.width-b.position.y)>b.spec.radius+reach for b in active)
