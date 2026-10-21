"""Cancellable AI workers bound to an immutable game revision.

Planning never mutates a match. Executing a finished job uses GameStore.action,
so AI and humans share the exact same rule adjudication and playback service.
"""
from copy import deepcopy
from math import atan2, degrees
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from .cue import ShotInput
from .model import Vec2
from .pockets import unsupported_pocket
from .rules import HEAD, legal_ids
from .runout import Search, shot_options


def decide(service, state, *, cancelled=lambda: False, progress=lambda value: None):
    search=Search(service,cancelled=cancelled,progress=progress)
    base={'game_id':state['id'],'revision':state['revision'],'routes':[],
          'model':search.model.data['version'] if search.model.data else 'heuristic-baseline'}
    if state['phase']=='choice':
        choices=state['choices']
        preferred=('accept_free','accept_position','accept_head','choose_solid','choose_stripe','rerack_self','rerack_opponent')
        choice=next(c for c in preferred if c in choices)
        return {**base,'status':'found','action':{'action':'choice','choice':choice},'message':'AI 按当前可用规则选项继续'}
    if state['ball_in_hand']=='head' and not state['is_break']:
        targets=[b for b in state['scene']['balls'] if b['id'] in legal_ids(state) and b['pocket'] is None]
        if targets and all(b['position']['x']<HEAD-1e-9 for b in targets):
            ball=max(targets,key=lambda b:b['position']['x'])['id']
            return {**base,'status':'found','action':{'action':'respot_head','ball':ball},
                    'message':'按线后自由球规则重置最近的合法目标球'}
    if state['needs_placement']:
        candidates=[]
        for x in (.25,.5,.8,1.1,1.4,1.7,2.,2.25):
            if state['ball_in_hand']=='head' and x>=HEAD:continue
            for y in (.22,.43,.635,.84,1.05):
                trial=deepcopy(state);cue=next(b for b in trial['scene']['balls'] if b['id']=='cue')
                cue.update(position={'x':x,'y':y},pocket=None)
                try:
                    balls,_=service.decode(trial['scene'])
                    if unsupported_pocket(next(b for b in balls if b.id=='cue'),service.table):continue
                    options=shot_options(service,trial,search.policy)
                    if options:candidates.append((options[0]['cost'],x,y))
                except ValueError:continue
        if not candidates:return {**base,'status':'not_found','message':'未找到普通杆法可用的自由球位置，可暂停 AI 后手动摆球'}
        _,x,y=min(candidates)
        return {**base,'status':'found','action':{'action':'place','x':x,'y':y},'message':'AI 选择有普通出杆空间的自由球位置'}
    if state['is_break']:
        balls,_=service.decode(state['scene']);cue=next(b for b in balls if b.id=='cue')
        apex=next(b for b in balls if b.id=='1')
        shot=ShotInput(degrees(atan2(apex.position.y-cue.position.y,apex.position.x-cue.position.x)),4.)
        trial=search.forward(state,shot,opening=True)
        if trial:
            from dataclasses import asdict
            return {**base,'status':'found','action':{'action':'shoot','shot':asdict(shot)},
                    'message':'AI 基本开球（与普通对局共用杆速范围）','evaluations':search.count}
        return {**base,'status':'cancelled' if cancelled() else 'not_found','message':'开球仿真未完成，请重试或切换手动'}
    result=search.solve(state)
    if result['routes']:
        return {**base,**result,'action':{'action':'shoot','shot':result['routes'][0]['steps'][0]['shot']}}
    # A legal ordinary contact is a modest fallback, never advertised as a safety
    # or a clear. Reject any foul, scratch, unsupported or inaccessible stroke.
    if not search.stopped():
        balls,_=service.decode(state['scene']);cue=next(b for b in balls if b.id=='cue')
        for target in sorted((b for b in balls if b.id in legal_ids(state)),key=lambda b:(b.position-cue.position).norm()):
            for speed,tip in ((.8,0.),(1.2,.5),(1.8,0.)):
                shot=ShotInput(degrees(atan2(target.position.y-cue.position.y,target.position.x-cue.position.x)),speed,0.,tip)
                trial=search.forward(state,shot)
                if trial and not trial[1]['last_decision']['fouls'] and trial[1]['winner'] is None:
                    from dataclasses import asdict
                    return {**base,**result,'status':'found','evaluations':search.count,
                            'action':{'action':'shoot','shot':asdict(shot)},
                            'message':'未找到可验证进球路线，采用合法普通触球；此杆不作为清台推荐'}
    return {**base,**result,'message':'预算内未找到符合普通出杆限制的方案；可重试或切换本地双人接管'}


class AIJobs:
    def __init__(self,games,slots):
        self.games=games;self.slots=slots;self.lock=Lock();self.jobs={}

    def start(self,data):
        state=self.games.ai_snapshot(data)
        with self.lock:
            now=monotonic()
            self.jobs={k:v for k,v in self.jobs.items() if v['status']=='running' or now-v['created']<900}
            if any(v['status']=='running' for v in self.jobs.values()):raise ValueError('已有 AI 在思考，请先取消或等待完成')
            if not self.slots.acquire(blocking=False):raise ValueError('计算繁忙，请稍后重试')
            while len(self.jobs)>=20:self.jobs.pop(next(iter(self.jobs)))
            key=uuid4().hex
            entry={'id':key,'status':'running','created':now,'cancel':Event(),
                   'game_id':state['id'],'revision':state['revision'],
                   'progress':{'stage':'AI 正在检查球形与出杆空间','evaluations':0}}
            self.jobs[key]=entry
        def progress(value):
            with self.lock:entry['progress']=value
        def run():
            try:
                result=decide(self.games.service,state,cancelled=entry['cancel'].is_set,progress=progress)
                if entry['cancel'].is_set():result={**result,'status':'cancelled','routes':[]};result.pop('action',None)
                with self.lock:entry.update(status=result['status'],analysis=result)
            except Exception:
                import traceback
                traceback.print_exc()
                with self.lock:entry.update(status='error',error='AI 计算失败，请查看本机日志')
            finally:self.slots.release()
        Thread(target=run,daemon=True,name='runout-ai').start()
        return {'id':key,'status':'running'}

    def status(self,data,*,cancel=False):
        with self.lock:
            key=data.get('id') if isinstance(data,dict) else None
            if not isinstance(key,str) or key not in self.jobs:raise ValueError('AI 任务不存在或已过期')
            entry=self.jobs[key]
            if cancel:entry['cancel'].set()
            return deepcopy({k:v for k,v in entry.items() if k not in ('created','cancel')})

    def execute(self,data):
        with self.lock:
            key=data.get('id') if isinstance(data,dict) else None
            if not isinstance(key,str) or key not in self.jobs:raise ValueError('AI 任务不存在或已过期')
            entry=self.jobs[key]
            if entry['cancel'].is_set() or entry['status']!='found' or 'action' not in entry.get('analysis',{}):
                raise ValueError('AI 任务没有可执行方案或已取消')
            analysis=deepcopy(entry['analysis'])
            # Check and commit under the same game lock. Revision prevents double
            # execution, including retries and a second browser on the same match.
            with self.games.lock:
                self.games.ai_snapshot({'id':entry['game_id'],'revision':entry['revision']})
                value=self.games.action({'id':entry['game_id'],'revision':entry['revision'],**analysis['action']})
            return {**value,'ai_analysis':analysis}
