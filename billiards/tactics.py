"""Learned legal-contact/safety fallback, after the offensive runout search."""
from copy import deepcopy
from dataclasses import asdict
from itertools import product
import json
from math import asin,atan2,cos,degrees,radians,sin,sqrt,pi

import numpy as np

from .cue import ShotInput
from .model import Vec2
from .planner_routes import RAILS,image,segment_distance
from .rules import legal_ids,group
from .runout import Search,shot_options,cluster_pressure
from .shot_prior import contact_cost,planning_policy

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


def direct_contact_rays(service,state):
    """Visible contact intervals, independent of potting lines and cut limits.

    Split each target's angular silhouette at every blocker tangent. Test the
    interval interiors against the actual first sphere intersection, so a
    visible edge counts even when the centre is blocked.
    """
    balls,_=service.decode(state['scene']);cue=next(b for b in balls if b.id=='cue')
    active=[b for b in balls if b.pocket is None and b.id!='cue'];rays=[]
    for target in active:
        if target.id not in legal_ids(state):continue
        delta=target.position-cue.position;distance=delta.norm();radius=cue.spec.radius+target.spec.radius
        if distance<1e-9:continue
        bearing=atan2(delta.y,delta.x);half=asin(min(1.,radius/distance))
        cuts=[-half,0.,half]
        for b in active:
            d=b.position-cue.position;n=d.norm()
            if n<1e-9:continue
            centre=(atan2(d.y,d.x)-bearing+pi)%(2*pi)-pi
            span=asin(min(1.,(cue.spec.radius+b.spec.radius)/n))
            cuts.extend(v for v in (centre-span,centre+span) if -half<v<half)
        cuts=sorted(set(cuts));angles=[0.]+[(a+b)/2 for a,b in zip(cuts,cuts[1:]) if b-a>1e-9]
        found=[]
        for offset in sorted(angles,key=abs):
            u=Vec2(cos(bearing+offset),sin(bearing+offset));hits=[]
            for b in active:
                d=b.position-cue.position;t=d.dot(u);rr=cue.spec.radius+b.spec.radius
                discriminant=rr*rr-max(0.,d.dot(d)-t*t)
                if t>0 and discriminant>1e-14:hits.append((max(0.,t-sqrt(discriminant)),b.id))
            if not hits:continue
            first,key=min(hits);p=cue.position+u*first;r=cue.spec.radius
            if key!=target.id or not (r<=p.x<=service.table.length-r and r<=p.y<=service.table.width-r):continue
            found.append({'angle':degrees(bearing+offset)%360,'rails':0,'clearance':0.,'target':target.id,'length':first})
            if len(found)==3:break
        rays+=found
    return rays


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
    direct=direct_contact_rays(service,state)
    rays=direct or [r for r in kick_rays(service,state) if r['rails']>0]
    rows=[];seen=set();tried=0
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
                first=next((e for e in result.events if e.kind=='ball_ball' and 'cue' in e.actors),None)
                approach=sum(e.kind=='ball_cushion' and 'cue' in e.actors and
                             (first is None or e.time<first.time-1e-9) for e in result.events)
                if direct and approach:continue
                x=tactical_features(service,state,after,shot,result,search.policy)
                secondary=[list(e.actors) for e in result.events if e.kind=='ball_ball' and e is not first]
                first_target=next((i for i in first.actors if i!='cue'),None) if first else None
                cue_others={b if a=='cue' else a for a,b in secondary if 'cue' in (a,b) and first_target not in (a,b)}
                jaws=sum(e.kind=='ball_cushion' and 'cue' in e.actors and e.detail.startswith('jaw:') for e in result.events)
                risk=contact_cost(secondary,first_target,[])+planning_policy()['cue_jaw_contact_cost']*jaws
                if x[1]>0 or x[15]:
                    potted=after['last_decision']['potted']
                    target=next((b for b in result.final if b.id in potted and b.id in legal_ids(state)),None)
                    if cue_others:
                        mine=deepcopy(after);mine['turn']=state['turn']
                        opened=({o['target'] for o in shot_options(service,mine,search.policy)}-
                                {o['target'] for o in shot_options(service,state,search.policy)})&set(legal_ids(state))
                        if not opened:continue
                    margin=search.human_margin(state,shot,target.id,target.pocket,require_leaf=bool(cue_others)) if target else None
                    if not margin or not margin['allowed'] or margin['leaf_passed']<3:continue
                rows.append({'shot':asdict(shot),'x':x.tolist(),'after':after,
                             'human':access,'cushions':int(round(x[11]*8)),
                             'first_contact_cushions':approach,
                             'control_risk':risk,
                             'legal':bool(x[0]) and not bool(x[4]),'pot':bool(x[1]>0 or x[15])})
    return rows


def choose_contact(service,state,*,cancelled=lambda:False,seconds=8,evaluations=450):
    model=TacticModel(service)
    search=Search(service,trained=False,seconds=seconds,evaluations=evaluations,cancelled=cancelled)
    rows=contact_candidates(service,state,search)
    if cancelled():return {'status':'cancelled','routes':[]}
    legal=[r for r in rows if r['legal']]
    pots=[r for r in legal if r['pot']]
    candidates=pots or legal or [r for r in rows if r['after']['winner'] is None] or rows
    if candidates:
        def rank(row):
            x=np.asarray(row['x']);return (row['legal'],model.score(x)+.12*x[8]-.025*x[12]-.2*row.get('control_risk',0.))
        best=max(candidates,key=rank);after=best['after'];x=best['x']
        escape=best['first_contact_cushions']>0
        kind=('kick_attack' if escape else 'attack') if best['pot'] and best['legal'] else ('escape' if escape else 'safety') if best['legal'] else 'best_effort'
        return {'status':'found','routes':[],'model':VERSION,'tactic':kind,
                'action':{'action':'shoot','shot':best['shot']},'evaluations':search.count,
                'predicted_fouls':after['last_decision']['fouls'],'hidden_fraction':x[8],
                'cue_cushions':best['cushions'],'human':best['human'],
                'requires_escape':not bool(direct_contact_rays(service,state)),
                'first_contact_cushions':best['first_contact_cushions'],
                'message':('直打进攻：模拟验证合法进球' if kind=='attack' else
                           '解球进攻：目标球无法直达，经库边触球并合法进球' if kind=='kick_attack' else
                           '解球：目标球无法直达，经库边完成合法触球' if kind=='escape' else
                           '直打防守：目标球可以直接打到，选择合法触球并限制对手进攻' if kind=='safety' else
                           '有限搜索未找到无犯规解法，仍完成当前杆；已明确列出预计犯规，未宣称合法')}
    # Every live, non-cancelled turn still produces a bounded shot. Pathological
    # fully surrounded white balls may foul: never claim guaranteed legality.
    balls,_=service.decode(state['scene']);cue=next(b for b in balls if b.id=='cue')
    target=next((b for b in balls if b.id in legal_ids(state) and b.pocket is None),None)
    direct=direct_contact_rays(service,state)
    angle=direct[0]['angle'] if direct else degrees(atan2(target.position.y-cue.position.y,target.position.x-cue.position.x)) if target else 0.
    return {'status':'found','routes':[],'model':VERSION,'tactic':'best_effort',
            'action':{'action':'shoot','shot':asdict(ShotInput(angle%360,1.1,0.,.5))},
            'evaluations':search.count,'predicted_fouls':['预算内未验证到合法解法'],
            'message':'没有验证到可行水平杆法，仍提交有界尝试；可能犯规，不冒称无犯规解球'}
