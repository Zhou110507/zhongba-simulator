"""Offline-selected opening book. Never inspects the current rack balls."""
from math import atan2,degrees
import json

from .cue import ShotInput

VERSION='random-gap-break-book-v1'


def profiles(service):
    values=[]
    for x in (.25,.50):
        for y in (.16,.40,service.table.width/2,service.table.width-.40,service.table.width-.16):
            for speed,tip,bias in [(5.,t,b) for b in (-.065,-.035,-.018,0.,.018,.035,.065) for t in (0.,.1)]+[(4.5,0.,0.)]:
                angle=degrees(atan2(service.table.width/2+bias-y,service.table.length-.635-x))%360
                values.append({'id':f'break-{len(values)+1}','position':{'x':x,'y':y},
                               'shot':{'angle_deg':angle,'cue_speed':speed,'tip_x':0.,'tip_y':tip}})
    return values


def choose(service, rack_number=1):
    path=service.root/'configs'/'ai_break_model.json'
    data=json.loads(path.read_text(encoding='utf8'))
    if data['version']!=VERSION or data['physics_signature']!=service.signature:
        raise ValueError('离线开球模型与当前球台不匹配，请重新训练开球')
    selected=data['selected']
    return selected[(max(1,rack_number)-1)%len(selected)]


def decide_break(service,state):
    book=choose(service,state.get('rack_number',1))
    # Reading our white ball only checks whether the trained starting position
    # has been placed. Object coordinates, seed and gap size are never read.
    cue=next(b for b in state['scene']['balls'] if b['id']=='cue')
    position=book['position']
    needs_place=any(abs(cue['position'][k]-position[k])>1e-8 for k in ('x','y'))
    action=({'action':'place',**position} if needs_place and state['ball_in_hand']=='head'
            else {'action':'shoot','shot':book['shot']})
    return {'game_id':state['id'],'revision':state['revision'],'status':'found','routes':[],
            'model':VERSION,'action':action,'evaluations':0,'elapsed':0.,
            'break_profile':book['id'],'rack_read':False,
            'message':'调用随机微缝离线训练的开球方案；本局未读取球堆或搜索下球'}
