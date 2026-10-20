"""Independent collision limits and time-step convergence, not visual tuning."""
from dataclasses import replace

import pytest

from billiards.elastic import burst, stored_energy
from billiards.model import Ball, Physics, Vec2
from billiards.play import PlayService
from billiards.rules import racked_balls


@pytest.mark.parametrize('speed',[.3,1,5,6.6])
def test_two_equal_balls_recover_configured_restitution_and_momentum(speed):
    r=Ball('a',Vec2()).spec.radius
    values=(Ball('a',Vec2(.5,.5),Vec2(speed,0)),Ball('b',Vec2(.5+2*r,.5)))
    p=Physics(ball_contact_model='frictionless')
    elapsed,final,segments,_=burst(values,p)
    assert 0<elapsed<.003
    assert (final[1].velocity.x-final[0].velocity.x)/speed==pytest.approx(.95,abs=.0003)
    assert sum(b.velocity.x for b in final)==pytest.approx(speed,abs=1e-12)
    energy=values[0].energy
    assert all(sum(b.energy for b in balls)+stored_energy(balls,p)<=energy*1.0003 for _,_,balls,_ in segments)
    assert stored_energy(final,p)<1e-15


def test_touching_chain_transmits_an_elastic_wave_instead_of_a_rigid_push():
    r=Ball('a',Vec2()).spec.radius
    values=tuple(Ball(str(i),Vec2(.5+2*r*i,.5),Vec2(2 if i==0 else 0,0)) for i in range(3))
    _,final,_,_=burst(values,Physics())
    # A compliant Newton's cradle transfers most kinetic energy to the end ball.
    assert final[-1].velocity.x>1.7
    assert abs(final[0].velocity.x)<.3
    assert sum(b.energy for b in final)>.8*sum(b.energy for b in values)


@pytest.mark.parametrize('gap',[0,.2])
def test_rack_step_halving_convergence_energy_and_input_order(gap):
    service=PlayService(table_profile='cbsa_2017');p=service.physics
    values=list(racked_balls(service,0,gap))
    values[0]=replace(values[0],position=values[1].position-Vec2(2*service.ball_spec.radius,0),velocity=Vec2(4.7,0))
    elapsed,final,segments,_=burst(tuple(values),p)
    _,fine,_,_=burst(tuple(values),p,step=p.elastic_step/2)
    _,reverse,_,_=burst(tuple(reversed(values)),p)
    by_id={b.id:b for b in reverse}
    assert max((a.velocity-b.velocity).norm() for a,b in zip(final,fine))<.003
    assert max((b.velocity-by_id[b.id].velocity).norm() for b in final)<1e-10
    assert max((b.position-by_id[b.id].position).norm() for b in final)<1e-12
    initial=sum(b.energy for b in values)
    assert sum(b.energy for b in final)<=initial
    assert all(sum(b.energy for b in balls)+stored_energy(balls,p)<=initial*1.0003 for _,_,balls,_ in segments)
    assert elapsed<.003
