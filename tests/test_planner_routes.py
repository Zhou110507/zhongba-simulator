from copy import deepcopy
from dataclasses import replace
from math import atan2, degrees, hypot

import pytest

from billiards.cue import ShotInput, strike
from billiards.engine import simulate
from billiards.planner import assess, decode_request, solve
from billiards.planner_examples import example
from billiards.planner_routes import image, prefix_rejector, routes_for, rail_name
from billiards.model import Vec2
from billiards.play import PlayService


@pytest.fixture(scope='module')
def service(): return PlayService()


def run_reference(service, request, angle=49.04130758538965):
    shot = ShotInput(angle, 1.8, 0, .35)
    initial = tuple(strike(b, shot, service.cue) if b.id == 'cue' else b for b in request.balls)
    return simulate(initial, service.table, service.physics)


@pytest.mark.parametrize('kind', ['one_bank', 'two_bank'])
def test_banked_solutions_avoid_blocker_and_replay_with_the_same_engine(service, kind):
    data = example(service, kind); data.update(seconds=30, evaluations=700)
    original = deepcopy(data); request = decode_request(service, data)
    assert request.shot.angle_deg == 0  # Starting aim does not contain the answer.
    result = solve(service, request)
    assert result['status'] == 'found' and result['evaluations'] <= 700
    assert data == original and any(v['inside'] for v in result['solutions'])
    assert result['performance']['route_families'] == 1
    assert sum(result['performance']['search_evaluations'].values()) < result['evaluations']
    for value in result['solutions']:
        scene = deepcopy(data['scene']); scene['shot'] = value['shot']
        replay = service.shoot(scene, compact=True)
        assert replay['complete'] and not replay['summary']['scratch']
        assert replay['summary']['first_contact'] == '1'
        assert not any(e['kind'] == 'ball_ball' and 'cue' in e['actors'] and '2' in e['actors'] for e in replay['result']['events'])
        final = next(b for b in replay['result']['final'] if b['id'] == 'cue')
        assert final['position']['x'] == pytest.approx(value['cue_final']['x'], abs=1e-10)
        assert final['position']['y'] == pytest.approx(value['cue_final']['y'], abs=1e-10)
        assert tuple(value['approach_rails']) == (('top',) if kind == 'one_bank' else ('top', 'right'))
        trials = value['perturbations'] or []
        assert len(trials) <= 8
        assert value['stability_complete'] == (len(trials) == 8)
        if trials:
            assert any(t['tip_x_delta'] or t['tip_y_delta'] for t in trials)
            assert value['stability_passed'] == sum(t['inside'] for t in trials)
        assert value['verified']
    for i, a in enumerate(result['solutions']):
        for b in result['solutions'][i+1:]:
            av, bv = a['shot'], b['shot']
            assert abs(av['cue_speed']-bv['cue_speed']) >= .2-1e-10 or hypot(av['tip_x']-bv['tip_x'], av['tip_y']-bv['tip_y']) >= .08-1e-10 or abs(((av['angle_deg']-bv['angle_deg']+180) % 360)-180) >= .15-1e-10


def test_actual_route_and_post_count_are_hard_conditions_at_the_same_goal(service):
    request = decode_request(service, example(service, 'one_bank'))
    result = run_reference(service, request)
    goal = next(b for b in result.final if b.id == 'cue').position
    request = replace(request, goal=goal)
    valid = assess(result, request, ('top',))
    assert valid['inside'] and valid['approach_rails'] == ('top',)
    assert valid['departure_rails'] == ('right', 'bottom')
    assert assess(result, replace(request, post_banks=2), ('top',))['inside']
    for invalid in (replace(request, first_rail='bottom'), replace(request, post_banks=1), replace(request, max_cushions=2)):
        value = assess(result, invalid, ('top',))
        assert value['error_m'] == 0 and not value['valid'] and not value['inside']
    assert not assess(result, request, ('bottom',))['valid']


def test_prefix_pruning_only_aborts_irrecoverably_invalid_routes(service):
    request = decode_request(service, example(service, 'one_bank'))
    shot = ShotInput(49.04130758538965, 1.8, 0, .35)
    balls = tuple(strike(b, shot, service.cue) if b.id == 'cue' else b for b in request.balls)
    full = simulate(balls, service.table, service.physics)
    checked = simulate(balls, service.table, service.physics, reject_events=prefix_rejector(request, ('top',)))
    assert full.status == checked.status == 'stopped'
    assert full.final == checked.final and full.events == checked.events
    rejected = simulate(balls, service.table, service.physics, reject_events=prefix_rejector(request, ('bottom',)))
    assert rejected.status == 'constraint_rejected' and rejected.duration < full.duration
    assert not assess(rejected, request, ('bottom',))['valid']


def test_geometric_blocker_is_not_removed_for_a_straight_attempt(service):
    request = decode_request(service, example(service, 'one_bank'))
    direct = replace(request, approach='direct', first_rail='any')
    route = routes_for(service, direct)[0]
    assert route.clearance < 0
    assert routes_for(service, request)[0].clearance > 0
    delta = request.balls[1].position-request.balls[0].position
    shot = ShotInput(degrees(atan2(delta.y, delta.x)), 1.8)
    balls = tuple(strike(b, shot, service.cue) if b.id == 'cue' else b for b in request.balls)
    result = simulate(balls, service.table, service.physics)
    first = next(e for e in result.events if e.kind == 'ball_ball' and 'cue' in e.actors)
    assert '2' in first.actors and not assess(result, direct)['valid']


def test_auto_enumerates_route_families_and_respects_explicit_rail_constraints(service):
    request = decode_request(service, example(service, 'one_bank'))
    auto = replace(request, approach='auto', first_rail='any')
    routes = routes_for(service, auto)
    assert {len(r.rails) for r in routes} == {0, 1, 2}
    assert len({r.rails for r in routes}) == len(routes)
    assert all(not r.rails or r.rails[0] != r.rails[-1] or len(r.rails) == 1 for r in routes)
    assert all(r.rails and r.rails[0] == 'top' for r in routes_for(service, replace(auto, first_rail='top')))
    assert all(r.rails == ('top', 'right') for r in routes_for(service, replace(auto, first_rail='top', second_rail='right')))
    assert all(not r.rails for r in routes_for(service, replace(auto, max_cushions=0)))
    assert rail_name('top-left') == 'top' and rail_name('jaw:top-left:1') == 'jaw'
    assert image(Vec2(1, .5), ('top', 'bottom'), (0, 2, 0, 1)) == Vec2(1, 2.5)


@pytest.mark.parametrize('change', [
    {'approach':[]}, {'approach':'three_bank'}, {'first_rail':[]}, {'second_rail':'bogus'},
    {'approach':'direct','first_rail':'top'}, {'second_rail':'left'},
    {'approach':'two_bank','first_rail':'top','second_rail':'top'},
    {'post_banks':True}, {'post_banks':-1}, {'post_banks':5}, {'post_banks':1.5},
    {'max_cushions':0}, {'post_banks':4}, {'stability':'guess'},
    {'approach':'auto','max_cushions':0},
    {'approach':'auto','second_rail':'right','max_cushions':1},
])
def test_invalid_or_conflicting_route_constraints_are_rejected(service, change):
    data = example(service, 'one_bank'); data.update(change)
    with pytest.raises(ValueError): decode_request(service, data)
