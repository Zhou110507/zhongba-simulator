"""Exercise the native launcher after extraction, with a system-Python-free PATH."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from time import sleep
from urllib.request import Request, urlopen


def check(source):
    scratch = Path(tempfile.mkdtemp(prefix='zhongba-portable-'))
    app = scratch/'中八 球房'
    shutil.copytree(source, app)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    # Only Windows is discoverable on PATH. The application must find its own runtime.
    env = dict(os.environ, PATH=str(Path(os.environ['WINDIR'])/'System32'))
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    python = str(app/'runtime'/'python.exe')
    details = json.loads(subprocess.check_output([python, '-X', 'utf8', '-c',
        "import json, numpy, billiards, sys; from billiards.play import APP_VERSION; "
        "print(json.dumps([sys.executable,numpy.__file__,billiards.__file__,APP_VERSION]))"],
        cwd=scratch, env=env, encoding='utf-8'))
    executable, numpy_module, game_module, version = details
    # Normalize both paths because an extracted directory may have a DOS short alias.
    assert Path(executable).samefile(python), details
    assert Path(numpy_module).resolve().is_relative_to((app/'runtime').resolve()), details
    assert Path(game_module).resolve().is_relative_to((app/'billiards').resolve()), details
    command = [str(app/'Zhongba3D.exe'), '--no-open', '--port', str(port)]
    base = f'http://127.0.0.1:{port}'

    def request(path, body=None):
        req = Request(base+path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type':'application/json'})
        with urlopen(req, timeout=15) as result:
            data = result.read()
            return json.loads(data) if result.headers.get_content_type() == 'application/json' else data

    subprocess.run(command, cwd=scratch, env=env, timeout=45, check=True)
    sleep(.35)
    assert request('/api/health')['app_version'] == version
    page = request('/').decode('utf-8')
    assert 'name="arena-version" content="'+version+'"' in page and 'id="room-stage"' in page
    assert b'Arena' in request('/assets/arena.js')
    match = request('/api/game/new', {'race_to':3,'seed':73})
    assert match['race_to'] == 3 and match['scores'] == [0,0]
    subprocess.run(command, cwd=scratch, env=env, timeout=45, check=True)
    assert request('/api/game/get', {'id':match['id']})['id'] == match['id']
    assert [p.name for p in (app/'artifacts').glob('local-service-*.log')] == [f'local-service-{port}.log']
    print(f'Portable launcher exited, reused its background service and restored a game. Version {version}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package',type=Path)
    check(parser.parse_args().package.resolve())
