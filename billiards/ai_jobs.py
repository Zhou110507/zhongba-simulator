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
from .ai_cache import model_stamp,matches,continuation,public_analysis


def decide(service, state, *, cancelled=lambda: False, progress=lambda value: None):
    if cancelled():return {'game_id':state['id'],'revision':state['revision'],'status':'cancelled','routes':[]}
    base={'game_id':state['id'],'revision':state['revision'],'routes':[],
          'model':'rule-action'}
    if state['phase']=='choice':
        choices=state['choices']
        preferred=('accept_free','accept_position','accept_head','choose_solid','choose_stripe','rerack_self','rerack_opponent')
        choice=next(c for c in preferred if c in choices)
        return {**base,'status':'found','action':{'action':'choice','choice':choice},'message':'AI 按当前可用规则选项继续'}
    if state['is_break']:
        from .break_policy import decide_break
        return decide_break(service,state)
    search=Search(service,seconds=24,evaluations=1500,cancelled=cancelled,progress=progress)
    base['model']=search.model.data['version'] if search.model.data else 'heuristic-baseline'
    if state['ball_in_hand']=='head' and not state['is_break']:
        targets=[b for b in state['scene']['balls'] if b['id'] in legal_ids(state) and b['pocket'] is None]
        if targets and all(b['position']['x']<HEAD-1e-9 for b in targets):
            ball=max(targets,key=lambda b:b['position']['x'])['id']
            return {**base,'status':'found','action':{'action':'respot_head','ball':ball},
                    'message':'按线后自由球规则重置最近的合法目标球'}
    if state['needs_placement']:
        candidates=[];valid_places=[]
        for x in (.25,.5,.8,1.1,1.4,1.7,2.,2.25):
            if state['ball_in_hand']=='head' and x>=HEAD:continue
            for y in (.22,.43,.635,.84,1.05):
                trial=deepcopy(state);cue=next(b for b in trial['scene']['balls'] if b['id']=='cue')
                cue.update(position={'x':x,'y':y},pocket=None)
                try:
                    balls,_=service.decode(trial['scene'])
                    if unsupported_pocket(next(b for b in balls if b.id=='cue'),service.table):continue
                    valid_places.append((x,y))
                    options=shot_options(service,trial,search.policy)
                    if options:candidates.append((options[0]['cost'],x,y))
                except ValueError:continue
        if candidates:_,x,y=min(candidates)
        elif valid_places:x,y=valid_places[0]
        else:
            # Denser geometric search, not a demand that an offensive pot exist.
            import numpy as np
            for x in np.linspace(.04,.60 if state['ball_in_hand']=='head' else service.table.length-.04,35):
                for y in np.linspace(.04,service.table.width-.04,25):
                    trial=deepcopy(state);cue=next(b for b in trial['scene']['balls'] if b['id']=='cue')
                    cue.update(position={'x':float(x),'y':float(y)},pocket=None)
                    try:
                        balls,_=service.decode(trial['scene'])
                        if not unsupported_pocket(next(b for b in balls if b.id=='cue'),service.table):valid_places.append((float(x),float(y)))
                    except ValueError:pass
                    if valid_places:break
                if valid_places:break
            if not valid_places:raise ValueError('台面没有有效白球位置，请检查场景')
            x,y=valid_places[0]
        return {**base,'status':'found','action':{'action':'place','x':x,'y':y},'message':'AI 选择有普通出杆空间的自由球位置'}
    result=search.solve(state)
    if cancelled():return {**base,**result,'status':'cancelled','routes':[]}
    if result['routes'] and result['routes'][0]['steps'][0]['cost']<5.:
        return {**base,**result,'action':{'action':'shoot','shot':result['routes'][0]['steps'][0]['shot']}}
    from .tactics import choose_contact
    progress({'stage':'进攻后备：检查多库解球、K球与防守','evaluations':search.count})
    fallback=choose_contact(service,state,cancelled=cancelled)
    if result['routes'] and (fallback.get('tactic')=='best_effort' or
                             fallback.get('tactic')=='safety' and fallback.get('hidden_fraction',0)<.5):
        return {**base,**result,'action':{'action':'shoot','shot':result['routes'][0]['steps'][0]['shot']}}
    return {**base,**fallback,'offensive_evaluations':search.count}


