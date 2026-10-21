"""Learned legal-contact/safety fallback, after the offensive runout search."""
from copy import deepcopy
from dataclasses import asdict
from itertools import product
import json
from math import atan2,cos,degrees,radians,sin

import numpy as np

from .cue import ShotInput
from .model import Vec2
from .planner_routes import RAILS,image,segment_distance
from .rules import legal_ids,group
from .runout import Search,shot_options,cluster_pressure

VERSION='escape-safety-value-v1'
FEATURES=['legal','own_pots','opponent_pots','scratch','lost','own_options',
          'opponent_options','opponent_best_cost','hidden_fraction','own_cluster_gain',
          'cue_edge','cushions','speed','side','tip','win']


def tactical_features(service,before,after,shot,result,policy):
    owner=before['turn'];mine=deepcopy(after);mine['turn']=owner
    other=deepcopy(after);other['turn']=1-owner
    own=shot_options(service,mine,policy) if after['phase']!='finished' else []
    opponent=shot_options(service,other,policy) if after['phase']!='finished' else []
    balls=[b for b in after['scene']['balls'] if b['pocket'] is None]
    cue=next((b for b in balls if b['id']=='cue'),None)
    targets=[b for b in balls if b['id'] in legal_ids(other)]
    hidden=0
    if cue:
        start=Vec2(**cue['position'])
        for t in targets:
            hidden+=any(b['id'] not in ('cue',t['id']) and
                        segment_distance(Vec2(**b['position']),start,Vec2(**t['position']))<2*service.ball_spec.radius
                        for b in balls)
        p=cue['position'];edge=min(p['x'],service.table.length-p['x'],p['y'],service.table.width-p['y'])
    else:edge=0.
    d=after['last_decision'];chosen=before['groups'][owner]
    mine_pots=sum(i!='cue' and (group(i)==chosen if chosen else i!='8') for i in d['potted'])
    opp_pots=sum(i!='cue' and group(i) not in (chosen,None) for i in d['potted']) if chosen else 0
    gain=cluster_pressure(before)-cluster_pressure(mine)
    x=[not d['fouls'],mine_pots/3,opp_pots/3,'cue' in d['potted'],after['winner']==1-owner,
       min(12,len(own))/12,min(12,len(opponent))/12,
       min(8,opponent[0]['cost'])/8 if opponent else 1.,hidden/max(1,len(targets)),
       gain/5,edge/.6,sum(e.kind=='ball_cushion' and 'cue' in e.actors for e in result.events)/8,
       shot.cue_speed/3.2,abs(shot.tip_x),abs(shot.tip_y),after['winner']==owner]
    return np.asarray(x,dtype=float)


class TacticModel:
    def __init__(self,service):
        from .human_stroke import load_policy
        self.data=json.loads((service.root/'configs'/'ai_tactics_model.json').read_text(encoding='utf8'))
        if self.data['version']!=VERSION or self.data['physics_signature']!=service.signature or self.data['features']!=FEATURES or self.data['human_policy']!=load_policy(service):
            raise ValueError('解球防守模型不匹配，请重新训练')
    def score(self,x):
        d=self.data;z=(x-np.asarray(d['mean']))/np.asarray(d['scale'])
        h=np.tanh(z@np.asarray(d['w1'])+np.asarray(d['b1']))
        return float(1/(1+np.exp(-np.clip(h@np.asarray(d['w2'])+d['b2'],-30,30))))


def kick_rays(service,state,max_rails=3):
    balls,_=service.decode(state['scene']);cue=next(b for b in balls if b.id=='cue')
    radius=cue.spec.radius;bounds=(radius,service.table.length-radius,radius,service.table.width-radius)
    rays=[]
    for target in balls:
        if target.id not in legal_ids(state) or target.pocket is not None:continue
        for count in range(max_rails+1):
            for rails in product(RAILS,repeat=count):
                if any(a==b for a,b in zip(rails,rails[1:])):continue
                virtual=image(target.position,rails,bounds);delta=virtual-cue.position
                if delta.norm()<1e-9:continue
                direction=delta*(1/delta.norm());position=cue.position;points=[position];valid=True
                for expected in rails:
                    hits=[]
                    for name,axis,coord in (('left','x',bounds[0]),('right','x',bounds[1]),('bottom','y',bounds[2]),('top','y',bounds[3])):
                        v=getattr(direction,axis);t=(coord-getattr(position,axis))/v if abs(v)>1e-10 else -1
                        if t>1e-7:hits.append((t,name))
                    if not hits:valid=False;break
                    distance,name=min(hits)
                    if name!=expected:valid=False;break
                    position=position+direction*distance;points.append(position)
                    direction=Vec2(-direction.x,direction.y) if name in ('left','right') else Vec2(direction.x,-direction.y)
                if not valid:continue
                points.append(target.position)
                clearance=min((segment_distance(b.position,a,z)-radius-b.spec.radius
                               for a,z in zip(points,points[1:]) for b in balls
                               if b.id not in ('cue',target.id) and b.pocket is None),default=1.)
                rays.append({'angle':degrees(atan2(delta.y,delta.x))%360,'rails':count,
                             'clearance':clearance,'target':target.id,'length':delta.norm()})
    return sorted(rays,key=lambda r:(r['clearance']<0,r['rails'],-r['clearance'],r['length']))


