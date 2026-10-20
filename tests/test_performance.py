"""Accuracy contracts for lighter playback and explicitly perturbed racks."""
from copy import deepcopy
import gzip
import json

import pytest

from billiards.engine import real_roots
from billiards.game import GameStore
from billiards.play import PlayService
from billiards.rules import adjudicate, racked_balls, group


@pytest.fixture(scope='module')
def service():return PlayService(table_profile='cbsa_2017')


@pytest.mark.parametrize('seed',range(12))
def test_micro_gap_rack_is_bounded_reproducible_and_nonoverlapping(service,seed):
    tight=racked_balls(service,seed,0);loose=racked_balls(service,seed,.2)
    assert loose==racked_balls(service,seed,.2) and loose!=racked_balls(service,seed+1,.2)
    assert loose[1].position==tight[1].position
    assert loose[5].id=='8' and {group(loose[11].id),group(loose[15].id)}=={'solid','stripe'}
    gaps=[]
    for i,a in enumerate(tight[1:],1):
        for j,b in enumerate(tight[i+1:],i+1):
            distance=(loose[i].position-loose[j].position).norm()
            assert distance>=a.spec.radius+b.spec.radius-1e-12
            if abs((a.position-b.position).norm()-2*a.spec.radius)<1e-10:gaps.append(distance-2*a.spec.radius)
    assert len(gaps)==30 and all(0<=gap<=.0002+1e-12 for gap in gaps)
    assert max(gaps)-min(gaps)>1e-5
    service.decode(service.snapshot(loose,__import__('billiards.cue',fromlist=['ShotInput']).ShotInput(0,4)))


@pytest.mark.parametrize('gap',[-1,.51,True,float('nan'),'0.2'])
def test_invalid_rack_gaps_rejected(service,gap):
    with pytest.raises(ValueError):GameStore(service).new({'gap_mm':gap})


@pytest.mark.parametrize('seed',[0,7,19])
def test_micro_gap_breaks_finish_and_compact_decision_matches_full(service,seed):
    store=GameStore(service);game=store.new({'seed':seed,'gap_mm':.2})
    full=service.shoot(game['scene']);compact=service.shoot(game['scene'],compact=True)
    assert full['complete'] and compact['complete']
    for key in ('initial','final'):assert full['result'][key]==compact['result'][key]
    # Numeric playback rows are lossless, including every contact microstep.
    assert compact['result']['detail']=='playback-v2'
    for a,b in zip(full['result']['segments'],compact['result']['segments'],strict=True):
        assert [a['start'],a['end']]==b[:2]
        for ball,row in zip(a['balls'],b[2],strict=True):
            assert [*ball['position'].values(),*ball['velocity'].values(),*ball['omega'].values(),ball['pocket']]==row
        for motion,row in zip(a['motion'],b[3],strict=True):
            assert [motion['phase'],*motion['acceleration'].values(),*motion['angular_acceleration'].values()]==row
    assert adjudicate(game,full,service)==adjudicate(game,compact,service)
    before=next(e for e in full['result']['events'] if 'cue' in e['actors'] and e['kind'] in ('ball_ball','ball_cushion','ball_pocket'))
    after=next(e for e in compact['result']['events'] if 'before' in e)
    assert after['before']==[b for b in before['before'] if b['id'] in before['actors']]
    assert all('after' not in e for e in compact['result']['events'])
    assert len(json.dumps(compact))<len(json.dumps(full))*.6


def test_server_rack_randomness_is_persisted_not_rerolled_on_restore(service,monkeypatch):
    values=iter([12,34]);monkeypatch.setattr('billiards.game.secrets.randbits',lambda _:next(values))
    store=GameStore(service);one=store.new({});two=store.new({})
    assert one['seed']!=two['seed'] and one['scene']!=two['scene']
    assert store.get({'id':one['id']})==one
    assert one['gap_mm']==.2


@pytest.mark.parametrize('coeff,horizon,expected',[([-2,1],3,[2]),([2,-3,1],3,[1,2]),
    ([0,0,1],2,[0]),([1,0,1],2,[]),([1,-1e8,1],1,[1e-8])])
def test_stable_low_order_roots(coeff,horizon,expected):
    assert real_roots(coeff,horizon)==pytest.approx(expected,abs=1e-12)


def test_standard_ball_table_scale(service):
    assert service.ball_spec.radius*2==.05715
    assert service.ball_spec.radius*2/service.table.length==pytest.approx(.0225)
    assert service.table.width/(2*service.ball_spec.radius)==pytest.approx(22.2222222222)
