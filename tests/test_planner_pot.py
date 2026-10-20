from copy import deepcopy
from dataclasses import replace

import pytest

from billiards.cue import ShotInput, strike
from billiards.engine import Event, simulate
from billiards.planner import assess, decode_request, solve
from billiards.planner_examples import example
from billiards.planner_pot import recommendation_key
from billiards.planner_routes import prefix_rejector
from billiards.play import PlayService


@pytest.fixture(scope='module')
def normal():
    service = PlayService()
    data = example(service, 'pot_bank')
    request = decode_request(service, data)
    shot = ShotInput(48.5122328657204, 1.4, 0, -.3)
    balls = tuple(strike(b, shot, service.cue) if b.id == 'cue' else b for b in request.balls)
    result = simulate(balls, service.table, service.physics)
    assert assess(result, request, ())['inside']
    return service, data, request, result


def test_normal_search_pots_directly_and_keeps_post_contact_bank(normal):
    service, data, _, _ = normal
    data = deepcopy(data); original = deepcopy(data); data['seconds'] = 30
    response = solve(service, decode_request(service, data))
    assert data == {**original, 'seconds': 30}
    assert response['status'] == 'found' and response['evaluations'] <= 480
    assert response['baseline']['verified']
    assert response['solutions'][0]['inside']
    for value in response['solutions']:
        assert value['verified'] and not value['approach_rails']
        assert value['cue_cushions'] == 1 and len(value['departure_rails']) == 1
        assert value['target_pocket'] == 'top-right' and value['shot']['tip_x'] == 0
        actual = service.shoot({**data['scene'], 'shot': value['shot']}, compact=True)
        cue = next(b for b in actual['result']['final'] if b['id'] == 'cue')
        assert actual['complete'] and actual['summary']['potted'] == ['1']
        assert cue['position'] == pytest.approx(value['cue_final'], abs=1e-10)


@pytest.mark.parametrize('radius', [.06, .08, .1, .12])
def test_goal_overlap_includes_tangency_and_rejects_a_gap(normal, radius):
    _, _, request, result = normal
    cue = next(b for b in result.final if b.id == 'cue')
    reach = radius+cue.spec.radius
    for extra, success in ((-.001, True), (0., True), (.000001, False)):
        goal = cue.position+type(cue.position)(reach+extra, 0)
        metrics = assess(result, replace(request, goal=goal, radius=radius), ())
        assert metrics['valid'] and metrics['inside'] is success
        assert metrics['error_m'] == pytest.approx(reach+extra)
        assert metrics['goal_margin_m'] == pytest.approx(-extra)


@pytest.mark.parametrize('kind', ['pre_bank', 'object_bank', 'second_kiss', 'scratch'])
def test_zero_goal_error_cannot_override_a_failed_pot_constraint(normal, kind):
    _, _, request, result = normal
    contact = next(e for e in result.events if e.kind == 'ball_ball')
    cue = next(b for b in result.final if b.id == 'cue')
    if kind == 'scratch':
        result = replace(result, final=tuple(replace(b, pocket='top-left') if b.id == 'cue' else b for b in result.final))
    else:
        event = Event(contact.time-.001 if kind == 'pre_bank' else contact.time+.001,
                      'ball_ball' if kind == 'second_kiss' else 'ball_cushion',
                      ('cue', '1') if kind == 'second_kiss' else ('cue',) if kind == 'pre_bank' else ('1',),
                      'top', contact.before, contact.after)
        events = tuple(sorted((*result.events, event), key=lambda e: e.time))
        result = replace(result, events=events)
        assert prefix_rejector(request, ())(events)
    metrics = assess(result, replace(request, goal=cue.position), ())
    assert metrics['error_m'] == 0 and not metrics['valid'] and not metrics['inside']


def test_region_satisfied_prefers_fewer_banks_and_less_side_over_centre_error():
    def value(error, banks, side=0):
        return dict(inside=True, error_m=error, cue_cushions=banks,
                    shot=dict(cue_speed=1.4, tip_x=side, tip_y=.15))
    assert recommendation_key(value(.09, 0), .1) < recommendation_key(value(.001, 1), .1)
    assert recommendation_key(value(.09, 1), .1) < recommendation_key(value(.001, 1, .3), .1)


@pytest.mark.parametrize('change', [
    {'strategy': 'wrong'}, {'stroke': []}, {'strategy': 'pot_first', 'pocket': None},
    {'strategy': 'pot_first', 'approach': 'one_bank'},
    {'goal': {'x': 1.2, 'y': .6, 'radius': .07}},
    {'goal': {'x': 1.2, 'y': .6, 'radius': .14}},
])
def test_normal_choices_are_validated_before_search(normal, change):
    service, data, _, _ = normal
    with pytest.raises(ValueError): decode_request(service, {**data, **change})


def test_normal_and_special_are_explicit_and_cancellation_does_no_work(normal):
    service, data, request, _ = normal
    assert request.strategy == 'pot_first' and request.stroke == 'natural'
    special = decode_request(service, example(service, 'one_bank'))
    assert special.strategy == 'position' and special.approach == 'one_bank'
    response = solve(service, request, cancelled=lambda: True)
    assert response['status'] == 'cancelled' and response['evaluations'] == 0 and not response['solutions']
    assert decode_request(service, {**data, 'stroke': 'small_side'}).stroke == 'small_side'
    assert decode_request(service, {**data, 'stroke': 'open'}).stroke == 'open'
