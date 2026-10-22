"""Start or reuse a persistent local service, then open its actual URL."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic,sleep
import webbrowser

from .play import APP_VERSION,ROOT
from .webapp import running_version


def ensure_running(port=8766,*,timeout=20):
    if not 1<=port<=65535:raise ValueError('端口须在 1–65535 之间')
    candidates=range(port,min(65535,port+10)+1)
    versions={p:running_version(p) for p in candidates}
    for p in candidates:
        if versions[p]==APP_VERSION:return f'http://127.0.0.1:{p}/'
    directory=Path(ROOT)/'artifacts';directory.mkdir(parents=True,exist_ok=True)
    options={'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
    for p in candidates:
        if versions[p] is not None:continue
        log=directory/f'local-service-{p}.log'
        with log.open('ab',buffering=0) as output:
            child=subprocess.Popen([sys.executable,'-m','billiards.webapp','--port',str(p)],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=output,stderr=output,close_fds=True,**options)
        deadline=monotonic()+timeout
        while monotonic()<deadline:
            if running_version(p)==APP_VERSION:return f'http://127.0.0.1:{p}/'
            if child.poll() is not None:break
            sleep(.1)
        if child.poll() is None:
            child.terminate();child.wait(timeout=5)
            raise RuntimeError(f'服务未在预期时间内就绪，请查看日志：{log}')
    raise RuntimeError(f'未能启动本地服务，请查看 {directory} 下的 local-service 日志或指定其他端口')


def main():
    parser=argparse.ArgumentParser(description='在独立后台启动中八练习台')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--no-open',action='store_true')
    args=parser.parse_args()
    try:url=ensure_running(args.port)
    except (OSError,ValueError,RuntimeError) as error:parser.exit(1,str(error)+'\n')
    print('中八练习台：'+url,flush=True)
    print('本地服务已在后台运行，关闭启动窗口不影响练习台。',flush=True)
    if not args.no_open:webbrowser.open(url)


if __name__=='__main__':main()
