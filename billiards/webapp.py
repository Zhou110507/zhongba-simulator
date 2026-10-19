"""Local practice UI and bounded stateless shot API. Run: python -m billiards.webapp."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import threading
from urllib.parse import unquote, urlsplit

from .play import PlayService, ROOT

MAX_BODY = 65536


def reject_constant(value):
    raise ValueError('不允许非有限数值：'+value)


def make_handler(service):
    jobs = threading.BoundedSemaphore(2)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type',content_type)
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
            if path=='/api/health':
                self.send_json(200,{'status':'ok','app_version':'phase-b-playable-v1'})
                return
            if path in ('/','/play','/play/'):
                target = service.root/'web'/'index.html'
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
            if path not in ('/api/validate','/api/shot'):
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
                if not jobs.acquire(blocking=False):
                    self.send_json(503,{'error':'计算繁忙，请稍后重试'})
                    return
                try:
                    response = service.shoot(data) if path=='/api/shot' else service.validate(data)
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
    return ThreadingHTTPServer(('127.0.0.1',port),make_handler(service))


def main():
    parser = argparse.ArgumentParser(description='Local Chinese eight-ball practice prototype')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--open',action='store_true',dest='open_browser')
    options = parser.parse_args()
    if not 0 <= options.port <= 65535:
        parser.error('port must be between 0 and 65535')
    if options.open_browser and options.port:
        from http.client import HTTPConnection
        connection = HTTPConnection('127.0.0.1',options.port,timeout=.5)
        try:
            connection.request('GET','/api/health')
            response = connection.getresponse()
            data = json.loads(response.read())
            if response.status==200 and data.get('app_version')=='phase-b-playable-v1':
                import webbrowser
                webbrowser.open(f'http://127.0.0.1:{options.port}/')
                return
        except (OSError,ValueError):
            pass
        finally:
            connection.close()
    with create_server(options.port) as server:
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