def contact_candidates(service,state,search,*,attempts=320):
    rays=kick_rays(service,state);rows=[];seen=set();tried=0
    # Guarantee at least one chance to each target and rail count before more
    # tiny variants; negative-clearance rays remain useful for intentional K.
    selected=[];groups=set()
    for ray in rays:
        key=ray['target'],ray['rails']
        if key not in groups:selected.append(ray);groups.add(key)
    selected+= [r for r in rays if r not in selected][:20]
    settings=[(1.8,0.,0.),(2.6,0.,.4),(3.2,.25,.3),(1.1,0.,.5),
              (2.6,-.25,.3),(3.2,0.,-.45),(.8,0.,0.)]
    for offset in (0.,-.5,.5,-1.5,1.5,-3.,3.):
        for speed,side,tip in settings:
            for ray in selected:
                if search.stopped() or tried>=attempts:return rows
                shot=ShotInput((ray['angle']+offset)%360,speed,side,tip)
                key=(round(shot.angle_deg,5),speed,side,tip)
                if key in seen:continue
                seen.add(key);tried+=1
                trial=search.forward(state,shot)
                if trial is None:continue
                result,after,access=trial
                x=tactical_features(service,state,after,shot,result,search.policy)
                rows.append({'shot':asdict(shot),'x':x.tolist(),'after':after,
                             'human':access,'cushions':int(round(x[11]*8)),
                             'legal':bool(x[0]) and not bool(x[4]),'pot':bool(x[1]>0 or x[15])})
    return rows


def choose_contact(service,state,*,cancelled=lambda:False,seconds=12,evaluations=700):
    model=TacticModel(service)
    search=Search(service,trained=False,seconds=seconds,evaluations=evaluations,cancelled=cancelled)
    rows=contact_candidates(service,state,search)
    if cancelled():return {'status':'cancelled','routes':[]}
    legal=[r for r in rows if r['legal']]
    pots=[r for r in legal if r['pot']]
    candidates=pots or legal or [r for r in rows if r['after']['winner'] is None] or rows
    if candidates:
        def rank(row):
            x=np.asarray(row['x']);return (row['legal'],model.score(x)+.12*x[8]-.025*x[12])
        best=max(candidates,key=rank);after=best['after'];x=best['x']
        kind='kick_attack' if best['pot'] and best['legal'] else 'safety' if best['legal'] else 'best_effort'
        return {'status':'found','routes':[],'model':VERSION,'tactic':kind,
                'action':{'action':'shoot','shot':best['shot']},'evaluations':search.count,
                'predicted_fouls':after['last_decision']['fouls'],'hidden_fraction':x[8],
                'cue_cushions':best['cushions'],'human':best['human'],
                'message':('解球进攻：模拟验证合法进球' if kind=='kick_attack' else
                           '解球／防守：模拟验证合法触球，优先限制对手直接进攻' if kind=='safety' else
                           '有限搜索未找到无犯规解法，仍完成当前杆；已明确列出预计犯规，未宣称合法')}
    # Every live, non-cancelled turn still produces a bounded shot. Pathological
    # fully surrounded white balls may foul: never claim guaranteed legality.
    balls,_=service.decode(state['scene']);cue=next(b for b in balls if b.id=='cue')
    target=next((b for b in balls if b.id in legal_ids(state) and b.pocket is None),None)
    angle=degrees(atan2(target.position.y-cue.position.y,target.position.x-cue.position.x)) if target else 0.
    return {'status':'found','routes':[],'model':VERSION,'tactic':'best_effort',
            'action':{'action':'shoot','shot':asdict(ShotInput(angle%360,1.1,0.,.5))},
            'evaluations':search.count,'predicted_fouls':['预算内未验证到合法解法'],
            'message':'没有验证到可行水平杆法，仍提交有界尝试；可能犯规，不冒称无犯规解球'}
