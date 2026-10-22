"""Offline learned stroke ordering. Predictions never replace physical checks."""
import json
import numpy as np

VERSION='human-continuation-prior-v1'
FEATURES=['distance','object_distance','cut','clearance','aim_window','pot_cost',
          'cue_x','cue_y','target_x','target_y','cos','sin','rail_clearance',
          'speed','side','tip','speed_squared','speed_tip','distance_speed',
          'cut_side','object_speed','remaining','cluster_pressure']


def inputs(service,state,option,setting):
    from math import cos,sin,radians
    from .runout import cluster_pressure
    balls={b['id']:b for b in state['scene']['balls']}
    p=balls['cue']['position'];t=balls[option['target']]['position']
    speed,side,tip=setting;angle=radians(option['angle'])
    edge=min(p['x'],p['y'],service.table.length-p['x'],service.table.width-p['y'])
    return [option['distance']/2,option['object_distance']/2,option['cut']/90,
            min(.3,option['clearance'])/.3,min(1,option['aim_half_window_deg']/.3),
            option['cost']/5,p['x']/2.54,p['y']/1.27,t['x']/2.54,t['y']/1.27,
            cos(angle),sin(angle),min(.3,edge)/.3,speed/3.2,side,tip,
            (speed/3.2)**2,speed*tip/3.2,option['distance']*speed/6.4,
            option['cut']*side/90,option['object_distance']/max(.2,speed)/3,
            sum(b['pocket'] is None and b['id']!='cue' for b in balls.values())/15,
            cluster_pressure(state)/10]


class ShotPrior:
    def __init__(self,service):
        path=service.root/'configs'/'ai_shot_prior.json'
        self.data=json.loads(path.read_text(encoding='utf8')) if path.is_file() else None
        if self.data:
            from .human_stroke import load_policy
            d=self.data
            if (d['version']!=VERSION or d['features']!=FEATURES or
                d['physics_signature']!=service.signature or d['human_policy']!=load_policy(service)):
                raise ValueError('出杆先验与当前模型不匹配，请重新训练')
            self.mean=np.asarray(d['mean']);self.scale=np.asarray(d['scale'])
            self.w1=np.asarray(d['w1']);self.b1=np.asarray(d['b1'])
            self.w2=np.asarray(d['w2']);self.b2=d['b2']

    def predict(self,values):
        if not len(values):return np.empty(0)
        if not self.data:return np.zeros(len(values))
        z=(np.asarray(values)-self.mean)/self.scale
        return 1/(1+np.exp(-np.clip(np.tanh(z@self.w1+self.b1)@self.w2+self.b2,-30,30)))


def contact_cost(contacts,first_target,opened_targets):
    """Do not reward a precise collision stop; allow purposeful cluster release."""
    cue_others={b if a=='cue' else a for a,b in contacts
                if 'cue' in (a,b) and first_target not in (a,b)}
    incidental=max(0,len(contacts)-len(cue_others))
    return max(0.,1.2*len(cue_others)+.12*incidental-.45*min(2,len(opened_targets)))


def continuation_cost(next_options,won):
    if won:return 0.
    if not next_options:return 3.5
    best=next_options[0]
    return .5*min(6.,best['cost'])+.5*bool(best['rear_restricted'])
