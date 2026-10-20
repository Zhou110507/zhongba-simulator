"""Deterministic unilateral impulse solve for touching ball networks.

Projected Gauss-Seidel solves the normal complementarity constraints together
with bounded horizontal friction. Isolated impacts retain their original model.
Mixed islands alternate passive ball and cushion solves; persistent rail
support still uses the engine's explicit limitation.
"""

from dataclasses import replace

import numpy as np

from .ball_contact import contact_data
from .model import Vec2, Vec3


class ClusterFailure(RuntimeError):
    pass


def resolve_cluster(balls,physics,plastic_pairs=(),allow_zero=False):
    pairs=[]
    # Stable physical ordering, independent of the caller's list order.
    order=sorted((i for i,b in enumerate(balls) if b.pocket is None),key=lambda i:balls[i].id)
    for k,i in enumerate(order):
        a=balls[i]
        for j in order[k+1:]:
            b=balls[j];dp=b.position-a.position
            if dp.norm()>a.spec.radius+b.spec.radius+2e-9:continue
            info=contact_data(a,b,physics)
            n,t=info['normal'],info['tangent']
            budget=(info['friction_coefficient']*abs(info['horizontal_slip_m_s'])/info['surface_slip_m_s']
                    if info['surface_slip_m_s']>1e-12 else 0)
            pairs.append((i,j,n,t,budget))
    if not pairs:raise ClusterFailure('No touching constraints')
    count=len(balls);dofs=count*3
    state=np.array([v for b in balls for v in (b.velocity.x,b.velocity.y,b.omega.z)],dtype=float)
    inverse=np.array([v for b in balls for v in (1/b.spec.mass,1/b.spec.mass,1/b.spec.inertia)])
    normal=np.zeros((len(pairs),dofs));tangent=np.zeros_like(normal)
    for row,(i,j,n,t,_) in enumerate(pairs):
        normal[row,3*i:3*i+2]=(-n.x,-n.y);normal[row,3*j:3*j+2]=(n.x,n.y)
        tangent[row,3*i:3*i+3]=(t.x,t.y,balls[i].spec.radius)
        tangent[row,3*j:3*j+3]=(-t.x,-t.y,balls[j].spec.radius)
    vn0=normal@state
    target=-physics.ball_restitution*np.minimum(vn0,0)
    for row,(i,j,*_) in enumerate(pairs):
        if frozenset((balls[i].id,balls[j].id)) in plastic_pairs:
            target[row]=0
    kn=np.sum(normal*normal*inverse,axis=1);kt=np.sum(tangent*tangent*inverse,axis=1)
    normal_response=normal*inverse;tangent_response=tangent*inverse
    jn=np.zeros(len(pairs));jt=np.zeros(len(pairs))
    for iteration in range(4000):
        change=0.0
        for row,(_,_,_,_,mu) in enumerate(pairs):
            updated=max(0,jn[row]+(target[row]-normal[row]@state)/kn[row])
            delta=updated-jn[row];jn[row]=updated;state+=normal_response[row]*delta
            bound=mu*updated
            updated_t=float(np.clip(jt[row]+(tangent[row]@state)/kt[row],-bound,bound))
            delta_t=updated_t-jt[row];jt[row]=updated_t;state-=tangent_response[row]*delta_t
            change=max(change,abs(delta),abs(delta_t))
        if change<1e-13 and np.min(normal@state-target)>-1e-11:break
    else:raise ClusterFailure('Contact island did not converge')
    changed=tuple(replace(b,velocity=Vec2(*state[3*i:3*i+2]),omega=Vec3(b.omega.x,b.omega.y,state[3*i+2]))
                  for i,b in enumerate(balls))
    if sum(b.energy for b in changed)>sum(b.energy for b in balls)+1e-9:
        raise ClusterFailure('Contact island violates passivity')
    active=[(i,j) for row,(i,j,*_) in enumerate(pairs) if jn[row]>1e-12]
    if not active and not allow_zero:raise ClusterFailure('No compressive impulse')
    return changed,active


