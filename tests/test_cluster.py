"""Multi-ball impulse invariants and real tightly packed rack integration."""
from dataclasses import replace
from math import sqrt

import pytest

from billiards.cluster import resolve_cluster, project_positions
from billiards.engine import simulate
from billiards.game import GameStore
from billiards.model import Ball, Physics, Table, Vec2, Vec3
from billiards.play import PlayService


@pytest.mark.parametrize('e',[0,.5,.95,1])
def test_touching_chain_preserves_momentum_passivity_and_input_order(e):
    r=Ball('a',Vec2()).spec.radius
    balls=(Ball('a',Vec2(.4,.4),Vec2(2,.1)),Ball('b',Vec2(.4+2*r,.4)),Ball('c',Vec2(.4+4*r,.4)))
    physics=Physics(ball_restitution=e,contact_solver='cluster')
    out,pairs=resolve_cluster(balls,physics)
    reversed_out,_=resolve_cluster(tuple(reversed(balls)),physics)
    by_id={b.id:b for b in reversed_out}
    assert len(pairs)==2
    assert sum(b.spec.mass*b.velocity.x for b in out)==pytest.approx(sum(b.spec.mass*b.velocity.x for b in balls),abs=1e-12)
    assert sum(b.spec.mass*b.velocity.y for b in out)==pytest.approx(sum(b.spec.mass*b.velocity.y for b in balls),abs=1e-12)
    assert sum(b.energy for b in out)<=sum(b.energy for b in balls)+1e-12
    for b in out:assert b==by_id[b.id]
    assert out[1].velocity.x>=out[0].velocity.x-1e-10
    assert out[2].velocity.x>=out[1].velocity.x-1e-10


def test_position_projection_preserves_center_of_mass():
    r=Ball('a',Vec2()).spec.radius
    balls=(Ball('a',Vec2(.5,.5)),Ball('b',Vec2(.5+2*r-1e-5,.5)))
    out=project_positions(balls)
    assert sum(b.position.x*b.spec.mass for b in out)==pytest.approx(sum(b.position.x*b.spec.mass for b in balls),abs=1e-14)
    assert (out[0].position-out[1].position).norm()==pytest.approx(2*r,abs=1e-12)


def test_mixed_network_does_not_silently_ignore_frozen_rail():
    r=Ball('a',Vec2()).spec.radius;table=Table()
    balls=(Ball('a',Vec2(table.length-3*r,.5),Vec2(1,0)),Ball('b',Vec2(table.length-r,.5)))
    result=simulate(balls,table,Physics(contact_solver='cluster'))
    assert result.status=='stopped'
    assert any(e.kind=='ball_cushion' for e in result.events)
    assert sum(b.energy for b in result.final)<=sum(b.energy for b in balls)


@pytest.mark.parametrize('angle,speed',[(0,4),(.45,5)])
def test_actual_tightly_racked_break_completes_and_commits_legal_decision(angle,speed):
    service=PlayService(table_profile='cbsa_2017');store=GameStore(service);game=store.new({'seed':0})
    request={'id':game['id'],'revision':0,'shot':{**game['scene']['shot'],'angle_deg':angle,'cue_speed':speed}}
    preview=store.preview(request)
    assert preview['complete'],preview['result']['status']
    assert store.get({'id':game['id']})['revision']==0
    result=store.action({**request,'action':'shoot'})
    assert result['rule_committed'] and result['game_after']['revision']==1
    assert result['game_after']['groups']==[None,None]
    assert result['game_after']['last_decision']['break_object_cushions']>=4 or result['summary']['potted']
    service.decode(result['next_scene'])
    # Every instantaneous contact obeys passivity; no external energy is added.
    for event in result['result']['events']:
        if event['kind']!='ball_ball':continue
        def energy(values):
            return sum(.5*b['spec']['mass']*(b['velocity']['x']**2+b['velocity']['y']**2)+
                       .2*b['spec']['mass']*b['spec']['radius']**2*sum(w*w for w in b['omega'].values()) for b in values)
        assert energy(event['after'])<=energy(event['before'])+1e-8
    for segment in result['result']['segments']:
        active=[b for b in segment['balls'] if b['pocket'] is None]
        for i,a in enumerate(active):
            for b in active[i+1:]:
                distance=sqrt(sum((a['position'][axis]-b['position'][axis])**2 for axis in ('x','y')))
                assert distance>=a['spec']['radius']+b['spec']['radius']-1e-8
