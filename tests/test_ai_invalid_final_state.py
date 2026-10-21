"""A rejected physical endpoint must never abort a search or commit a match."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from billiards.cue import ShotInput, strike
from billiards.engine import simulate
from billiards.game import GameStore
from billiards.model import Ball, Vec2, Vec3, validate_scene
from billiards.play import PlayService
from billiards.runout import Search


@pytest.fixture(scope='module')
def case():
    return json.loads((Path(__file__).parent/'fixtures'/'ai-invalid-final-state.json').read_text(encoding='utf8'))


@pytest.fixture(scope='module')
def service():return PlayService(table_profile='cbsa_2017')


def test_real_candidate_is_incomplete_with_both_recording_modes(service,case):
    state=case['candidate'];balls,_=service.decode(state['scene']);shot=ShotInput(**case['shot'])
    launched=tuple(strike(b,shot,service.cue) if b.id=='cue' else b for b in balls)
    for recording in (False,True):
        result=simulate(launched,service.table,service.physics,record_segments=recording)
        assert result.status=='invalid_final_state'
        with pytest.raises(ValueError,match='Balls 12 and 13 overlap'):
            validate_scene(result.final,service.table,service.physics)
        # Reject the physical output rather than moving balls to certify it.
        a,b=(next(x for x in result.final if x.id==key) for key in ('12','13'))
        assert a.spec.radius+b.spec.radius-(a.position-b.position).norm()==pytest.approx(.0003890486777,abs=1e-10)


def test_search_discards_bad_candidate_and_can_continue(service,case):
    state=deepcopy(case['candidate']);before=deepcopy(state)
    search=Search(service,trained=False,seconds=20,evaluations=10)
    assert search.forward(state,ShotInput(**case['shot'])) is None
    assert search.count==1
    assert search.rejected['simulation:invalid_final_state']==1
    # A different, real stroke still runs through physics and adjudication.
    value=search.forward(state,ShotInput(0,.5,0,.5))
    assert value is not None
    service.decode(value[1]['scene'])
    assert state==before


def test_invalid_result_cannot_advance_or_persist_game(service,case,tmp_path):
    state=deepcopy(case['candidate']);games=GameStore(service,tmp_path,compact=True)
    games.games[state['id']]=state;games._save(state)
    path=tmp_path/(state['id']+'.json');saved=path.read_bytes()
    response=games.action({'id':state['id'],'revision':state['revision'],'action':'shoot','shot':case['shot']})
    assert response['result']['status']=='invalid_final_state'
    assert not response['complete'] and not response['rule_committed']
    assert response['next_scene'] is None
    assert games.games[state['id']]==state and path.read_bytes()==saved
    assert response['game_after']['revision']==state['revision']


@pytest.mark.parametrize('kind',['overlap','outside','nonfinite'])
def test_other_invalid_contact_endpoints_are_rejected(kind,monkeypatch):
    from billiards import engine
    balls=(Ball('cue',Vec2(.4,.5),Vec2(1,0)),Ball('1',Vec2(.8,.5)))
    def broken_contact(a,b,physics):
        a=replace(a,velocity=Vec2(),omega=Vec3())
        position={'overlap':a.position,'outside':Vec2(-1,.5),'nonfinite':Vec2(float('nan'),.5)}[kind]
        return a,replace(b,position=position,velocity=Vec2(),omega=Vec3())
    monkeypatch.setattr(engine,'resolve_ball_contact',broken_contact)
    result=engine.simulate(balls)
    assert result.status=='invalid_final_state'


def test_existing_contact_tolerance_and_bad_input_contract_remain():
    a=Ball('cue',Vec2(.4,.5));r=a.spec.radius
    touching=(a,Ball('1',Vec2(.4+2*r-5e-11,.5)))
    assert simulate(touching).status=='stopped'
    with pytest.raises(ValueError,match='overlap'):
        simulate((a,replace(touching[1],position=a.position)))
