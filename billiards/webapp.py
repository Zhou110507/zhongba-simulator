"""Local practice UI and bounded stateless shot API. Run: python -m billiards.webapp."""

import argparse
import errno
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import socket
import threading
from urllib.parse import unquote, urlsplit

from .play import APP_VERSION, PlayService, ROOT

MAX_BODY = 65536


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits two live listeners on the same endpoint.
    # The browser may then keep reaching an older process after an "upgrade".
    allow_reuse_address=not hasattr(socket,'SO_EXCLUSIVEADDRUSE')

    def server_bind(self):
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def reject_constant(value):
    raise ValueError('不允许非有限数值：'+value)


def make_handler(service):
    jobs = threading.BoundedSemaphore(2)
    from .planner_jobs import PlannerJobs
    planners = PlannerJobs(service, jobs)
    rules_service=PlayService(service.root,table_profile='cbsa_2017')
    from .game import GameStore, free_table
    games=GameStore(rules_service,service.root/'artifacts'/'rules'/'matches',compact=True)
    from .ai_jobs import AIJobs
    opponents=AIJobs(games,jobs)

    def scene_service(data):
        if isinstance(data,dict) and data.get('model_signature')==rules_service.signature:
            return rules_service
        return service

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def send_bytes(self, status, body, content_type):
            compressed=len(body)>2048 and 'gzip' in self.headers.get('Accept-Encoding','').lower()
            if compressed:body=gzip.compress(body,compresslevel=1,mtime=0)
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Vary','Accept-Encoding')
            if compressed:self.send_header('Content-Encoding','gzip')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status, data):
            body = json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
            self.send_bytes(status,body,'application/json; charset=utf-8')

        def valid_host(self):
            host = self.headers.get('Host','')
            port = self.server.server_address[1]
            return host in (f'127.0.0.1:{port}',f'localhost:{port}')

        def do_GET(self):
            if not self.valid_host():
                self.send_json(403,{'error':'仅允许本机访问'})
                return
            path = unquote(urlsplit(self.path).path)
            if path=='/api/config':
                self.send_json(200,service.config())
                return
            if path=='/api/rules/config':
                self.send_json(200,rules_service.config())
                return
            if path=='/api/health':
                self.send_json(200,{'status':'ok','app_version':APP_VERSION})
                return
            if path in ('/','/play','/play/'):
                target = service.root/'web'/'index.html'
            elif path=='/lab':
                target = service.root/'web'/'lab.html'
            elif path.startswith('/assets/'):
                base = (service.root/'web').resolve()
                target = (base/path.removeprefix('/assets/')).resolve()
                if not target.is_relative_to(base):
                    self.send_json(404,{'error':'找不到文件'})
                    return
            elif path.startswith('/artifacts/phase-a/') and path.endswith('.html'):
                base = (service.root/'artifacts'/'phase-a').resolve()
                target = (service.root/path.lstrip('/')).resolve()
                if not target.is_relative_to(base):
                    self.send_json(404,{'error':'找不到文件'})
                    return
            else:
                self.send_json(404,{'error':'找不到页面'})
                return
            if not target.is_file():
                self.send_json(404,{'error':'找不到页面文件'})
                return
            content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            self.send_bytes(200,target.read_bytes(),content_type+'; charset=utf-8')

        def do_POST(self):
            self.close_connection = True
            origin = self.headers.get('Origin')
            allowed_origin = {f'http://127.0.0.1:{self.server.server_address[1]}',
                              f'http://localhost:{self.server.server_address[1]}'}
            if not self.valid_host() or (origin is not None and origin not in allowed_origin):
                self.send_json(403,{'error':'仅接受本机练习页面的请求'})
                return
            path = urlsplit(self.path).path
            if path not in ('/api/validate','/api/shot','/api/lab','/api/calibration','/api/free-table',
                            '/api/game/new','/api/game/get','/api/game/action','/api/game/preview',
                            '/api/ai/start','/api/ai/status','/api/ai/cancel','/api/ai/execute','/api/ai/layout',
                            '/api/plan/start','/api/plan/status','/api/plan/cancel','/api/plan/example'):
                self.send_json(404,{'error':'未知接口'})
                return
            if self.headers.get_content_type() != 'application/json':
                self.send_json(415,{'error':'需要 JSON 场景数据'})
                return
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= MAX_BODY:
                    self.send_json(413,{'error':'场景数据为空或超过 64 KB'})
                    return
                data = json.loads(self.rfile.read(length).decode('utf-8'),parse_constant=reject_constant)
                # Control requests must remain available while a worker holds a CPU slot.
                if path.startswith('/api/plan/'):
                    if path.endswith('/example'):
                        from .planner_examples import example
                        response = example(service, data.get('kind') if isinstance(data, dict) else None)
                    else:
                        response = planners.start(data) if path.endswith('/start') else planners.status(data, cancel=path.endswith('/cancel'))
                    self.send_json(200, response)
                    return
                if path.startswith('/api/ai/') and not path.endswith('/execute'):
                    if path.endswith('/layout'):
                        balls,shot=scene_service(data).decode(data)
                        response=rules_service.validate(rules_service.snapshot(balls,shot))
                    else:
                        response=opponents.start(data) if path.endswith('/start') else opponents.status(data,cancel=path.endswith('/cancel'))
                    self.send_json(200,response)
                    return
                if not jobs.acquire(blocking=False):
                    self.send_json(503,{'error':'计算繁忙，请稍后重试'})
                    return
                try:
                    if path=='/api/ai/execute':
                        response=opponents.execute(data)
                    elif path.startswith('/api/game/'):
                        response={'/api/game/new':games.new,'/api/game/get':games.get,
                                  '/api/game/action':games.action,'/api/game/preview':games.preview}[path](data)
                    elif path=='/api/free-table':
                        response=free_table(service,data)
                    elif path=='/api/lab':
                        from .physics_lab import run_experiment
                        response=run_experiment(service,data)
                    elif path=='/api/calibration':
                        from .calibration import fit_measurements
                        response=fit_measurements(data)
                    else:
                        selected=scene_service(data)
                        response = selected.shoot(data,compact=self.headers.get('X-Billiards-Playback')=='1') if path=='/api/shot' else selected.validate(data)
                finally:
                    jobs.release()
                self.send_json(200,response)
            except (ValueError,UnicodeDecodeError) as error:
                self.send_json(400,{'error':str(error)})
            except (BrokenPipeError,ConnectionResetError):
                return
            except Exception:
                import traceback
                traceback.print_exc()
                self.send_json(500,{'error':'计算失败，请查看本地服务日志'})

    return Handler


