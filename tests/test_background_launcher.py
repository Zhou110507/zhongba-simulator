from types import SimpleNamespace
import os
import subprocess

import pytest

from billiards import launcher


def test_existing_current_service_is_reused_without_spawning(monkeypatch):
    monkeypatch.setattr(launcher,'running_version',lambda p:launcher.APP_VERSION if p==8767 else 'old')
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda *a,**k:pytest.fail('Do not start another current service'))
    assert launcher.ensure_running()=='http://127.0.0.1:8767/'


def test_new_service_uses_independent_group_and_file_logs(monkeypatch,tmp_path):
    calls=[];started=[]
    monkeypatch.setattr(launcher,'ROOT',tmp_path)
    def version(p):return launcher.APP_VERSION if started and p==8767 else 'old' if p==8766 else None
    monkeypatch.setattr(launcher,'running_version',version)
    def spawn(argv,**kwargs):
        calls.append((argv,kwargs));started.append(True)
        return SimpleNamespace(poll=lambda:None)
    monkeypatch.setattr(launcher.subprocess,'Popen',spawn)
    assert launcher.ensure_running()=='http://127.0.0.1:8767/'
    argv,options=calls[0]
    assert argv==[launcher.sys.executable,'-m','billiards.webapp','--port','8767']
    assert options['stdin']==subprocess.DEVNULL and options['stdout'] is options['stderr']
    assert options['stdout'].name==str(tmp_path/'artifacts/local-service-8767.log')
    assert options['stdout'].closed and options['close_fds']
    if os.name=='nt':assert options['creationflags']&subprocess.CREATE_NO_WINDOW and options['creationflags']&subprocess.CREATE_NEW_PROCESS_GROUP
    else:assert options['start_new_session']


def test_failed_child_can_try_the_next_port_without_stopping_existing_services(monkeypatch,tmp_path):
    attempts=[]
    monkeypatch.setattr(launcher,'ROOT',tmp_path)
    monkeypatch.setattr(launcher,'running_version',lambda p:launcher.APP_VERSION if len(attempts)==2 and p==8768 else 'old' if p==8766 else None)
    def spawn(argv,**kwargs):
        attempts.append(argv[-1]);failed=len(attempts)==1
        return SimpleNamespace(poll=lambda:1 if failed else None)
    monkeypatch.setattr(launcher.subprocess,'Popen',spawn)
    assert launcher.ensure_running()=='http://127.0.0.1:8768/' and attempts==['8767','8768']


def test_startup_timeout_reports_log_and_cleans_only_its_own_child(monkeypatch,tmp_path):
    stopped=[];clock=iter([0.,2.])
    monkeypatch.setattr(launcher,'ROOT',tmp_path)
    monkeypatch.setattr(launcher,'running_version',lambda _:None)
    monkeypatch.setattr(launcher,'monotonic',lambda:next(clock))
    child=SimpleNamespace(poll=lambda:None,terminate=lambda:stopped.append('terminate'),wait=lambda **k:stopped.append('wait'))
    monkeypatch.setattr(launcher.subprocess,'Popen',lambda *a,**k:child)
    with pytest.raises(RuntimeError,match='local-service-8766.log'):launcher.ensure_running(timeout=1)
    assert stopped==['terminate','wait']


def test_launcher_opens_browser_only_after_service_is_ready(monkeypatch):
    events=[]
    monkeypatch.setattr(launcher.sys,'argv',['billiards.launcher'])
    monkeypatch.setattr(launcher,'ensure_running',lambda port:(events.append('ready') or 'http://127.0.0.1:8767/'))
    monkeypatch.setattr(launcher.webbrowser,'open',lambda url:events.append(url))
    launcher.main()
    assert events==['ready','http://127.0.0.1:8767/']


def test_no_open_launch_can_verify_service_without_opening_a_browser(monkeypatch):
    monkeypatch.setattr(launcher.sys,'argv',['billiards.launcher','--port','8787','--no-open'])
    monkeypatch.setattr(launcher,'ensure_running',lambda port:'http://127.0.0.1:'+str(port)+'/')
    monkeypatch.setattr(launcher.webbrowser,'open',lambda _:pytest.fail('No browser requested'))
    launcher.main()
