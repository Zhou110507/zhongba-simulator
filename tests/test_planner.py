from copy import deepcopy
from dataclasses import replace
from threading import BoundedSemaphore, Event
from time import monotonic, sleep

import pytest

from billiards.cue import strike
from billiards.elastic import ElasticCancelled, burst
from billiards.engine import simulate
from billiards.game import free_table
from billiards.model import Ball, Vec2
from billiards.planner import assess, decode_request, solve
from billiards.planner_jobs import PlannerJobs
from billiards.play import PlayService


@pytest.fixture(scope='module')
def service(): return PlayService()


def payload(service, preset='draw', **changes):
    scene = deepcopy(next(p['scene'] for p in service.presets() if p['id'] == preset))
    scene['shot'].update(cue_speed=1., tip_x=0., tip_y=0.)
    return dict(scene=scene, target='1', goal=dict(x=.7, y=.6, radius=.06),
                seconds=30, evaluations=320, max_cushions=0, **changes)


@pytest.mark.parametrize('preset,goal,pocket', [
    ('draw', (.7, .6), None), ('follow', (1.4, .6), None),
    ('corner', (1.6, .5), 'top-right')])
def test_reachable_tasks_from_an_unrelated_initial_shot_are_reverified(service, preset, goal, pocket):
    data = payload(service, preset, pocket=pocket)
    data['goal'].update(x=goal[0], y=goal[1])
    original = deepcopy(data)
    result = solve(service, decode_request(service, data))
    assert data == original
    assert result['status'] == 'found'
    assert result['evaluations'] <= data['evaluations']
    assert result['solutions'][0]['inside']
    for value in result['solutions']:
        assert value['verified'] and value['valid']
        scene = deepcopy(data['scene']); scene['shot'] = value['shot']
        actual = service.shoot(scene, compact=True)
        cue = next(b for b in actual['result']['final'] if b['id'] == 'cue')
        target = next(b for b in actual['result']['final'] if b['id'] == '1')
        assert actual['complete'] and not actual['summary']['scratch']
        assert actual['summary']['first_contact'] == '1'
        assert cue['position']['x'] == pytest.approx(value['cue_final']['x'], abs=1e-10)
        assert cue['position']['y'] == pytest.approx(value['cue_final']['y'], abs=1e-10)
        if pocket: assert target['pocket'] == pocket


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(target='cue'), lambda d: d.update(target='16'),
    lambda d: d.update(pocket=[]), lambda d: d.update(pocket='bogus'),
    lambda d: d['goal'].update(x=float('nan')), lambda d: d['goal'].update(x=True),
    lambda d: d['goal'].update(x=-1), lambda d: d['goal'].update(radius=.001),
    lambda d: d.update(seconds=True), lambda d: d.update(evaluations=True),
    lambda d: d.update(max_cushions=True), lambda d: d.update(allow_other='yes'),
    lambda d: d['scene']['balls'].pop(),
    lambda d: d['scene']['balls'][0].update(pocket='top-right'),
])
def test_invalid_or_missing_task_is_rejected_before_start(service, mutate):
    data = payload(service); mutate(data)
    with pytest.raises(ValueError): decode_request(service, data)


def test_goal_cannot_be_in_a_pocket_but_may_coincide_with_a_movable_ball(service):
    data = payload(service)
    data['goal'].update(x=1.2, y=.6)
    assert decode_request(service, data).goal == Vec2(1.2, .6)
    data['goal'].update(x=1.27, y=0)
    with pytest.raises(ValueError): decode_request(service, data)


def test_full_fifteen_ball_scene_is_not_replaced_with_two_balls(service, monkeypatch):
    scene = free_table(service, dict(balls=[str(i) for i in range(1, 16)], cue=dict(x=.4, y=.5), seed=4))['scene']
    data = payload(service); data.update(scene=scene, evaluations=12)
    import billiards.planner as module
    forward = module.simulate; seen = []
    def inspect(balls, *args, **kwargs):
        seen.append(tuple(b.id for b in balls))
        return forward(balls, *args, **kwargs)
    monkeypatch.setattr(module, 'simulate', inspect)
    solve(service, decode_request(service, data))
    assert seen and all(set(ids) == {'cue', *(str(i) for i in range(1, 16))} for ids in seen)


