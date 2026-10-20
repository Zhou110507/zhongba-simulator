"""Short Hertz contact bursts for nearby ball networks; free flight stays CCD.

Elastic stiffness: Moreno et al. (2022), DOI 10.1007/s11071-021-07117-4,
table 1 and equation 3.4 (phenolic resin E=3.8 GPa, nu=.375).
The dissipative exponent 1/4 gives speed-independent restitution: Ramirez
et al. (1999), DOI 10.1103/PhysRevE.60.4465, section II. Damping is calibrated
numerically to the configured isolated-ball restitution, not to rack spread.
This is a planar approximation, not measured Chinese-eight-ball calibration.
"""
from dataclasses import dataclass, replace
from functools import cached_property, lru_cache
from math import inf, sqrt

import numpy as np

from .model import Vec2, Vec3
from .motion import Motion


class ElasticFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ContactStep:
    """Keep the dense integrator state; materialize audit objects only on demand."""
    start: float
    end: float
    source: tuple
    order: tuple
    position: np.ndarray
    velocity: np.ndarray
    spin: np.ndarray
    acceleration: np.ndarray
    angular: np.ndarray

    @cached_property
    def balls(self):
        values=list(self.source)
        for row,index in enumerate(self.order):
            b=self.source[index]
            values[index]=replace(b,position=Vec2(*self.position[row]),velocity=Vec2(*self.velocity[row]),omega=Vec3(b.omega.x,b.omega.y,self.spin[row]))
        return tuple(values)

    @cached_property
    def motions(self):
        values=[Motion('elastic_contact',Vec2(),Vec3(),inf,None) for _ in self.source]
        for row,index in enumerate(self.order):values[index]=Motion('elastic_contact',Vec2(*self.acceleration[row]),Vec3(0,0,self.angular[row]),inf,None)
        return tuple(values)

    def __iter__(self):
        yield self.start;yield self.end;yield self.balls;yield self.motions

    def shifted(self,time):
        return replace(self,start=self.start+time,end=self.end+time)

    def packed(self):
        states=[[b.position.x,b.position.y,b.velocity.x,b.velocity.y,b.omega.x,b.omega.y,b.omega.z,b.pocket] for b in self.source]
        motions=[['elastic_contact',0,0,0,0,0] for _ in self.source]
        for row,index in enumerate(self.order):
            states[index][:4]=[*self.position[row],*self.velocity[row]];states[index][6]=self.spin[row]
            motions[index][1:3]=self.acceleration[row].tolist();motions[index][5]=self.angular[row]
        return [self.start,self.end,states,motions]


@lru_cache(maxsize=32)
def damping_ratio(restitution):
    """Dimensionless F=x**1.5 + gamma*x**.25*x_dot, clipped nonadhesive."""
    if restitution == 1:return 0.0
    if not 0 < restitution <= 1:raise ElasticFailure('Hertz restitution must be positive')
    def rebound(gamma):
        x,v=0.,1.;h=.002
        def acc(x,v):return -max(0.,max(x,0.)**1.5+gamma*max(x,0.)**.25*v)
        for _ in range(6000):
            a=acc(x,v);b=acc(x+h*v/2,v+h*a/2)
            c=acc(x+h*v/2+h*h*a/4,v+h*b/2);d=acc(x+h*v+h*h*b/2,v+h*c)
            x,v=x+h*v+h*h*(a+b+c)/6,v+h*(a+2*b+2*c+d)/6
            if x<=0:return -v
        return 0.
    low,high=0.,8.
    for _ in range(30):
        mid=(low+high)/2
        if rebound(mid)>restitution:low=mid
        else:high=mid
    return (low+high)/2


def stiffness(a,b,physics):
    radius=a.spec.radius*b.spec.radius/(a.spec.radius+b.spec.radius)
    return 2*physics.ball_young_modulus*sqrt(radius)/(3*(1-physics.ball_poisson_ratio**2))


def stored_energy(balls,physics):
    return sum(stiffness(a,b,physics)*max(0,a.spec.radius+b.spec.radius-(b.position-a.position).norm())**2.5/2.5
               for i,a in enumerate(balls) for b in balls[i+1:] if a.pocket is None and b.pocket is None)


def nearby_network(contacts,balls,margin=.001):
    """Include microgaps before treating the first rack hit as isolated."""
    for c in contacts:
        if c.kind!='ball_ball':continue
        for i in c.indices:
            if any(j not in c.indices and b.pocket is None and
                   (b.position-balls[i].position).norm()<=b.spec.radius+balls[i].spec.radius+margin
                   for j,b in enumerate(balls)):return True
    return False


