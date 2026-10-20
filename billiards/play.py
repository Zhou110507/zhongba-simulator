"""Versioned scene snapshots and the shared forward-shot application service."""

from dataclasses import asdict, replace
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from time import perf_counter

from .cue import CueSpec, ShotInput, strike
from .engine import simulate
from .equipment import load_equipment, load_physics_profile
from .model import Ball, PocketSpec, Vec2, Vec3, validate_scene
from .pockets import geometry_dict, outline
from .shot_analysis import first_contact_analysis

ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = 'phase-c-spin-v1'


def _number(value, name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value):
        raise ValueError(f"{name} 必须是有限数值")
    return float(value)


class PlayService:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        config = json.loads((self.root/'configs'/'prototype_play.json').read_text(encoding='utf-8'))
        equipment = load_equipment(self.root/'configs'/'chinese_eight_ball.json',config['table_profile'])
        self.table = replace(equipment.table,pockets=PocketSpec(**config['pockets']))
        self.ball_spec = equipment.ball
        self.physics = load_physics_profile(self.root/'configs'/'physics_profiles.json',config['physics_profile'])
        self.cue = CueSpec(**config['cue'])
        self.model = {'table':asdict(self.table),'physics':asdict(self.physics),'cue':asdict(self.cue)}
        self.signature = sha256(json.dumps(self.model,sort_keys=True).encode()).hexdigest()[:16]

    def snapshot(self, balls, shot):
        return {'schema_version':1,'kind':'zhongba-practice','model_signature':self.signature,
                **deepcopy(self.model),'balls':[asdict(ball) for ball in balls],'shot':asdict(shot)}

    def decode(self, data):
        if not isinstance(data,dict) or data.get('schema_version') != 1 or data.get('kind') != 'zhongba-practice':
            raise ValueError("不支持的场景文件格式")
        if data.get('model_signature') != self.signature or any(data.get(key) != value for key,value in self.model.items()):
            raise ValueError("场景的球桌、物理或球杆版本不匹配，请保留原文件并使用对应版本打开")
        values = data.get('balls')
        if not isinstance(values,list) or not 1 <= len(values) <= 16:
            raise ValueError("场景需要一颗白球和最多 15 颗目标球")
        allowed_ids = {'cue',*(str(number) for number in range(1,16))}
        pocket_ids = {pocket.id for pocket in outline(self.table).pockets}
        balls = []
        try:
            for value in values:
                if not isinstance(value,dict) or value.get('id') not in allowed_ids:
                    raise ValueError("球号必须为 cue 或 1 到 15")
                if value.get('spec') != asdict(self.ball_spec):
                    raise ValueError("球规格与当前中八配置不匹配")
                position = value['position']
                velocity,omega = value['velocity'],value['omega']
                if any(_number(velocity[axis],'速度') != 0 for axis in ('x','y')) or any(
                        _number(omega[axis],'角速度') != 0 for axis in ('x','y','z')):
                    raise ValueError("可编辑场景中所有球必须完全静止")
                pocket = value.get('pocket')
                if pocket is not None and pocket not in pocket_ids:
                    raise ValueError("未知球袋编号")
                balls.append(Ball(value['id'],Vec2(_number(position['x'],'x'),_number(position['y'],'y')),
                                  spec=self.ball_spec,pocket=pocket))
            source = data['shot']
            shot = ShotInput(*(_number(source[name],name) for name in ('angle_deg','cue_speed','tip_x','tip_y')))
        except (KeyError,TypeError) as error:
            raise ValueError("场景字段不完整或格式错误") from error
        if sum(ball.id=='cue' for ball in balls) != 1:
            raise ValueError("场景必须恰好包含一颗白球")
        validate_scene(balls,self.table,self.physics)
        cue_ball = next(ball for ball in balls if ball.id=='cue')
        strike(replace(cue_ball,pocket=None),shot,self.cue)
        return tuple(balls),shot

    def validate(self, data):
        balls,shot = self.decode(data)
        cue_ball = next(ball for ball in balls if ball.id=='cue')
        launched = strike(replace(cue_ball,pocket=None),shot,self.cue)
        return {'scene':self.snapshot(balls,shot),
                'launch':{'speed':launched.velocity.norm(),'velocity':asdict(launched.velocity),
                          'omega':asdict(launched.omega)}}

    def shoot(self, data):
        balls,shot = self.decode(data)
        cue_ball = next(ball for ball in balls if ball.id=='cue')
        launched = strike(cue_ball,shot,self.cue)
        initial = tuple(launched if ball.id=='cue' else ball for ball in balls)
        started = perf_counter()
        result = simulate(initial,self.table,self.physics,max_time=60,max_events=1200)
        elapsed = (perf_counter()-started)*1000
        complete = result.status=='stopped'
        final = tuple(replace(ball,velocity=Vec2(),omega=Vec3()) for ball in result.final)
        return {'result':result.to_dict(None),'compute_ms':elapsed,'complete':complete,
                'contact_analysis':first_contact_analysis(result),
                'next_scene':self.snapshot(final,shot) if complete else None,
                'snapshot':self.snapshot(balls,shot),
                'summary':{'potted':[ball.id for ball in result.final if ball.pocket is not None and
                                     next(initial for initial in balls if initial.id==ball.id).pocket is None],
                           'scratch':next(ball for ball in result.final if ball.id=='cue').pocket is not None,
                           'first_contact':next((event.actors[1] if event.actors[0]=='cue' else event.actors[0]
                                                 for event in result.events
                                                 if event.kind=='ball_ball' and 'cue' in event.actors),None)}}

    def presets(self):
        corner = next(pocket for pocket in outline(self.table).pockets if pocket.id=='top-right')
        descriptions = (
            ('corner','角袋直球',[Ball('cue',corner.mouth-corner.outward*1.15,spec=self.ball_spec),
                                Ball('1',corner.mouth-corner.outward*.55,spec=self.ball_spec)],ShotInput(45,.9)),
            ('side','中袋直球',[Ball('cue',Vec2(self.table.length/2,.88),spec=self.ball_spec),
                              Ball('1',Vec2(self.table.length/2,.45),spec=self.ball_spec)],ShotInput(270,.9)),
            ('draw','低杆练习 · 中距离',[Ball('cue',Vec2(.45,.6),spec=self.ball_spec),
                              Ball('1',Vec2(1.2,.6),spec=self.ball_spec)],ShotInput(0,2.8,0,-.5)),
            ('draw-angle','低杆分离角 · 偏瞄 0.5°',[Ball('cue',Vec2(.45,.6),spec=self.ball_spec),
                              Ball('1',Vec2(1.2,.6),spec=self.ball_spec)],ShotInput(.5,2.8,0,-.5)),
            ('follow','高杆练习 · 中距离',[Ball('cue',Vec2(.45,.6),spec=self.ball_spec),
                                Ball('1',Vec2(1.2,.6),spec=self.ball_spec)],ShotInput(0,1.8,0,.5)),
            ('cushion','碰库与左右击点',[Ball('cue',Vec2(1.6,.4),spec=self.ball_spec)],ShotInput(10,1.8,.35,.25)),
            ('speed','中力走台 · 单球',[Ball('cue',Vec2(.4,.42),spec=self.ball_spec)],ShotInput(0,2.5,0,.4)),
            ('side-transfer','侧旋传递 · 正碰',[Ball('cue',Vec2(.65,.6),spec=self.ball_spec),
                              Ball('1',Vec2(1.2,.6),spec=self.ball_spec)],ShotInput(0,1.8,.45,0)),
            ('throw','碰薄带偏 · 近半球',[Ball('cue',Vec2(.65,.6),spec=self.ball_spec),
                              Ball('1',Vec2(1.2,.628575),spec=self.ball_spec)],ShotInput(0,1.8,0,0)),
            ('free','自由摆球',[Ball('cue',Vec2(.5,.55),spec=self.ball_spec),
                              Ball('1',Vec2(.95,.55),spec=self.ball_spec),
                              Ball('2',Vec2(1.5,.75),spec=self.ball_spec),
                              Ball('8',Vec2(1.9,.45),spec=self.ball_spec)],ShotInput(5,.9,0,.3)),
        )
        return [{'id':name,'name':label,'scene':self.snapshot(balls,shot)} for name,label,balls,shot in descriptions]

    def config(self):
        return {'app_version':APP_VERSION,'model_signature':self.signature,
                'model':deepcopy(self.model),'ball_spec':asdict(self.ball_spec),
                'geometry':geometry_dict(self.table),'presets':self.presets(),
                'limits':{'max_balls':16,'max_tip_offset':self.cue.max_tip_offset,
                          'max_cue_speed':self.cue.max_speed},
                'calibration_status':'Generic literature-bounded cloth tuning; table-specific dynamics and pocket geometry uncalibrated',
                'cloth_reference':{'label':'通用台球 · 较快台面参考','sliding':self.physics.sliding_friction,
                                   'rolling':self.physics.rolling_friction,
                                   'source':'https://drdavepoolinfo.com/faq/physics/physical-properties/'}}