def test_blocking_ball_is_a_hard_failure_even_at_exact_goal(service):
    data = payload(service)
    data['scene']['balls'].append(deepcopy(data['scene']['balls'][1]))
    data['scene']['balls'][-1].update(id='2', position=dict(x=.8, y=.6))
    request = decode_request(service, data)
    shot = replace(request.shot, angle_deg=0, cue_speed=1.4)
    balls = tuple(strike(b, shot, service.cue) if b.id == 'cue' else b for b in request.balls)
    actual = simulate(balls, service.table, service.physics)
    final = next(b for b in actual.final if b.id == 'cue').position
    assessment = assess(actual, replace(request, goal=final))
    assert assessment['error_m'] == 0 and not assessment['valid'] and not assessment['inside']
    assert '首次触球不是指定目标球' in assessment['reasons']


def test_no_solution_in_tiny_budget_is_not_reported_unreachable(service):
    data = payload(service, pocket='bottom-left'); data.update(evaluations=12)
    result = solve(service, decode_request(service, data))
    assert result['status'] == 'not_found'
    assert result['solutions'] == []
    assert 'no reachability proof' in result['scope']


def test_cancelled_search_does_no_forward_work(service):
    result = solve(service, decode_request(service, payload(service)), cancelled=lambda: True)
    assert result['status'] == 'cancelled' and result['evaluations'] == 0 and not result['solutions']


def test_light_recording_preserves_contact_network_physics_and_events(service):
    r = service.ball_spec.radius
    balls = (Ball('cue', Vec2(.4, .6), Vec2(2, 0), spec=service.ball_spec),
             Ball('1', Vec2(.8, .6), spec=service.ball_spec),
             Ball('2', Vec2(.8+2*r, .6), spec=service.ball_spec))
    full = simulate(balls, service.table, service.physics)
    light = simulate(balls, service.table, service.physics, record_segments=False)
    assert full.status == light.status == 'stopped'
    assert full.final == light.final and full.events == light.events and full.duration == light.duration
    assert full.segments and not light.segments
    assert any(e.detail == 'hertz-onset' for e in full.events)
    with pytest.raises(ValueError, match='not recorded'): light.state_at(light.duration/2)


def test_cancellation_during_flight_and_inside_elastic_burst(service):
    balls = (Ball('a', Vec2(.5, .6), Vec2(2, 0)), Ball('b', Vec2(.5+2*service.ball_spec.radius, .6)))
    assert simulate(balls, service.table, service.physics, cancel=lambda: True).status == 'cancelled'
    checks = []
    def cancel():
        checks.append(1)
        return len(checks) > 4
    with pytest.raises(ElasticCancelled): burst(balls, service.physics, cancel=cancel)
    assert len(checks) == 5


def test_job_cancel_releases_capacity_and_retains_completed_status(service, monkeypatch):
    import billiards.planner_jobs as module
    ready = Event()
    def work(s, request, *, cancelled, progress):
        ready.set()
        while not cancelled(): sleep(.001)
        return {'status': 'cancelled', 'solutions': []}
    monkeypatch.setattr(module, 'solve', work)
    slots = BoundedSemaphore(1); manager = PlannerJobs(service, slots)
    first = manager.start(payload(service)); assert ready.wait(1)
    with pytest.raises(ValueError): manager.start(payload(service))
    manager.status(first, cancel=True)
    limit = monotonic()+2
    while manager.status(first)['status'] == 'running' and monotonic() < limit: sleep(.005)
    assert manager.status(first)['status'] == 'cancelled'
    assert slots.acquire(blocking=False); slots.release()
    with pytest.raises(ValueError): manager.status({'id':'missing'})