class AIJobs:
    def __init__(self,games,slots):
        self.games=games;self.slots=slots;self.lock=Lock();self.jobs={}
        self.continuations={};self.metrics={'cache_hits':0,'prefetches':0,'searches':0,'invalidations':0}

    def start(self,data):
        state=self.games.ai_snapshot(data)
        with self.lock:
            now=monotonic()
            self.jobs={k:v for k,v in self.jobs.items() if v['status']=='running' or now-v['created']<900}
            self.continuations={k:v for k,v in self.continuations.items() if now-v['created']<900}
            stamp=model_stamp(self.games.service)
            for key,existing in self.jobs.items():
                if (existing['game_id']==state['id'] and existing['revision']==state['revision'] and
                    existing.get('stamp')==stamp and not existing['cancel'].is_set() and
                    existing['status'] in ('running','found') and matches(existing['source'],state)):
                    return {'id':key,'status':existing['status'],'reused_job':True}
            saved=self.continuations.pop(state['id'],None)
            if saved and (saved['revision']!=state['revision'] or saved['stamp']!=stamp or not matches(saved['expected'],state)):
                self.metrics['invalidations']+=1;saved=None
            if saved:
                while len(self.jobs)>=20:
                    old=next((k for k,v in self.jobs.items() if v['status']!='running'),None)
                    if old is None:break
                    self.jobs.pop(old)
                key=uuid4().hex
                self.jobs[key]={'id':key,'status':'found','created':now,'cancel':Event(),
                                'game_id':state['id'],'revision':state['revision'],'stamp':stamp,
                                'source':deepcopy(state),
                                'analysis':saved['analysis']}
                self.metrics['cache_hits']+=1
                return {'id':key,'status':'found','cache_hit':True}
            if any(v['status']=='running' for v in self.jobs.values()):raise ValueError('已有 AI 在思考，请先取消或等待完成')
            if not self.slots.acquire(blocking=False):raise ValueError('计算繁忙，请稍后重试')
            while len(self.jobs)>=20:self.jobs.pop(next(iter(self.jobs)))
            key=uuid4().hex
            entry={'id':key,'status':'running','created':now,'cancel':Event(),
                   'game_id':state['id'],'revision':state['revision'],
                   'stamp':stamp,
                   'source':deepcopy(state),
                   'progress':{'stage':'AI 正在检查球形与出杆空间','evaluations':0}}
            self.jobs[key]=entry
            self.metrics['searches']+=1
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
            public={k:v for k,v in entry.items() if k not in ('created','cancel','stamp','source','analysis')}
            if 'analysis' in entry:public['analysis']=public_analysis(entry['analysis'])
            return deepcopy(public)

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
                current=self.games.ai_snapshot({'id':entry['game_id'],'revision':entry['revision']})
                if entry.get('source') is not None and (not matches(entry['source'],current) or entry.get('stamp')!=model_stamp(self.games.service)):
                    raise ValueError('台面或模型与 AI 快照不一致，请重新计算')
                value=self.games.action({'id':entry['game_id'],'revision':entry['revision'],**analysis['action']})
            if value.get('rule_committed'):
                actual=value['game_after'];tail=continuation(analysis,actual)
                if tail:
                    self.continuations[actual['id']]={'expected':deepcopy(actual),'revision':actual['revision'],
                                                       'created':monotonic(),
                                                       'stamp':entry.get('stamp',model_stamp(self.games.service)),
                                                       'analysis':tail}
                    while len(self.continuations)>8:self.continuations.pop(next(iter(self.continuations)))
        response={**value,'ai_analysis':public_analysis(analysis)}
        if data.get('prefetch') and value.get('rule_committed'):
            actual=value['game_after']
            who=actual['chooser'] if actual['phase']=='choice' else actual['turn']
            if actual['phase'] in ('playing','choice') and who==actual.get('ai_player'):
                try:
                    response['prefetch']=self.start({'id':actual['id'],'revision':actual['revision']})
                    response['prefetch'].update(game_id=actual['id'],revision=actual['revision'])
                    self.metrics['prefetches']+=1
                except ValueError:pass  # CPU occupied: ordinary next-turn start retries.
        return response