def touching_pairs(balls):
    return {frozenset((a.id,b.id)) for i,a in enumerate(balls) for b in balls[i+1:]
            if a.pocket is None and b.pocket is None and
            (a.position-b.position).norm()<=a.spec.radius+b.spec.radius+2e-9}


def resolve_network(balls,table,physics):
    """Deterministic alternating impulses for a ball network touching cushions.

    Each ball island solve and cushion impulse is passive. Repeated impulses
    propagate compression until all touching surfaces separate. This is a rigid
    multiple-impact approximation, not a calibrated finite-duration rack model.
    """
    from .cushion import resolve_cushion, CushionFailure
    from .pockets import outline, resolve_surface
    operations=[]
    surfaces=outline(table).surfaces if table.pockets is not None else ()
    for _ in range(128):
        before=balls
        balls,pairs=resolve_cluster(balls,physics,allow_zero=True)
        for i,j in pairs:operations.append(('ball_ball',(balls[i].id,balls[j].id),'cluster',before,balls))
        walls=[]
        for i,b in sorted(enumerate(balls),key=lambda item:item[1].id):
            if b.pocket is not None:continue
            if surfaces:
                seen=[]
                for s in surfaces:
                    dp=s.closest(b.position)-b.position;distance=dp.norm()
                    if distance>b.spec.radius+s.radius+2e-9 or distance<1e-12:continue
                    n=dp*(1/distance)
                    if b.velocity.dot(n)>1e-10 and not any((n-other).norm()<1e-7 for other in seen):
                        seen.append(n);walls.append((i,s.id))
            else:
                for name,gap,approach in [('left',b.position.x-b.spec.radius,-b.velocity.x),
                    ('right',table.length-b.spec.radius-b.position.x,b.velocity.x),
                    ('bottom',b.position.y-b.spec.radius,-b.velocity.y),
                    ('top',table.width-b.spec.radius-b.position.y,b.velocity.y)]:
                    if gap<2e-9 and approach>1e-10:walls.append((i,name))
        if not walls:return balls,operations
        for i,name in walls:
            before=balls;changed=list(balls)
            try:
                if surfaces:changed[i]=resolve_surface(balls[i],name,table,physics)
                elif physics.cushion_model=='frictionless':
                    from .engine import resolve_wall
                    changed[i]=resolve_wall(balls[i],name,table,physics.cushion_restitution)
                else:changed[i]=resolve_cushion(balls[i],name,table,physics)
            except CushionFailure as error:raise ClusterFailure(str(error)) from error
            balls=tuple(changed)
            operations.append(('ball_cushion',(balls[i].id,),name,before,balls))
    raise ClusterFailure('Mixed contact network did not separate')


def project_positions(balls):
    """Mass-weighted nonpenetration correction after a 2 ms support step."""
    balls=list(balls)
    order=sorted(range(len(balls)),key=lambda i:balls[i].id)
    for _ in range(128):
        maximum=0.0
        for k,i in enumerate(order):
            for j in order[k+1:]:
                a,b=balls[i],balls[j]
                if a.pocket is not None or b.pocket is not None:continue
                dp=b.position-a.position;distance=dp.norm();overlap=a.spec.radius+b.spec.radius-distance
                if overlap<=1e-12:continue
                if distance<=1e-12:raise ClusterFailure('Coincident ball centres')
                maximum=max(maximum,overlap)
                delta=dp*(overlap/distance/(1/a.spec.mass+1/b.spec.mass))
                balls[i]=replace(a,position=a.position-delta*(1/a.spec.mass))
                balls[j]=replace(b,position=b.position+delta*(1/b.spec.mass))
        if maximum<1e-11:return tuple(balls)
    raise ClusterFailure('Position projection did not converge')
