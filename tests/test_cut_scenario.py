"""05 must use exactly the same shared resolver for BOTH balls as 06."""

from dataclasses import replace
from unittest.mock import patch

import pytest

from billiards import simulate
from billiards.cushion import resolve_cushion
from billiards.diagnostics import cushion_observations
from billiards.scenarios import acceptance_scenes


def scenario(id):
    return next(s for s in acceptance_scenes() if s["id"]==id)


def test_05_and_06_use_identical_cushion_configuration():
    a,b = scenario("cut"),scenario("rail")
    assert a["physics"] == b["physics"]
    assert a["physics"].cushion_model == "coupled_impulse"


def test_every_05_wall_contact_calls_the_shared_resolver_for_each_ball():
    s = scenario("cut")
    with patch("billiards.engine.resolve_cushion",wraps=resolve_cushion) as shared:
        r = simulate(s["balls"],s["table"],s["physics"])
    events = [e for e in r.events if e.kind=="ball_cushion"]
    assert r.status == "stopped"
    assert shared.call_count == len(events) == 3
    assert {(e.actors[0],e.detail) for e in events} == {
        ("cue","bottom"),("1","top"),("cue","right")}
    for event,call in zip(events,shared.call_args_list):
        b = next(b for b in event.before if b.id==event.actors[0])
        expected = resolve_cushion(b,event.detail,s["table"],s["physics"])
        actual = next(b for b in event.after if b.id==event.actors[0])
        assert call.args[0] == b
        assert actual == expected
        assert actual.omega != b.omega
        assert actual.energy <= b.energy+1e-12


def test_05_ideal_limit_reflects_both_balls_with_equal_angles():
    s = scenario("cut_mirror")
    r = simulate(s["balls"],s["table"],s["physics"],max_time=s["max_time"])
    rows = cushion_observations(r)
    assert {row["ball"] for row in rows} == {"cue","1"}
    assert len(rows) == 2
    for row in rows:
        assert row["incident_deg"] == pytest.approx(row["immediate_deg"],abs=1e-10)
    for event in r.events:
        assert all(b.omega.x==b.omega.y==b.omega.z==0 for b in event.after)


def test_05_low_speed_impacts_converge_for_both_balls():
    s = scenario("cut")
    states = []
    for steps in (512,2048):
        r = simulate(s["balls"],s["table"],replace(s["physics"],cushion_steps=steps))
        states.append({(e.actors[0],e.detail):next(b for b in e.after if b.id==e.actors[0])
                       for e in r.events if e.kind=="ball_cushion"})
    assert states[0].keys() == states[1].keys()
    for key in states[0]:
        assert (states[0][key].velocity-states[1][key].velocity).norm() < 3e-4

