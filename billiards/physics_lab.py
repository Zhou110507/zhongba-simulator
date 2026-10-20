"""Bounded, reproducible contact-state experiments using the production engine."""

from dataclasses import replace
from math import cos, sin, radians

from .ball_contact import impact_report
from .calibration import number
from .engine import simulate
from .model import Ball, Vec2, Vec3


def run_experiment(service,data):
    if not isinstance(data,dict):
        raise ValueError('实验参数必须是对象')
    kind=data.get('kind','ball')
    if kind not in ('ball','cushion'):
        raise ValueError('未知实验类型')
    speed=number(data,'speed',minimum=.1)
    cut=number(data,'cut')
    follow=number(data,'follow',minimum=-1.5)
    side=number(data,'side',minimum=-1.5)
    if speed>3.5 or cut>70 or max(abs(follow),abs(side))>1.5:
        raise ValueError('实验范围：速度 0.1–3.5 m/s，角度 0–70°，旋转比 ±1.5')
    radius=service.ball_spec.radius
    theta=radians(cut)
    if kind=='ball':
        cue=Ball('cue',Vec2(.8,.6),Vec2(speed,0),Vec3(0,follow*speed/radius,side*speed/radius),service.ball_spec)
        target=Ball('1',cue.position+Vec2(cos(theta),sin(theta))*(2*radius),spec=service.ball_spec)
        variants=[('当前旋转摩擦模型',service.physics,[cue,target]),
                  ('无球球摩擦对照',replace(service.physics,ball_contact_model='frictionless'),[cue,target])]
    else:
        velocity=Vec2(speed*sin(theta),speed*cos(theta))
        def cue(spin):
            return Ball('cue',Vec2(.7,service.table.width-radius),velocity,
                        Vec3(-velocity.y*follow/radius,velocity.x*follow/radius,spin*speed/radius),service.ball_spec)
        variants=[('指定侧旋',service.physics,[cue(side)]),('相反侧旋',service.physics,[cue(-side)]),
                  ('无侧旋对照',service.physics,[cue(0)])]
    output=[]
    for label,physics,balls in variants:
        result=simulate(balls,service.table,physics,max_time=60,max_events=1200)
        first=next((e for e in result.events if e.kind in ('ball_ball','ball_cushion')),None)
        if first is None:
            raise ValueError('初始接触未能解析')
        cue_after=next(b for b in first.after if b.id=='cue')
        metrics={'cue_spin_after_rad_s':cue_after.omega.z,
                 'contact_energy_loss_J':sum(b.energy for b in first.before)-sum(b.energy for b in first.after),
                 'status':result.status,'first_event':first.kind,'surface':first.detail}
        if kind=='ball':
            metrics.update(impact_report(balls[0],balls[1],next(b for b in first.after if b.id=='1'),physics))
        # Include every event timestamp so no rendered chord crosses a cushion.
        times={result.duration*i/240 for i in range(241)}|{e.time for e in result.events}
        times|={min(result.duration,.25)*i/50 for i in range(51)}
        paths={b.id:[] for b in balls}
        for time in sorted(times):
            for b in result.state_at(time):
                if b.pocket is None:
                    paths[b.id].append({'x':b.position.x,'y':b.position.y,'time':time})
        output.append({'label':label,'metrics':metrics,'paths':paths,
                       'initial':[{'id':b.id,'position':{'x':b.position.x,'y':b.position.y},'radius':b.spec.radius} for b in balls],
                       'duration_s':result.duration,'complete':result.status=='stopped'})
    return {'kind':kind,'settings':{'speed':speed,'cut':cut,'follow':follow,'side':side},
            'model_signature':service.signature,'variants':output,
            'initial_state':'接触瞬间的平动与旋转初态；不是从静止出杆的击点参数。',
            'scope':'球球采用三维表面滑速的水平投影；忽略竖直冲量、离台及高低旋向目标球的转移。'}
