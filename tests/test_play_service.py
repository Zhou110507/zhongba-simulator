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


@pytest.mark.parametrize('preset_id',['corner','side','draw','draw-angle','follow','cushion','speed','free'])
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


def test_touching_neighbors_are_now_supported_by_the_cluster_solver(service):
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
    assert response['result']['status'] == 'stopped'
    assert response['complete'] and response['next_scene'] is not None
    assert any(e['detail']=='hertz-onset' for e in response['result']['events'])
    service.decode(response['next_scene'])


def test_incomplete_simulation_never_returns_a_fake_next_scene(service,monkeypatch):
    from billiards.engine import simulate
    def bounded(*args,**kwargs):
        return simulate(*args,**{**kwargs,'max_events':1})
    monkeypatch.setattr('billiards.play.simulate',bounded)
    response=service.shoot(service.presets()[0]['scene'])
    assert response['result']['status']=='max_events'
    assert not response['complete'] and response['next_scene'] is None


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


def test_ai_http_is_opt_in_cancellable_and_revision_bound(server):
    status,_,body=request(server,'POST','/api/game/new',b'{"seed":0}')
    game=json.loads(body);assert status==200 and game['ai_player'] is None
    data=json.dumps({'id':game['id'],'revision':game['revision']}).encode()
    assert request(server,'POST','/api/ai/start',data)[0]==400
    status,_,body=request(server,'POST','/api/game/new',b'{"scenario":"ai_endgame","seed":0}')
    game=json.loads(body);assert status==200 and game['ai_player']==1 and not game['is_break']
    data=json.dumps({'id':game['id'],'revision':game['revision']}).encode()
    status,_,body=request(server,'POST','/api/ai/start',data)
    assert status==200
    job=json.dumps({'id':json.loads(body)['id']}).encode()
    assert request(server,'POST','/api/ai/cancel',job)[0]==200
    assert request(server,'POST','/api/ai/execute',job)[0]==400
    assert request(server,'POST','/api/ai/status',b'{"id":[]}')[0]==400
    assert request(server,'POST','/api/ai/start',data,{'Origin':'https://example.com'})[0]==403
    status,_,body=request(server,'POST','/api/game/get',json.dumps({'id':game['id']}).encode())
    assert status==200 and json.loads(body)['revision']==0
    assert request(server,'GET','/assets/ai-opponent.js')[0]==200


def test_ai_layout_import_accepts_practice_scenes_without_changing_their_profile(server,service):
    scene=deepcopy(service.presets()[0]['scene']);before=deepcopy(scene)
    status,_,raw=request(server,'POST','/api/ai/layout',json.dumps(scene).encode())
    assert status==200
    converted=json.loads(raw)['scene']
    assert converted['table']['width']==1.27 and scene['table']['width']==1.26
    assert converted['balls']==scene['balls'] and scene==before
    assert request(server,'POST','/api/ai/layout',b'{"kind":"unknown"}')[0]==400


def test_lab_and_calibration_endpoints_keep_profile_state_immutable(server,service):
    original=deepcopy(service.model)
    status,_,body=request(server,'GET','/lab')
    assert status==200 and '旋转与碰撞' in body.decode('utf-8')
    status,_,body=request(server,'GET','/assets/calibration-example.json')
    measurements=json.loads(body)
    assert status==200 and measurements['data_origin']=='synthetic'
    status,_,body=request(server,'POST','/api/lab',json.dumps(dict(kind='ball',speed=1.341,cut=30,follow=0,side=0)).encode())
    assert status==200 and all(v['complete'] for v in json.loads(body)['variants'])
    status,_,body=request(server,'POST','/api/calibration',json.dumps(measurements).encode())
    assert status==200 and json.loads(body)['parameters']['rolling_friction']==pytest.approx(.007)
    assert service.model==original
    for endpoint in ('/api/lab','/api/calibration'):
        status,_,_=request(server,'POST',endpoint,b'{}')
        assert status==400


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


