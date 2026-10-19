from copy import deepcopy
from http.client import HTTPConnection
import json
import threading

import pytest

from billiards.play import PlayService
from billiards.webapp import create_server


@pytest.fixture(scope='module')
def service():
    return PlayService()


@pytest.mark.parametrize('preset_id',['corner','side','draw','follow','cushion','speed','free'])
def test_each_playable_preset_finishes_using_the_shared_engine(service,preset_id):
    scene = next(preset['scene'] for preset in service.presets() if preset['id']==preset_id)
    original = deepcopy(scene)
    response = service.shoot(scene)
    assert response['complete']
    assert response['result']['status'] == 'stopped'
    assert scene == original
    service.decode(response['next_scene'])
    if preset_id in ('corner','side'):
        assert response['summary']['potted'] == ['1']
        assert not response['summary']['scratch']


def test_scene_save_import_reproduces_the_whole_shot(service):
    scene = service.presets()[0]['scene']
    first = service.shoot(scene)
    imported = service.validate(json.loads(json.dumps(first['snapshot'])))['scene']
    second = service.shoot(imported)
    assert first['result'] == second['result']
    assert first['next_scene'] == second['next_scene']


def test_ball_list_order_does_not_change_first_contact_or_physical_result(service):
    scene = deepcopy(service.presets()[0]['scene'])
    first = service.shoot(scene)
    scene['balls'].reverse()
    second = service.shoot(scene)
    assert first['summary']['first_contact'] == second['summary']['first_contact'] == '1'
    expected = {ball['id']:ball for ball in first['result']['final']}
    actual = {ball['id']:ball for ball in second['result']['final']}
    for identifier in expected:
        assert actual[identifier]['pocket'] == expected[identifier]['pocket']
        assert actual[identifier]['position']['x'] == pytest.approx(expected[identifier]['position']['x'])
        assert actual[identifier]['position']['y'] == pytest.approx(expected[identifier]['position']['y'])


def test_white_ball_scratch_and_respot_allow_a_subsequent_shot(service):
    scene = deepcopy(service.presets()[0]['scene'])
    scene['balls'] = scene['balls'][:1]
    scene['balls'][0]['position'] = {'x':service.table.length/2,'y':.3}
    scene['shot'].update(angle_deg=270,cue_speed=.6,tip_x=0,tip_y=.4)
    response = service.shoot(scene)
    assert response['summary']['scratch']
    assert response['result']['final'][0]['pocket'] == 'bottom-middle'
    with pytest.raises(ValueError,match='白球已落袋'):
        service.shoot(response['next_scene'])
    respotted = deepcopy(response['next_scene'])
    respotted['balls'][0].update(position={'x':.5,'y':.5},pocket=None)
    assert service.shoot(respotted)['complete']


def test_scene_supports_sixteen_separate_balls(service):
    scene = deepcopy(service.presets()[0]['scene'])
    cue = scene['balls'][0]
    cue['position'] = {'x':.4,'y':.55}
    target = scene['balls'][1]
    scene['balls'] = [cue]
    for number in range(1,16):
        ball = deepcopy(target)
        ball['id'] = str(number)
        ball['position'] = {'x':.9+((number-1)%5)*.32,'y':.25+((number-1)//5)*.3}
        scene['balls'].append(ball)
    scene['shot'].update(angle_deg=0,cue_speed=.1,tip_x=0,tip_y=0)
    response = service.shoot(scene)
    assert response['complete']
    assert len(response['result']['final']) == 16


@pytest.mark.parametrize('change',['overlap','version','spec','duplicate','tip','too_many','nonfinite'])
def test_invalid_scenes_are_rejected_before_simulation(service,change):
    scene = deepcopy(service.presets()[0]['scene'])
    if change=='overlap':
        scene['balls'][1]['position'] = deepcopy(scene['balls'][0]['position'])
    elif change=='version':
        scene['physics']['cushion_restitution'] = .8
    elif change=='spec':
        scene['balls'][0]['spec']['radius'] = .1
    elif change=='duplicate':
        scene['balls'][1]['id'] = 'cue'
    elif change=='tip':
        scene['shot'].update(tip_x=.5,tip_y=.5)
    elif change=='too_many':
        scene['balls'] *= 9
    elif change=='nonfinite':
        scene['balls'][0]['position']['x'] = float('nan')
    with pytest.raises(ValueError):
        service.shoot(scene)


def test_unsupported_contact_is_reported_without_a_fake_next_scene(service):
    scene = deepcopy(service.presets()[0]['scene'])
    radius = service.ball_spec.radius
    scene['balls'][0]['position'] = {'x':.5,'y':.5}
    scene['balls'][1]['position'] = {'x':.7,'y':.5}
    neighbor = deepcopy(scene['balls'][1])
    neighbor['id'] = '2'
    neighbor['position']['x'] += 2*radius
    scene['balls'].append(neighbor)
    scene['shot'].update(angle_deg=0,tip_x=0,tip_y=0,cue_speed=1)
    response = service.shoot(scene)
    assert response['result']['status'] == 'unsupported_coupled_contact'
    assert not response['complete']
    assert response['next_scene'] is None


@pytest.fixture(scope='module')
def server():
    server = create_server(0)
    worker = threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    yield server
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def request(server,method,path,body=None,extra_headers=None):
    connection = HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
    headers = {'Content-Type':'application/json'}
    headers.update(extra_headers or {})
    connection.request(method,path,body=body,headers=headers)
    response = connection.getresponse()
    status,content_type,payload = response.status,response.getheader('Content-Type'),response.read()
    connection.close()
    return status,content_type,payload


def test_local_api_serves_ui_config_and_a_real_shot(server,service):
    status,content_type,body = request(server,'GET','/')
    assert status==200 and content_type.startswith('text/html')
    assert '中八练习台' in body.decode('utf-8')
    status,_,body = request(server,'GET','/api/config')
    assert status==200
    config = json.loads(body)
    assert len(config['geometry']['pockets']) == 6
    status,_,body = request(server,'POST','/api/shot',json.dumps(config['presets'][0]['scene']).encode())
    assert status==200
    assert json.loads(body)['summary']['potted'] == ['1']


def test_api_rejects_bad_payloads_and_cross_origin_requests(server,service):
    body = json.dumps(service.presets()[0]['scene']).encode()
    assert request(server,'POST','/api/shot',body,{'Origin':'https://example.com'})[0]==403
    assert request(server,'POST','/api/shot',b'x'*65537)[0]==413
    assert request(server,'POST','/api/shot',b'{"value":NaN}')[0]==400
    assert request(server,'POST','/api/shot',b'{}',{'Content-Type':'text/plain'})[0]==415
    assert request(server,'GET','/.git/config')[0]==404
    assert request(server,'GET','/assets/../../configs/physics_profiles.json')[0]==404


def test_launcher_reuses_its_existing_server_without_starting_a_second_one(server,monkeypatch):
    from billiards.webapp import main
    opened = []
    port = server.server_address[1]
    monkeypatch.setattr('sys.argv',['billiards.webapp','--port',str(port),'--open'])
    monkeypatch.setattr('webbrowser.open',opened.append)
    main()
    assert opened == [f'http://127.0.0.1:{port}/']
