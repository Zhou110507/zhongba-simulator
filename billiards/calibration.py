"""Fit elementary cloth/normal-restitution measurements, without changing profiles."""

from collections import defaultdict
from math import isfinite, sqrt


def number(record,key,minimum=0,positive=False):
    value=record.get(key)
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(f'{key} 必须是有限数值')
    if abs(value)>1e6 or not isfinite(value) or (positive and 0<value<1e-9):
        raise ValueError(f'{key} 数值量级无效')
    if value<minimum or (positive and value==minimum):
        raise ValueError(f'{key} 超出允许范围')
    return value


def fit_measurements(data):
    if not isinstance(data,dict) or data.get('schema_version')!=1:
        raise ValueError('标定文件需要 schema_version=1')
    records=data.get('records')
    if not isinstance(records,list) or not 2<=len(records)<=500:
        raise ValueError('需要 2 到 500 条测量记录')
    source=data.get('source','未说明来源')
    if not isinstance(source,str) or len(source)>2000:
        raise ValueError('来源说明无效')
    groups=defaultdict(list)
    for r in records:
        if not isinstance(r,dict):
            raise ValueError('测量记录必须是对象')
        kind=r.get('kind')
        if kind=='rolling_stop':
            x,y=2*9.81*number(r,'distance_m',positive=True),number(r,'speed_m_s',positive=True)**2
            parameter='rolling_friction'
        elif kind=='slide_to_roll':
            radius=number(r,'radius_m',positive=True)
            speed=number(r,'speed_m_s',positive=True)
            omega=number(r,'forward_omega_rad_s',minimum=-1e6)
            x,y=3.5*9.81*number(r,'time_s',positive=True),abs(speed-radius*omega)
            if y<=1e-9:
                raise ValueError('初态已是纯滚动，不能据此标定滑动摩擦')
            parameter='sliding_friction'
        elif kind=='spin_decay':
            x=number(r,'time_s',positive=True)
            y=number(r,'initial_abs_omega_rad_s',positive=True)-number(r,'final_abs_omega_rad_s',positive=True)
            if y<0:
                raise ValueError('无外力自旋测量不应越转越快')
            parameter='spin_deceleration'
        elif kind=='normal_ball_collision':
            x,y=number(r,'approach_speed_m_s',positive=True),number(r,'separation_speed_m_s')
            if y>x:
                raise ValueError('分离法向相对速度不能大于接近速度')
            parameter='ball_restitution'
        else:
            raise ValueError('未知测量种类；库边能量恢复参数不能直接用法向速度比拟合')
        if not all(isfinite(v) for v in (x,y)) or x>1e8 or y>1e8:
            raise ValueError('测量量级无效')
        groups[parameter].append((x,y))
    estimates={}
    for name,rows in groups.items():
        if len(rows)<2:
            raise ValueError(f'{name} 至少需要两条独立测量')
        value=sum(x*y for x,y in rows)/sum(x*x for x,y in rows)
        if not 0<=value<=({'spin_deceleration':100}.get(name,1)):
            raise ValueError(f'{name} 拟合值超出当前模型允许范围')
        residuals=[y-value*x for x,y in rows]
        estimates[name]={'value':value,'count':len(rows),
                         'residual_rms':sqrt(sum(r*r for r in residuals)/len(rows)),
                         'individual_range':[min(y/x for x,y in rows),max(y/x for x,y in rows)],
                         'residual_definition':'y - fitted_parameter*x in the documented regression coordinates'}
    return {'schema_version':1,'source':source,'data_origin':data.get('data_origin','unknown'),
            'status':'estimates_only_not_applied_or_independently_verified',
            'parameters':{key:value['value'] for key,value in estimates.items()},'estimates':estimates,
            'assumptions':['水平匀质台面；滚动停距样本必须从纯滚动开始。',
                           '滑动恢复样本须测到首次纯滚动且中途无碰撞。',
                           '恢复系数使用两球法向相对速度，不是单球速度比。',
                           '自旋样本的末态仍在转动；不能把已停转后的等待时间算入。',
                           '未自动剔除离群值；残差不等于独立实桌验证精度。']}