def test_inverse_http_job_can_be_polled_and_cancelled_without_blocking_shots(server,service):
    from time import monotonic, sleep
    data = dict(scene=next(p['scene'] for p in service.presets() if p['id']=='draw'),
                target='1',goal=dict(x=.7,y=.6,radius=.06),seconds=30,evaluations=1000)
    body=json.dumps(data).encode()
    assert request(server,'POST','/api/plan/start',body,{'Origin':'https://example.com'})[0]==403
    assert request(server,'POST','/api/plan/start',b'[]')[0]==400
    status,_,raw=request(server,'POST','/api/plan/start',body)
    value=json.loads(raw);assert status==200 and value['status']=='running'
    job=json.dumps({'id':value['id']}).encode()
    assert request(server,'POST','/api/plan/status',job)[0]==200
    assert request(server,'POST','/api/plan/cancel',job)[0]==200
    deadline=monotonic()+3
    while monotonic()<deadline:
        status,_,raw=request(server,'POST','/api/plan/status',job)
        value=json.loads(raw)
        if value['status']!='running':break
        sleep(.01)
    assert value['status']=='cancelled' and value['result']['solutions']==[]
    assert request(server,'POST','/api/plan/status',b'{"id":"missing"}')[0]==400
    assert request(server,'POST','/api/shot',json.dumps(data['scene']).encode())[0]==200
    for asset in ('planner.js','planner.css'):
        assert request(server,'GET','/assets/'+asset)[0]==200
    for kind in ('one_bank','two_bank'):
        status,_,raw=request(server,'POST','/api/plan/example',json.dumps({'kind':kind}).encode())
        task=json.loads(raw)
        assert status==200 and task['approach']==kind and len(task['scene']['balls'])==3
        assert task['scene']['shot']['angle_deg']==0
    assert request(server,'POST','/api/plan/example',b'[]')[0]==400


def test_rule_and_free_mode_http_contracts(server):
    status,_,body=request(server,'GET','/api/rules/config')
    config=json.loads(body)
    assert status==200 and config['model']['table']['width']==1.27
    status,_,body=request(server,'POST','/api/game/new',b'{"breaker":1}')
    game=json.loads(body)
    assert status==200 and game['turn']==1 and len(game['scene']['balls'])==16
    status,_,body=request(server,'POST','/api/validate',json.dumps(game['scene']).encode())
    assert status==200 and json.loads(body)['scene']['model_signature']==game['scene']['model_signature']
    for name in ('table-modes.js','table-modes.css'):
        assert request(server,'GET','/assets/'+name)[0]==200
    for endpoint in ('new','get','action','preview'):
        assert request(server,'POST','/api/game/'+endpoint,b'[]')[0]==400
    status,_,body=request(server,'POST','/api/free-table',b'{"balls":["3","8","13"],"cue":{"x":0.3,"y":0.4}}')
    value=json.loads(body)
    assert status==200 and [b['id'] for b in value['scene']['balls']]==['cue','3','8','13']
    assert value['scene']['table']['width']==1.26
    assert request(server,'POST','/api/free-table',b'{"balls":["1","1"],"cue":{"x":0.3,"y":0.4}}')[0]==400


def test_compact_playback_and_gzip_transport_keep_exact_final_balls(server,service):
    import gzip
    body=json.dumps(service.presets()[0]['scene']).encode()
    status,_,raw=request(server,'POST','/api/shot',body)
    full=json.loads(raw)
    status,headers,packed=request(server,'POST','/api/shot',body,
        {'X-Billiards-Playback':'1','Accept-Encoding':'gzip'})
    assert status==200
    # Successful decoding also verifies the negotiated compressed response.
    compact=json.loads(gzip.decompress(packed))
    assert compact['result']['detail']=='playback-v2'
    assert compact['result']['final']==full['result']['final']
    assert len(compact['result']['segments'])==len(full['result']['segments'])
    assert compact['result']['segments'][0][:2]==[full['result']['segments'][0][key] for key in ('start','end')]
    assert len(packed)<len(raw)*.3
