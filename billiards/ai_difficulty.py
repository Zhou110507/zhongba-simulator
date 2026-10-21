"""Four execution skills sharing one planner; never search for a lucky error."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import random

from .cue import ShotInput
from .human_stroke import check_stroke,load_policy

DEFAULT_LEVEL='expert'
LEVELS=('novice','intermediate','advanced','expert')


def validate_level(value):
    if not isinstance(value,str) or value not in LEVELS:raise ValueError('请选择有效的 AI 档位')
    return value


def configuration(service):
    return json.loads((service.root/'configs'/'ai_difficulty.json').read_text(encoding='utf8'))


def realize(service,state,planned):
    config=configuration(service);level=validate_level(state.get('ai_level',DEFAULT_LEVEL));profile=config['levels'][level]
    shot=ShotInput(**planned)
    report={'version':config['version'],'level':level,'label':profile['label'],
            'angle_sigma_deg':profile['angle_sigma_deg'],'speed_sigma_fraction':profile['speed_sigma_fraction'],
            'planned_shot':deepcopy(planned),'actual_shot':deepcopy(planned),
            'angle_error_deg':0.,'speed_error_fraction':0.,'speed_error_mps':0.,
            'angle_projection_scale':1.,'speed_bound_redraws':0}
    if level==DEFAULT_LEVEL:return deepcopy(planned),report
    # Stable across job IDs, preview/cancel/rethink, and incomplete-shot retries.
    # This identity never includes rack coordinates, potting or future outcomes.
    key=[config, state.get('ai_noise_seed',state['id']),state['rack_number'],
         state['revision'],state['ai_player'],level,planned]
    draw_key=sha256(json.dumps(key,sort_keys=True).encode()).hexdigest()
    rng=random.Random(draw_key);raw_angle=rng.gauss(0,profile['angle_sigma_deg'])
    balls,_=service.decode(state['scene']);policy=load_policy(service)
    def geometry(angle):
        return check_stroke(balls,replace(shot,angle_deg=angle,cue_speed=min(1.,shot.cue_speed)),service.table,policy)
    base=geometry(shot.angle_deg);scale=1.
    access=geometry(shot.angle_deg+raw_angle)
    if base['allowed']:
        while not access['allowed'] and scale>2**-20:
            scale*=.5;access=geometry(shot.angle_deg+raw_angle*scale)
        if not access['allowed']:scale=0.;access=base
    upper=service.cue.max_speed if state['is_break'] else min(service.cue.max_speed,policy['max_normal_cue_speed_mps'])
    if access['notes']:upper=min(upper,policy['rail_max_cue_speed_mps'])
    # Rejection only enforces parameter bounds; physics is simulated exactly once
    # by GameStore afterwards, regardless of whether the ball will be potted.
    speed=-1.;redraws=0
    while not 0<speed<=upper:
        speed=shot.cue_speed*(1+rng.gauss(0,profile['speed_sigma_fraction']));redraws+=1
        if redraws>10000:raise ValueError('AI 计划杆速与允许范围不一致')
    angle_error=raw_angle*scale
    actual={**planned,'angle_deg':(shot.angle_deg+angle_error)%360,'cue_speed':speed}
    report.update(draw_key=draw_key,actual_shot=deepcopy(actual),raw_angle_error_deg=raw_angle,
                  angle_error_deg=angle_error,angle_projection_scale=scale,speed_upper_mps=upper,
                  speed_error_fraction=speed/shot.cue_speed-1,speed_error_mps=speed-shot.cue_speed,
                  speed_bound_redraws=redraws-1)
    return actual,report