def create_server(port=8766, root=ROOT):
    service = PlayService(root)
    return LocalHTTPServer(('127.0.0.1',port),make_handler(service))


def running_version(port):
    from http.client import HTTPConnection,HTTPException
    connection=HTTPConnection('127.0.0.1',port,timeout=.25)
    try:
        connection.request('GET','/api/health')
        response=connection.getresponse();data=json.loads(response.read(4096))
        if response.status==200 and isinstance(data,dict) and data.get('status')=='ok':return data.get('app_version')
    except (OSError,ValueError,HTTPException):pass
    finally:connection.close()


def launch_server(port,open_browser):
    # A previous process can serve new HTML from disk with an old API. Reuse
    # only the running version of this code, leaving old services untouched.
    if open_browser and port:
        candidates=range(port,min(65535,port+10)+1)
        versions={candidate:running_version(candidate) for candidate in candidates}
        for candidate in candidates:
            if versions[candidate]==APP_VERSION:
                import webbrowser
                webbrowser.open(f'http://127.0.0.1:{candidate}/')
                return None
        for candidate in candidates:
            if versions[candidate] is not None:continue
            try:return create_server(candidate)
            except OSError as error:
                if error.errno!=errno.EADDRINUSE and getattr(error,'winerror',None)!=10048:raise
        raise ValueError('附近端口均被占用，请使用 --port 指定其他端口')
    return create_server(port)


def main():
    parser = argparse.ArgumentParser(description='Local Chinese eight-ball practice prototype')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--open',action='store_true',dest='open_browser')
    options = parser.parse_args()
    if not 0 <= options.port <= 65535:
        parser.error('port must be between 0 and 65535')
    try:server=launch_server(options.port,options.open_browser)
    except ValueError as error:parser.error(str(error))
    if server is None:return
    with server:
        url = f'http://127.0.0.1:{server.server_address[1]}/'
        print('ZHONGBA practice: '+url,flush=True)
        print('Local service running. Press Ctrl+C to stop.',flush=True)
        if options.open_browser:
            import webbrowser
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__=='__main__':
    main()
