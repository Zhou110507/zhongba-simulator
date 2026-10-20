"""One cancellable inverse job; shares the forward API's CPU capacity."""
from copy import deepcopy
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from .planner import decode_request, solve


class PlannerJobs:
    def __init__(self, service, slots):
        self.service = service; self.slots = slots; self.lock = Lock(); self.jobs = {}

    def start(self, data):
        request = decode_request(self.service, data)
        with self.lock:
            now = monotonic()
            self.jobs = {k: v for k, v in self.jobs.items() if now-v['created'] < 900 or v['status'] == 'running'}
            if any(v['status'] == 'running' for v in self.jobs.values()):
                raise ValueError('已有走位反算在运行，请先取消或等待完成')
            if not self.slots.acquire(blocking=False):
                raise ValueError('计算繁忙，请稍后重试')
            while len(self.jobs) >= 20: self.jobs.pop(next(iter(self.jobs)))
            key = uuid4().hex
            entry = {'id': key, 'status': 'running', 'progress': {'stage': '准备搜索', 'evaluations': 0, 'elapsed': 0},
                     'created': now, 'cancel': Event()}
            self.jobs[key] = entry

        def progress(value):
            with self.lock: entry['progress'] = value

        def run():
            try:
                result = solve(self.service, request, cancelled=entry['cancel'].is_set, progress=progress)
                with self.lock: entry.update(status=result['status'], result=result)
            except Exception:
                import traceback
                traceback.print_exc()
                with self.lock: entry.update(status='error', error='反算计算失败，请查看本地日志')
            finally: self.slots.release()

        Thread(target=run, daemon=True, name='position-planner').start()
        return {'id': key, 'status': 'running'}

    def status(self, data, cancel=False):
        key = data.get('id') if isinstance(data, dict) else None
        with self.lock:
            if not isinstance(key, str) or key not in self.jobs:
                raise ValueError('反算任务不存在或已过期')
            entry = self.jobs[key]
            if cancel: entry['cancel'].set()
            return deepcopy({k: v for k, v in entry.items() if k not in ('created', 'cancel')})
