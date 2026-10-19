"""Coupled cushion and cloth impulses with three-axis angular momentum.

The force balance and energetic restitution follow the two-contact construction
in Mathavan et al. (2010), equations 3--14 and section 3.3. This independent
split-impulse approximation bounds each tangential impulse by Coulomb friction
and arrests slip instead of numerically overshooting zero. It is NOT a claim of
having calibrated or exactly reproduced the published solver or a Chinese rail.

Local X runs along the rail, Y points into it, and Z points upward. State stores
(vX,vY,R*wX,R*wY,R*wZ); accumulated normal impulse is divided by mass.
"""

from dataclasses import replace
from math import hypot, sqrt

from .model import Vec2, Vec3


class CushionFailure(RuntimeError):
    pass


def _friction(ux, uy, kx, ky, budget):
    """Stick if possible; otherwise oppose the actual contact slip direction."""
    speed = hypot(ux,uy)
    if not speed or not budget:
        return 0.0,0.0
    jx,jy = -ux/kx,-uy/ky
    if hypot(jx,jy) <= budget:
        return jx,jy
    return -budget*ux/speed,-budget*uy/speed


def _step(state, dp, sine, cosine, mu_wall, mu_cloth):
    vx,vy,qx,qy,qz = state
    # Normal impulse has no torque (its line passes through the sphere centre).
    compression_work = cosine*(vy-.5*cosine*dp)*dp
    vy -= cosine*dp
    # Cushion tangential plane: X and Y' = -sin(theta)Y + cos(theta)Z.
    ux,uy = vx+sine*qy-cosine*qz, -sine*vy+qx
    jx,jy = _friction(ux,uy,3.5,2.5+sine*sine,mu_wall*dp)
    vx += jx
    vy -= sine*jy
    qx += 2.5*jy
    qy += 2.5*sine*jx
    qz -= 2.5*cosine*jx
    # Table reaction keeps vz=0. Its horizontal friction also exerts torque.
    reaction = sine*dp-cosine*jy
    if reaction < -1e-12:
        raise CushionFailure("Lift-off is outside the planar contact model")
    cx,cy = _friction(vx-qy,vy+qx,3.5,3.5,mu_cloth*max(0,reaction))
    return (vx+cx,vy+cy,qx+2.5*cy,qy-2.5*cx,qz),compression_work


def solve_contact(state, restitution, mu_wall, mu_cloth, height_ratio, steps):
    """Compression to vY=0; restitution returns e^2 of stored normal work.

    Every friction substep dissipates energy. Normal work is explicitly tracked,
    so energetic restitution cannot create total mechanical energy for 0<=e<=1.
    Integration resolution is relative to impact speed, not display frame rate.
    """
    if state[1] <= 0:
        return state
    sine = height_ratio-1
    cosine = sqrt(1-sine*sine)
    dp = state[1]/(cosine*steps)
    compression = 0.0
    for _ in range(8*steps):
        trial,work = _step(state,dp,sine,cosine,mu_wall,mu_cloth)
        amount = dp
        done = trial[1] <= 0
        if done:
            lo,hi = 0.0,dp
            for _ in range(44):
                middle = (lo+hi)/2
                candidate,_ = _step(state,middle,sine,cosine,mu_wall,mu_cloth)
                if candidate[1] > 0:
                    lo = middle
                else:
                    hi = middle
            amount = (lo+hi)/2
            trial,work = _step(state,amount,sine,cosine,mu_wall,mu_cloth)
        compression += work
        state = trial
        if done:
            state = (state[0],0.0,*state[2:])
            break
    else:
        raise CushionFailure("Compression did not converge")
    remaining = restitution*restitution*compression
    for _ in range(8*steps):
        if remaining <= 0:
            return state
        # Work contributed by the normal substep, before tangential impulses.
        gain = cosine*(-state[1]+.5*cosine*dp)*dp
        amount = dp
        done = gain >= remaining
        if done:
            amount = 2*remaining/(cosine*(sqrt(state[1]**2+2*remaining)-state[1]))
        state,work = _step(state,amount,sine,cosine,mu_wall,mu_cloth)
        remaining += work
        if done:
            return state
    raise CushionFailure("Restitution did not converge")


def resolve_cushion(ball, name, table, physics):
    normals = {"left":Vec2(-1,0),"right":Vec2(1,0),
               "bottom":Vec2(0,-1),"top":Vec2(0,1)}
    position = {"left":Vec2(ball.spec.radius,ball.position.y),
                "right":Vec2(table.length-ball.spec.radius,ball.position.y),
                "bottom":Vec2(ball.position.x,ball.spec.radius),
                "top":Vec2(ball.position.x,table.width-ball.spec.radius)}[name]
    return resolve_cushion_normal(ball,normals[name],physics,position)


def resolve_cushion_normal(ball, n, physics, position=None):
    if abs(n.norm()-1) > 1e-8:
        raise ValueError("Cushion normal must be a unit vector pointing into the cushion")
    tangent = Vec2(n.y,-n.x)
    r = ball.spec.radius
    v,w = ball.velocity,ball.omega
    state = (v.dot(tangent),v.dot(n),
             r*(w.x*tangent.x+w.y*tangent.y),r*(w.x*n.x+w.y*n.y),r*w.z)
    vx,vy,qx,qy,qz = solve_contact(state,physics.cushion_restitution,
                                  physics.cushion_friction,physics.sliding_friction,
                                  physics.cushion_contact_height_ratio,physics.cushion_steps)
    velocity = tangent*vx+n*vy
    xy_omega = tangent*(qx/r)+n*(qy/r)
    result = replace(ball,position=position or ball.position,velocity=velocity,
                     omega=Vec3(xy_omega.x,xy_omega.y,qz/r))
    if result.energy > ball.energy+1e-10*max(1,ball.energy):
        raise CushionFailure("Passive cushion created mechanical energy")
    return result
