import errno
from email.message import Message
from io import BytesIO
import json
import pytest

from billiards import webapp


@pytest.mark.parametrize(('page_version', 'table', 'http_status', 'ready'), [
    (webapp.APP_VERSION, True, 200, True),
    ('previous', True, 200, False),
    (webapp.APP_VERSION, False, 200, False),
    (webapp.APP_VERSION, True, 404, False),
])
def test_health_and_the_served_room_must_both_match(monkeypatch, page_version, table, http_status, ready):
    routes = []
    class Connection:
        def request(self, method, path):
            assert method == 'GET'
            routes.append(path)
        def getresponse(self):
            if routes[-1] == '/api/health':
                reply = BytesIO(json.dumps({'status':'ok','app_version':webapp.APP_VERSION}).encode())
                reply.status = 200
            else:
                body = f'<meta content="{page_version}" name="arena-version">'
                if table:
                    body += '<div id="room-stage"></div>'
                reply = BytesIO(body.encode())
                reply.status = http_status
                reply.headers = Message()
                reply.headers['Content-Type'] = 'text/html; charset=utf-8'
            return reply
        def close(self):
            pass
    monkeypatch.setattr(webapp, 'HTTPConnection', lambda *a, **k: Connection())
    assert webapp.running_version(8766) == (webapp.APP_VERSION if ready else '')
    assert routes == ['/api/health','/']


def test_old_version_in_preferred_port_is_not_reused_or_stopped(monkeypatch):
    opened=[];attempts=[];new_server=object()
    monkeypatch.setattr('webbrowser.open',opened.append)
    monkeypatch.setattr(webapp,'running_version',lambda port:'old-version' if port==8766 else None)
    def create(port):
        attempts.append(port)
        if port==8766:raise OSError(errno.EADDRINUSE,'occupied')
        return new_server
    monkeypatch.setattr(webapp,'create_server',create)
    assert webapp.launch_server(8766,True) is new_server
    assert attempts==[8767] and not opened


def test_launcher_finds_current_version_near_old_server_without_duplicate(monkeypatch):
    opened=[]
    monkeypatch.setattr('webbrowser.open',opened.append)
    monkeypatch.setattr(webapp,'running_version',lambda port:webapp.APP_VERSION if port==8768 else 'old-version')
    monkeypatch.setattr(webapp,'create_server',lambda _:pytest.fail('Existing current service must be reused'))
    assert webapp.launch_server(8766,True) is None
    assert opened==['http://127.0.0.1:8768/']


def test_unrelated_bind_failure_is_not_swallowed_as_port_collision(monkeypatch):
    monkeypatch.setattr(webapp,'running_version',lambda _:None)
    def denied(_):raise PermissionError(errno.EACCES,'denied')
    monkeypatch.setattr(webapp,'create_server',denied)
    with pytest.raises(PermissionError):webapp.launch_server(8766,True)


def test_plain_server_keeps_explicit_port_and_skips_browser_discovery(monkeypatch):
    created=[];server=object()
    monkeypatch.setattr(webapp,'running_version',lambda _:pytest.fail('No browser requested'))
    monkeypatch.setattr(webapp,'create_server',lambda port:(created.append(port) or server))
    assert webapp.launch_server(8766,False) is server and created==[8766]


def test_all_nearby_ports_busy_has_a_bounded_clear_error(monkeypatch):
    attempts=[]
    monkeypatch.setattr(webapp,'running_version',lambda _:None)
    def occupied(port):attempts.append(port);raise OSError(errno.EADDRINUSE,'occupied')
    monkeypatch.setattr(webapp,'create_server',occupied)
    with pytest.raises(ValueError,match='附近端口均被占用'):webapp.launch_server(65534,True)
    assert attempts==[65534,65535]


def test_second_live_listener_cannot_bind_the_same_address():
    # A real Windows regression: HTTPServer's default address reuse previously
    # let a new service report "started" while browsers still reached the old one.
    first=webapp.LocalHTTPServer(('127.0.0.1',0),webapp.BaseHTTPRequestHandler)
    try:
        with pytest.raises(OSError):webapp.LocalHTTPServer(first.server_address,webapp.BaseHTTPRequestHandler)
    finally:first.server_close()