def burst(balls,physics,*,limit=.008,step=None):
    """Return (elapsed, final, microsegments, contact-onsets).

    Integrate all active balls together, never project a compressed rack into
    plastic velocity constraints. Cloth impulse is neglected only inside this
    millisecond impact interval, as in the isolated impulse model. The caller
    must exclude boundaries for the entire bounded window. Intermediate geometric
    overlaps represent elastic indentation and carry explicit potential energy.
    """
    order=sorted((i for i,b in enumerate(balls) if b.pocket is None),key=lambda i:balls[i].id)
    source=tuple(balls[i] for i in order);n=len(source)
    p=np.array([(b.position.x,b.position.y) for b in source]);v=np.array([(b.velocity.x,b.velocity.y) for b in source])
    wz=np.array([b.omega.z for b in source]);r=np.array([b.spec.radius for b in source]);mass=np.array([b.spec.mass for b in source])
    inertia=.4*mass*r*r;i,j=np.triu_indices(n,1);diameter=r[i]+r[j]
    k=2*physics.ball_young_modulus*np.sqrt(r[i]*r[j]/diameter)/(3*(1-physics.ball_poisson_ratio**2))
    reduced=mass[i]*mass[j]/(mass[i]+mass[j]);damping=damping_ratio(physics.ball_restitution)*np.sqrt(k*reduced)
    hz=np.array([b.omega.x for b in source]);hy=np.array([b.omega.y for b in source])
    def force(pos,vel,spin):
        dp=pos[j]-pos[i];distance=np.sqrt(np.sum(dp*dp,axis=1));normal=dp/distance[:,None]
        overlap=np.maximum(diameter-distance,0);relative=vel[i]-vel[j]
        approach=np.sum(relative*normal,axis=1)
        fn=np.maximum(0,k*overlap**1.5+damping*overlap**.25*approach)
        tangent=np.column_stack((-normal[:,1],normal[:,0]));horizontal=np.sum(relative*tangent,axis=1)+r[i]*spin[i]+r[j]*spin[j]
        vertical=r[i]*(hz[i]*normal[:,1]-hy[i]*normal[:,0])+r[j]*(hz[j]*normal[:,1]-hy[j]*normal[:,0])
        slip=np.hypot(horizontal,vertical)
        mu=physics.ball_friction_a+physics.ball_friction_b*np.exp(-physics.ball_friction_c*slip) if physics.ball_friction_model=='alciatore' else physics.ball_friction
        ft=mu*fn*horizontal/np.maximum(slip,.02) if physics.ball_contact_model=='projected_throw' else np.zeros_like(fn)
        f=normal*fn[:,None]+tangent*ft[:,None]
        acceleration=np.column_stack([np.bincount(j,weights=f[:,axis],minlength=n)-np.bincount(i,weights=f[:,axis],minlength=n) for axis in range(2)])/mass[:,None]
        angular=-(np.bincount(i,weights=r[i]*ft,minlength=n)+np.bincount(j,weights=r[j]*ft,minlength=n))/inertia
        return acceleration,angular,overlap,fn
    def snapshot(pos,vel,spin):
        changed=list(balls)
        for row,index in enumerate(order):
            b=balls[index];changed[index]=replace(b,position=Vec2(*pos[row]),velocity=Vec2(*vel[row]),omega=Vec3(b.omega.x,b.omega.y,spin[row]))
        return tuple(changed)
    h=step or physics.elastic_step;elapsed=0.;segments=[];onsets=[];seen=set();initial_energy=sum(b.energy for b in balls)
    while elapsed<limit-1e-14:
        dt=min(h,limit-elapsed)
        a,az,_,_=force(p,v,wz)
        am,azm,overlap,fn=force(p+v*(dt/2)+a*(dt*dt/8),v+a*(dt/2),wz+az*(dt/2))
        for pair in np.flatnonzero(fn>1e-7):
            key=(int(i[pair]),int(j[pair]))
            if key not in seen:
                seen.add(key);onsets.append((elapsed,source[key[0]].id,source[key[1]].id,snapshot(p,v,wz)))
        segments.append(ContactStep(elapsed,elapsed+dt,tuple(balls),tuple(order),p,v,wz,am,azm))
        p=p+v*dt+am*(dt*dt/2);v=v+am*dt;wz=wz+azm*dt;elapsed+=dt
        gap=np.sqrt(np.sum((p[j]-p[i])**2,axis=1))-diameter
        if np.min(gap)>=-1e-12 and seen:
            final=snapshot(p,v,wz)
            if sum(b.energy for b in final)>initial_energy+max(1e-8,initial_energy*2e-5):raise ElasticFailure('Hertz burst violates energy budget')
            return elapsed,final,segments,onsets
    raise ElasticFailure('Hertz contact did not release within bounded window')
