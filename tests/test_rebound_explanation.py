import json
from pathlib import Path

import pytest

from billiards import Ball, BallSpec, Physics, Table, Vec2, Vec3, simulate
from billiards.cushion import resolve_cushion
from billiards.diagnostics import first_cushion_explanation
from billiards.scenarios import acceptance_scenes

REFERENCE = json.loads((Path(__file__).parent/'fixtures'/'mathavan_reference.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',REFERENCE['cases'],ids=lambda case:case['id'])
def test_cushion_agrees_with_independent_mathavan_reference(case):
    state = case['incoming']
    ball = Ball(state['id'],Vec2(**state['position']),Vec2(**state['velocity']),
                Vec3(**state['omega']),BallSpec(**state['spec']))
    physics = Physics(cushion_restitution=case['energetic_restitution'],cushion_steps=4096)
    actual = resolve_cushion(ball,'bottom',Table(),physics)
    expected_velocity = Vec2(**case['expected_velocity'])
    assert (actual.velocity-expected_velocity).norm() < 5e-5
    for axis in ('x','y','z'):
        assert getattr(actual.omega,axis) == pytest.approx(case['expected_omega'][axis],abs=.005)


def explanation():
    scene = next(scene for scene in acceptance_scenes() if scene['id']=='cut')
    result = simulate(scene['balls'],scene['table'],scene['physics'])
    return first_cushion_explanation(result)


def test_no_side_spin_control_does_not_remove_rolling_spin():
    cases = {case['id']:case for case in explanation()['cases']}
    current = cases['current']
    assert current['incoming']['omega']['z'] == 0
    assert current['incoming']['omega']['x'] != 0
    assert cases['no_side']['outgoing'] == current['outgoing']
    assert cases['no_side']['rolling'] == current['rolling']
    assert cases['no_rotation']['incoming']['velocity'] == current['incoming']['velocity']
    assert cases['no_rotation']['outgoing'] != current['outgoing']


def test_rebound_recovery_matches_analytic_slip_impulse():
    for case in explanation()['cases']:
        velocity = Vec2(**case['outgoing']['velocity'])
        slip = Vec2(**case['slip_after'])
        actual = Vec2(**case['rolling']['velocity'])
        assert (actual-(velocity-slip*(2/7))).norm() < 1e-12
        assert case['recovery_time_s'] > 0
        assert case['recovery_distance_m'] > 0
