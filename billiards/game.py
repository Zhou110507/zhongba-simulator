"""Local two-player rule games. The server owns balls, turn, groups and scores."""

from collections import OrderedDict
from copy import deepcopy
import json
from pathlib import Path
import random
import re
import secrets
import threading
from uuid import uuid4

from .cue import ShotInput
from .model import Ball, Vec2
from .pockets import unsupported_pocket
from .rules import HEAD, RULE_URL, RULE_VERSION, adjudicate, legal_ids, racked_balls, respot_ball


def integer(value,name,lower=0,upper=2**32-1):
    if isinstance(value,bool) or not isinstance(value,int) or not lower<=value<=upper:
        raise ValueError(f'{name} 超出允许范围')
    return value


def free_table(service,data):
    if not isinstance(data,dict):raise ValueError('自由球台参数无效')
    ids=data.get('balls')
    if not isinstance(ids,list) or len(ids)>15 or any(not isinstance(i,str) or i not in {str(n) for n in range(1,16)} for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('请选择 0 到 15 个不同编号的目标球')
    cue=data.get('cue',{})
    if not isinstance(cue,dict):raise ValueError('白球位置无效')
    from .play import _number
    position=Vec2(_number(cue.get('x'),'白球 X'),_number(cue.get('y'),'白球 Y'))
    balls=[Ball('cue',position,spec=service.ball_spec)]
    # Validate white first, then scatter targets around it without overlaps.
    service.decode(service.snapshot(balls,ShotInput(0,1)))
    if unsupported_pocket(balls[0],service.table):raise ValueError('白球不能摆在下球区域内')
    rng=random.Random(integer(data.get('seed',0),'布局编号'))
    for key in ids:
        for _ in range(3000):
            p=Vec2(rng.uniform(.15,service.table.length-.15),rng.uniform(.15,service.table.width-.15))
            if all((p-b.position).norm()>2*service.ball_spec.radius+.012 for b in balls):
                balls.append(Ball(key,p,spec=service.ball_spec));break
        else:raise ValueError('当前布局未能找到足够空间，请重新生成')
    return service.validate(service.snapshot(balls,ShotInput(0,1)))


class GameStore:
    def __init__(self,service,directory=None,*,compact=False):
        self.service=service;self.games=OrderedDict();self.cache={};self.lock=threading.RLock()
        self.compact=compact
        self.directory=Path(directory) if directory is not None else None

    def _save(self,state):
        if self.directory is None:return
        self.directory.mkdir(parents=True,exist_ok=True)
        target=self.directory/(state['id']+'.json')
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(state,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        temporary.replace(target)

    def _load(self,key):
        if not isinstance(key,str) or re.fullmatch('[0-9a-f]{32}',key) is None:raise ValueError('对局编号无效')
        if key not in self.games:
            path=self.directory/(key+'.json') if self.directory is not None else None
            if path is None or not path.is_file():raise ValueError('对局不存在，请重新开始')
            state=json.loads(path.read_text(encoding='utf-8'))
            if state.get('rule_version')!=RULE_VERSION:raise ValueError('对局规则版本不匹配')
            self.service.decode(state['scene'])
            self.games[key]=state
        self.games.move_to_end(key)
        return self.games[key]

    def public(self,state):
        data=deepcopy(state)
        data.update(rule_label='中八 · CBSA 2017 公开规则',rule_source=RULE_URL,legal_targets=legal_ids(state),
                    head_string_m=HEAD,foot_spot={'x':self.service.table.length-HEAD,'y':self.service.table.width/2})
        if state['ball_in_hand']=='head':
            legal=[b for b in state['scene']['balls'] if b['id'] in legal_ids(state) and b['pocket'] is None]
            if legal and all(b['position']['x']<HEAD-1e-9 for b in legal):
                closest=max(b['position']['x'] for b in legal)
                data['head_respot_candidates']=[b['id'] for b in legal if abs(b['position']['x']-closest)<1e-8]
        return data

    def _rack(self,state,breaker,seed,keep_warning=False):
        state.update(turn=breaker,breaker=breaker,phase='playing',winner=None,groups=[None,None],
                     is_break=True,ball_in_hand='head',needs_placement=False,choices=[],chooser=None,
                     scene=self.service.snapshot(racked_balls(self.service,seed,state.get('gap_mm',0)),ShotInput(0,4,0,0)),last_decision=None,seed=seed)
        if not keep_warning:state['break_warnings']=[0,0]

    def new(self,data):
        if not isinstance(data,dict):raise ValueError('对局参数无效')
        breaker=integer(data.get('breaker',0),'开球方',0,1)
        seed=integer(data.get('seed',secrets.randbits(32)),'摆球编号')
        from .play import _number
        gap=_number(data.get('gap_mm',.2),'摆球微隙')
        if not 0<=gap<=.5:raise ValueError('摆球微隙必须在 0–0.5 mm 内')
        ai_player=data.get('ai_player')
        if ai_player is not None:integer(ai_player,'AI 所在方',0,1)
        scenario=data.get('scenario','rack')
        if scenario not in ('rack','ai_endgame','ai_custom'):raise ValueError('未知对局场景')
        ai_group=data.get('ai_group','solid')
        if ai_group not in ('solid','stripe'):raise ValueError('AI 球组必须是全色或花色')
        custom_scene=None
        if scenario=='ai_custom' and data.get('scene') is not None:
            custom_scene=self.service.validate(data['scene'])['scene']
        with self.lock:
            state={'id':uuid4().hex,'revision':0,'rule_version':RULE_VERSION,'scores':[0,0],
                   'rack_number':1,'history':[],'last_decision':None,'seed':seed,'gap_mm':gap,'rack_version':'bounded-micro-gaps-v1'}
            self._rack(state,breaker,seed)
            state['ai_player']=ai_player
            state['scenario']=scenario
            if scenario in ('ai_endgame','ai_custom'):
                # Explicit practice start, separate from the normal fifteen-ball rack.
                ai_player=1 if ai_player is None else ai_player
                state.update(ai_player=ai_player,turn=ai_player,is_break=False,ball_in_hand=None,
                             groups=['solid' if i==ai_player else 'stripe' for i in range(2)])
                layout=[('cue',.75,.65),('1',1.27,.28),('2',2.08,.96),('3',.43,1.03),
                        ('8',1.98,.32),('9',.35,.40),('10',2.28,.65)]
                state['scene']=self.service.snapshot([Ball(key,Vec2(x,y),spec=self.service.ball_spec)
                                                      for key,x,y in layout],ShotInput(0,1.1))
            if scenario=='ai_custom':
                state['phase']='setup'
                if custom_scene is not None:state['scene']=custom_scene
                state['groups']=[ai_group if i==state['ai_player'] else ('stripe' if ai_group=='solid' else 'solid') for i in range(2)]
            self.games[state['id']]=state;self._save(state)
            while len(self.games)>8:
                old,_=self.games.popitem(last=False);self.cache.pop(old,None)
            return self.public(state)

    def get(self,data):
        if not isinstance(data,dict):raise ValueError('对局参数无效')
        with self.lock:return self.public(self._load(data.get('id')))

    def ai_snapshot(self,data):
        with self.lock:
            state=self._checked(data)
            who=state['chooser'] if state['phase']=='choice' else state['turn']
            if state.get('ai_player') is None or who!=state['ai_player'] or state['phase'] not in ('playing','choice'):
                raise ValueError('当前不是 AI 的回合')
            return deepcopy(state)

    def _checked(self,data):
        if not isinstance(data,dict):raise ValueError('对局参数无效')
        state=self._load(data.get('id'))
        if integer(data.get('revision'),'对局版本')!=state['revision']:raise ValueError('对局已更新，请重新载入，避免重复出杆')
        return state

    def _simulate(self,state,shot):
        if state['phase']!='playing':raise ValueError('请先处理规则选择或开始下一局')
        if state['needs_placement']:raise ValueError('请先摆放自由球，再出杆')
        scene=deepcopy(state['scene']);scene['shot']=shot
        scene=self.service.validate(scene)['scene']
        key=json.dumps([state['revision'],scene['shot']],sort_keys=True)
        cached=self.cache.get(state['id'])
        if cached and cached[0]==key:return deepcopy(cached[1])
        response=self.service.shoot(scene,compact=True) if self.compact else self.service.shoot(scene)
        self.cache[state['id']]=(key,deepcopy(response))
        return response

    def preview(self,data):
        with self.lock:
            state=self._checked(data)
            return self._simulate(state,data.get('shot'))

    def action(self,data):
        with self.lock:
            state=self._checked(data);before=deepcopy(state);action=data.get('action')
            if action=='shoot':
                response=self._simulate(state,data.get('shot'))
                if not response['complete']:
                    return {**response,'game_after':self.public(state),'rule_committed':False}
                updated=adjudicate(state,response,self.service)
                updated['scene']=deepcopy(response['next_scene'])
                if updated['last_decision']['respot_eight']:respot_ball(updated['scene'],'8',self.service)
                updated['history']=(state['history']+[updated['last_decision']])[-100:]
                state=updated
            elif action=='place':
                if state['phase']!='playing' or not state['ball_in_hand']:raise ValueError('当前没有自由摆球权')
                from .play import _number
                x,y=_number(data.get('x'),'白球 X'),_number(data.get('y'),'白球 Y')
                if state['ball_in_hand']=='head' and x>=HEAD:raise ValueError('本次只能把白球球心放在开球线后')
                state=deepcopy(state);cue=next(b for b in state['scene']['balls'] if b['id']=='cue')
                cue.update(position={'x':x,'y':y},pocket=None,velocity={'x':0,'y':0},omega={'x':0,'y':0,'z':0})
                balls,_=self.service.decode(state['scene'])
                if unsupported_pocket(next(b for b in balls if b.id=='cue'),self.service.table):raise ValueError('白球不能摆在袋口下球区域')
                state['needs_placement']=False
            elif action=='choice':
                choice=data.get('choice')
                if state['phase']!='choice' or choice not in state['choices']:raise ValueError('该规则选择当前不可用')
                state=deepcopy(state);who=state['chooser']
                if choice in ('rerack_self','rerack_opponent'):
                    breaker=who if choice=='rerack_self' else 1-who
                    if choice=='rerack_opponent':state['break_warnings'][breaker]=1
                    self._rack(state,breaker,(state['seed']+1)%2**32,keep_warning=True)
                elif choice.startswith('choose_'):
                    chosen='solid' if choice=='choose_solid' else 'stripe'
                    state['groups'][who]=chosen;state['groups'][1-who]='stripe' if chosen=='solid' else 'solid'
                    state.update(turn=who,phase='playing',choices=[],chooser=None)
                else:
                    state.update(turn=who,phase='playing',choices=[],chooser=None,
                                 ball_in_hand='all' if choice=='accept_free' else 'head' if choice=='accept_head' else None,
                                 needs_placement=choice!='accept_position')
            elif action=='respot_head':
                public=self.public(state);ids=public.get('head_respot_candidates',[])
                key=data.get('ball')
                if key not in ids:raise ValueError('当前不符合线后目标球重置条件')
                state=deepcopy(state);respot_ball(state['scene'],key,self.service)
            elif action=='next_rack':
                if state['phase']!='finished':raise ValueError('本局尚未结束')
                state=deepcopy(state);state['rack_number']+=1;state['seed']=(state['seed']+1)%2**32
                self._rack(state,1-state['breaker'],state['seed']);state['last_decision']=None
                state['scenario']='rack'
            elif action=='set_ai':
                ai_player=data.get('ai_player')
                if ai_player is not None:integer(ai_player,'AI 所在方',0,1)
                state=deepcopy(state);state['ai_player']=ai_player
            elif action=='finish_setup':
                if state.get('scenario')!='ai_custom' or state['phase']!='setup':raise ValueError('当前不在 AI 残局摆球中')
                scene=self.service.validate(data.get('scene'))['scene']
                balls,_=self.service.decode(scene)
                if not any(b.id=='8' and b.pocket is None for b in balls):raise ValueError('残局需要一颗在台的 8 号球')
                if any(b.id=='cue' and b.pocket is not None for b in balls):raise ValueError('请先把白球放回台面')
                if any(b.pocket is None and unsupported_pocket(b,self.service.table) for b in balls):
                    raise ValueError('请把在台球移出袋口下球区域')
                chosen=data.get('ai_group','solid')
                if chosen not in ('solid','stripe'):raise ValueError('请选择 AI 的球组')
                player=integer(data.get('ai_player',state.get('ai_player',1)),'AI 所在方',0,1)
                state=deepcopy(state)
                state.update(scene=scene,phase='playing',turn=player,ai_player=player,is_break=False,
                             groups=[chosen if i==player else ('stripe' if chosen=='solid' else 'solid') for i in range(2)],
                             scores=[0,0],winner=None,history=[],last_decision=None,
                             ball_in_hand=None,needs_placement=False)
            else:raise ValueError('未知对局操作')
            state['revision']=before['revision']+1
            self.service.decode(state['scene'])
            self._save(state);self.games[state['id']]=state;self.cache.pop(state['id'],None)
            if action=='shoot':return {**response,'game_after':self.public(state),'rule_committed':True}
            return self.public(state)
