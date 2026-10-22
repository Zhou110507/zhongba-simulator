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
from .ai_rolling import HORIZON,endpoint,extend,append,readiness
from .ai_difficulty import realize


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
    search=Search(service,seconds=30,evaluations=1800,cancelled=cancelled,progress=progress)
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
    result=search.plan(state)
    if cancelled():return {**base,**result,'status':'cancelled','routes':[]}
    if result['routes']:
        return {**base,**result,'action':{'action':'shoot','shot':result['routes'][0]['steps'][0]['shot']}}
    from .tactics import choose_contact
    progress({'stage':'进攻后备：可直达时检查防守，被遮挡时检查解球','evaluations':search.count})
    fallback=choose_contact(service,state,cancelled=cancelled)
    return {**base,**fallback,'offensive_evaluations':search.count}


class AIJobs:
    def __init__(self,games,slots):
        self.games=games;self.slots=slots;self.lock=Lock();self.jobs={}
        self.continuations={};self.metrics={'cache_hits':0,'prefetches':0,'searches':0,'invalidations':0,
                                          'extensions':0,'extended_steps':0}

    def start(self,data):
        value=self._start(data)
        self._extend(data['id'])
        with self.lock:
            lane=self.continuations.get(data['id'])
            if lane:value.update(extending=lane.get('extending',False),queued_steps=self._length(lane))
        return value

    def _start(self,data):
        state=self.games.ai_snapshot(data)
        with self.lock:
            now=monotonic()
            self.jobs={k:v for k,v in self.jobs.items() if v['status']=='running' or now-v['created']<900}
            for key,lane in list(self.continuations.items()):
                if now-lane['created']>=900:
                    lane['cancel'].set();self.continuations.pop(key)
            stamp=model_stamp(self.games.service)
            saved=self.continuations.get(state['id'])
            if saved and (saved['cancel'].is_set() or saved['revision']!=state['revision'] or saved['stamp']!=stamp or not matches(saved['expected'],state)):
                saved['cancel'].set();self.continuations.pop(state['id'])
                self.metrics['invalidations']+=1;saved=None
            for key,existing in self.jobs.items():
                if (existing['game_id']==state['id'] and existing['revision']==state['revision'] and
                    existing.get('stamp')==stamp and not existing['cancel'].is_set() and
                    existing['status'] in ('running','found') and matches(existing['source'],state)):
                    return {'id':key,'status':existing['status'],'reused_job':True}
            if saved and (saved['analysis'] or saved.get('extending')):
                while len(self.jobs)>=20:
                    old=next((k for k,v in self.jobs.items() if v['status']!='running'),None)
                    if old is None:break
                    self.jobs.pop(old)
                key=uuid4().hex
                ready=bool(saved['analysis'])
                self.jobs[key]={'id':key,'status':'found' if ready else 'running','created':now,'cancel':Event(),
                                'game_id':state['id'],'revision':state['revision'],'stamp':stamp,
                                'source':deepcopy(state),
                                'analysis':deepcopy(saved['analysis']),
                                'progress':{'stage':'等待队尾补算完成；已验证前序杆已执行','evaluations':0},
                                '_waiting_extension':not ready}
                if ready:self.metrics['cache_hits']+=1
                return {'id':key,'status':'found' if ready else 'running','cache_hit':ready}
            if any(v['status']=='running' and not v['cancel'].is_set() for v in self.jobs.values()):raise ValueError('已有 AI 在思考，请先取消或等待完成')
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
                with self.lock:
                    entry.update(status=result['status'],analysis=result)
                    if result['status']=='found' and endpoint(result) is not None and not entry['cancel'].is_set():
                        self.continuations[state['id']]={'cancel':Event(),'extending':False,'stamp':entry['stamp'],
                            'expected':deepcopy(state),'revision':state['revision'],'created':monotonic(),'analysis':deepcopy(result)}
            except Exception:
                import traceback
                traceback.print_exc()
                with self.lock:entry.update(status='error',error='AI 计算失败，请查看本机日志')
            finally:
                self.slots.release()
                self._extend(state['id'])
        Thread(target=run,daemon=True,name='runout-ai').start()
        return {'id':key,'status':'running'}

    @staticmethod
    def _length(lane):
        analysis=lane.get('analysis')
        return len(analysis['routes'][0]['steps']) if analysis and analysis.get('routes') else 0

    def _live(self,key,lane):
        if self.continuations.get(key) is not lane or lane['cancel'].is_set():return False
        if lane['stamp']!=model_stamp(self.games.service):return False
        try:actual=self.games.ai_snapshot({'id':key,'revision':lane['revision']})
        except ValueError:return False
        return matches(lane['expected'],actual)

    def _publish(self,lane):
        # A search may finish after several prefix strokes have been consumed.
        # Publish to the current revision only, never resurrect an old job.
        for entry in self.jobs.values():
            if (entry['game_id']==lane['expected']['id'] and entry['revision']==lane['revision'] and
                entry['stamp']==lane['stamp'] and not entry['cancel'].is_set() and matches(entry['source'],lane['expected'])):
                entry.update(status=lane['analysis']['status'],analysis=deepcopy(lane['analysis']))
                entry.pop('_waiting_extension',None)

    def _finish_tactically(self,key,lane,reason):
        # A failed suffix never authorizes a stroke at its future endpoint.
        with self.lock:
            if not self._live(key,lane):lane['cancel'].set();return
            source=deepcopy(lane['expected'])
            lane['fallback_pending']=True
            lane['progress']={'stage':'续接未接通，按当前实际球位选择进攻、防守或解球','evaluations':0}
        from .tactics import choose_contact
        result=choose_contact(self.games.service,source,cancelled=lane['cancel'].is_set)
        with self.lock:
            if (self._live(key,lane) and lane['revision']==source['revision'] and
                matches(lane['expected'],source) and result['status']=='found'):
                lane['abandoned_analysis']=lane['analysis']
                result['transition']={'reason':reason,'source_revision':source['revision'],
                                      'retained_steps':self._length(lane),'required':HORIZON}
                result['message']=('三杆续接未接通，改按当前球位完成本杆；' if reason=='no_robust_continuation_found'
                                   else '队尾补算异常，改按当前球位完成本杆；')+result.get('message','')
                result.update(game_id=key,revision=lane['revision'])
                lane['analysis']=result;self._publish(lane)
            else:lane['cancel'].set()

    def _extend(self,key):
        with self.lock:
            lane=self.continuations.get(key)
            if not lane or lane.get('extending') or not lane.get('analysis'):return
            anchor=endpoint(lane['analysis']);remaining=self._length(lane)
            if (anchor is None or remaining>=HORIZON or anchor['phase']!='playing' or
                anchor['winner'] is not None or anchor['turn']!=anchor.get('ai_player')):return
            if lane.get('failed_anchor') and matches(lane['failed_anchor'],anchor):return
            if not self._live(key,lane):lane['cancel'].set();return
            if not self.slots.acquire(blocking=False):return
            lane['extending']=True;lane['anchor']=deepcopy(anchor)
            depth=HORIZON-remaining
            lane['progress']={'stage':f'保留前 {remaining} 杆，向队尾补算 {depth} 杆','evaluations':0}
            self.metrics['extensions']+=1
        def progress(value):
            with self.lock:
                if self.continuations.get(key) is lane:lane['progress']=value
        def run():
            fallback_started=False
            try:
                result=extend(self.games.service,anchor,depth,cancelled=lane['cancel'].is_set,progress=progress)
                with self.lock:
                    if not self._live(key,lane):lane['cancel'].set();return
                    combined=append(lane['analysis'],result,anchor)
                    needs_fallback=combined is None
                    if combined:
                        combined.update(game_id=key,revision=lane['revision'],cache_hit=True,evaluations=0,elapsed=0.)
                        lane['analysis']=combined
                        self.metrics['extended_steps']+=len(result['routes'][0]['steps'])
                        self._publish(lane)
                if needs_fallback:
                    # extend resumes budget slices internally; only exhausted
                    # continuation searches reach this tactical transition.
                    fallback_started=True
                    self._finish_tactically(key,lane,'no_robust_continuation_found')
            except Exception:
                import traceback
                traceback.print_exc()
                if not fallback_started:
                    try:
                        self._finish_tactically(key,lane,'suffix_error')
                        return
                    except Exception:traceback.print_exc()
                with self.lock:
                    lane['failed_anchor']=deepcopy(anchor)
                    for entry in self.jobs.values():
                        if entry['game_id']==key and entry['revision']==lane['revision'] and entry['stamp']==lane['stamp'] and matches(entry['source'],lane['expected']):
                            entry.update(status='error',error='队尾补算及独立战术计算均失败，请查看日志')
            finally:
                with self.lock:
                    lane['extending']=False
                    lane['fallback_pending']=False
                    if lane['cancel'].is_set():
                        for entry in self.jobs.values():
                            if (entry.get('_waiting_extension') and entry['game_id']==key and
                                entry['stamp']==lane['stamp'] and matches(entry['source'],lane['expected'])):
                                entry.update(status='cancelled',analysis={'status':'cancelled','routes':[]})
                                entry.pop('_waiting_extension',None)
                self.slots.release()
                # If another stroke was played during the search, refill the
                # newly vacant place too; never redo the retained prefix.
                self._extend(key)
        Thread(target=run,daemon=True,name='runout-rolling').start()

    def status(self,data,*,cancel=False):
        with self.lock:
            key=data.get('id') if isinstance(data,dict) else None
            if not isinstance(key,str) or key not in self.jobs:raise ValueError('AI 任务不存在或已过期')
            entry=self.jobs[key]
            lane=self.continuations.get(entry['game_id'])
            current=lane and matches(entry['source'],lane['expected']) and entry['revision']==lane['revision']
            if cancel:
                entry['cancel'].set()
                if current:lane['cancel'].set()
            public={k:v for k,v in entry.items() if k not in ('created','cancel','stamp','source','analysis') and not k.startswith('_')}
            if entry.get('analysis'):
                public['analysis']=public_analysis(entry['analysis'])
                gate=readiness(entry['analysis'],entry['source'])
                if current:
                    last=endpoint(lane['analysis'])
                    public['analysis']['rolling']={'target':HORIZON,'remaining':self._length(lane),
                                                  'extending':lane.get('extending',False),
                                                  'fallback_pending':lane.get('fallback_pending',False),
                                                  'exhausted':bool(last and lane.get('failed_anchor') and matches(last,lane['failed_anchor'])),
                                                  'progress':lane.get('progress',{})}
                    gate=readiness(lane['analysis'] or entry['analysis'],entry['source'])
                exhausted=bool(current and public['analysis'].get('rolling',{}).get('exhausted')) or endpoint(entry['analysis']) is None
                gate.update(waiting=not gate['ready'] and not exhausted,blocked=not gate['ready'] and exhausted)
                public['analysis']['execution_gate']=gate
            public=deepcopy(public)
        if not cancel:self._extend(entry['game_id'])
        return public

    def execute(self,data):
        with self.lock:
            key=data.get('id') if isinstance(data,dict) else None
            if not isinstance(key,str) or key not in self.jobs:raise ValueError('AI 任务不存在或已过期')
            entry=self.jobs[key]
            if entry['cancel'].is_set() or entry['status']!='found' or 'action' not in entry.get('analysis',{}):
                raise ValueError('AI 任务没有可执行方案或已取消')
            lane=self.continuations.get(entry['game_id'])
            same_lane=(lane and not lane['cancel'].is_set() and lane['revision']==entry['revision'] and
                       matches(lane['expected'],entry['source']) and lane['stamp']==entry['stamp'])
            analysis=deepcopy(lane['analysis'] if same_lane and lane['analysis'] else entry['analysis'])
            # Check and commit under the same game lock. Revision prevents double
            # execution, including retries and a second browser on the same match.
            with self.games.lock:
                current=self.games.ai_snapshot({'id':entry['game_id'],'revision':entry['revision']})
                if entry.get('source') is not None and (not matches(entry['source'],current) or entry.get('stamp')!=model_stamp(self.games.service)):
                    raise ValueError('台面或模型与 AI 快照不一致，请重新计算')
                gate=readiness(analysis,current)
                if not gate['ready']:
                    raise ValueError(f"等待前瞻补齐：已验证 {gate['available']}/{gate['required']} 杆，当前杆尚未执行")
                action=deepcopy(analysis['action']);execution=None
                if action['action']=='shoot':
                    action['shot'],execution=realize(self.games.service,current,action['shot'])
                    analysis['execution']=execution
                value=self.games.action({'id':entry['game_id'],'revision':entry['revision'],**action},ai_execution=execution)
            if value.get('rule_committed'):
                actual=value['game_after'];tail=continuation(analysis,actual)
                if tail:
                    if not same_lane:
                        if lane:lane['cancel'].set()
                        lane={'cancel':Event(),'extending':False,'stamp':entry.get('stamp',model_stamp(self.games.service))}
                        self.continuations[actual['id']]=lane
                    lane.update(expected=deepcopy(actual),revision=actual['revision'],created=monotonic(),analysis=tail)
                    while len(self.continuations)>8:self.continuations.pop(next(iter(self.continuations)))['cancel'].set()
                elif (same_lane and lane.get('extending') and endpoint(analysis) is not None and
                      matches(endpoint(analysis),actual) and actual['phase']=='playing' and actual['turn']==actual.get('ai_player')):
                    # Keep ownership of the endpoint worker even when playback
                    # overtakes it. The next client joins it instead of re-search.
                    lane.update(expected=deepcopy(actual),revision=actual['revision'],created=monotonic(),analysis=None)
                else:
                    old=self.continuations.pop(actual['id'],None)
                    if old:old['cancel'].set()
        response={**value,'ai_analysis':public_analysis(analysis)}
        if execution is not None:response['ai_execution']=execution
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
