"""Versioned CBSA January 2017 table rules, adjudicated from actual events.

Source: https://cbsa.cssf.net.cn/annoucement/2017/0120/142126.html
Numbers below refer to section III. No called pocket is required, including 8.
"""

from copy import deepcopy
from math import sqrt, cos, sin, pi
import random

from .model import Ball, Vec2
from .pockets import outline

RULE_VERSION='cbsa-2017-01'
RULE_URL='https://cbsa.cssf.net.cn/annoucement/2017/0120/142126.html'
HEAD=.635


def group(ball_id):
    n=int(ball_id)
    return 'solid' if 1<=n<=7 else 'stripe' if 9<=n<=15 else None


def racked_balls(service,seed=0,gap_mm=0):
    """0 = ideal tight rack; positive = explicit, bounded engineering error.

    Dilating by half the maximum gap plus bounded independent radial offsets
    guarantees no overlap. The apex remains exactly on the foot spot.
    """
    if isinstance(gap_mm,bool) or not isinstance(gap_mm,(float,int)) or not 0<=gap_mm<=.5:
        raise ValueError('摆球微隙幅度必须在 0–0.5 mm 内')
    rng=random.Random(seed)
    remaining=[str(n) for n in range(2,15) if n not in (7,8)]
    rng.shuffle(remaining)
    layout=[];iterator=iter(remaining)
    r=service.ball_spec.radius
    for row in range(5):
        for column in range(row+1):
            key=('1' if row==0 else '8' if (row,column)==(2,1) else
                 '7' if (row,column)==(4,0) else '15' if (row,column)==(4,4) else next(iterator))
            half_gap=gap_mm/2000
            pitch=r+half_gap/2
            x=service.table.length-HEAD+row*sqrt(3)*pitch
            y=service.table.width/2+(2*column-row)*pitch
            if row and gap_mm:
                angle=rng.uniform(0,2*pi);offset=rng.uniform(0,half_gap/2)
                x+=offset*cos(angle);y+=offset*sin(angle)
            layout.append(Ball(key,Vec2(x,y),spec=service.ball_spec))
    return [Ball('cue',Vec2(.3,service.table.width/2),spec=service.ball_spec),*layout]


def legal_ids(state):
    balls=[b for b in state['scene']['balls'] if b['id']!='cue' and b['pocket'] is None]
    chosen=state['groups'][state['turn']]
    if chosen is None:return [b['id'] for b in balls if b['id']!='8']
    own=[b['id'] for b in balls if group(b['id'])==chosen]
    return own or ['8']


def _first_contacts(events):
    hits=[e for e in events if e['kind']=='ball_ball' and 'cue' in e['actors']]
    if not hits:return [],None
    time=hits[0]['time']
    return sorted({next(i for i in e['actors'] if i!='cue') for e in hits if abs(e['time']-time)<1e-8}),time


def _new_cushion_contact(event,response,service):
    actor=event['actors'][0]
    ball=next(b for b in response['snapshot']['balls'] if b['id']==actor)
    surface=next((s for s in outline(service.table).surfaces if s.id==event['detail']),None)
    if surface is None:return True
    radius=ball['spec']['radius']+surface.radius
    position=Vec2(**ball['position'])
    if (position-surface.closest(position)).norm()>radius+1e-8:return True
    # A pre-declared frozen ball must leave that cushion before its return counts.
    for segment in response['result']['segments']:
        if segment['start']>=event['time']-1e-10:break
        index=next(i for i,b in enumerate(segment['balls']) if b['id']==actor)
        b=segment['balls'][index];m=segment['motion'][index]
        duration=min(segment['end'],event['time'])-segment['start']
        for dt in (0,duration/2,duration):
            p=Vec2(b['position']['x']+b['velocity']['x']*dt+.5*m['acceleration']['x']*dt*dt,
                   b['position']['y']+b['velocity']['y']*dt+.5*m['acceleration']['y']*dt*dt)
            if (p-surface.closest(p)).norm()>radius+1e-7:return True
    return False


def adjudicate(state,response,service):
    """Pure decision; incomplete physics never changes turn, groups or score."""
    if not response['complete']:raise ValueError('仿真尚未完整结束，本杆不能判罚或推进对局')
    out=deepcopy(state);events=response['result']['events']
    first,hit_time=_first_contacts(events)
    potted=[b['id'] for b in response['result']['final'] if b['pocket'] is not None and
            next(a for a in state['scene']['balls'] if a['id']==b['id'])['pocket'] is None]
    targets=[i for i in potted if i!='cue']
    fouls=[];clauses=[]
    def foul(reason,clause):
        fouls.append(reason);clauses.append(clause)
    if 'cue' in potted:foul('白球落袋','21(a)')
    if not first:foul('未碰到目标球','9.1')
    if first and not state['is_break'] and not set(first)&set(legal_ids(state)):
        foul('首碰非法目标球','7.3 / 9.1 / 10')
    cue=next(b for b in state['scene']['balls'] if b['id']=='cue')
    frozen=[b for b in state['scene']['balls'] if b['id'] in legal_ids(state) and b['pocket'] is None and
            (Vec2(**b['position'])-Vec2(**cue['position'])).norm()<=b['spec']['radius']+cue['spec']['radius']+1e-8]
    for ball in frozen:
        moved=ball['id'] in potted
        for segment in response['result']['segments']:
            b=next(b for b in segment['balls'] if b['id']==ball['id'])
            if segment['end']>segment['start'] and (Vec2(**b['velocity']).norm()>1e-7 or
                    (Vec2(**b['position'])-Vec2(**ball['position'])).norm()>1e-7):moved=True
        final=next(b for b in response['result']['final'] if b['id']==ball['id'])
        moved|=(Vec2(**final['position'])-Vec2(**ball['position'])).norm()>1e-7
        if not moved:foul('与白球相贴的合法目标球未移动','13.1')
    cushion_events=[e for e in events if e['kind']=='ball_cushion' and
                    (hit_time is not None and e['time']>=hit_time-1e-9) and _new_cushion_contact(e,response,service)]
    if not state['is_break'] and hit_time is not None and not targets and not cushion_events:
        foul('触球后无目标球入袋，也没有球有效碰库','9.2 / 13.2 / 15')
    # Head-string ball-in-hand requires an initially forward stroke. Balls behind
    # the string can be contacted only after the cue has crossed it and returned.
    if state['ball_in_hand']=='head':
        initial=next(b for b in response['result']['initial'] if b['id']=='cue')
        if initial['velocity']['x']<=0:foul('线后自由球须向顶库方向击打','5.3 / 5.5')
        if first and all(next(b for b in state['scene']['balls'] if b['id']==i)['position']['x']<HEAD-1e-9 for i in first):
            crossed=False
            for seg in response['result']['segments']:
                if seg['start']>=hit_time:break
                i=next(i for i,b in enumerate(seg['balls']) if b['id']=='cue');b=seg['balls'][i];a=seg['motion'][i]['acceleration']['x']
                dt=min(seg['end'],hit_time)-seg['start'];times=[0,dt]
                if a and 0<-b['velocity']['x']/a<dt:times.append(-b['velocity']['x']/a)
                crossed|=any(b['position']['x']+b['velocity']['x']*t+.5*a*t*t>=HEAD for t in times)
            if not crossed:foul('未越过开球线即击打线后目标球','5.3')
    shooter=state['turn'];other=1-shooter
    out.update(is_break=False,ball_in_hand=None,needs_placement=False,choices=[],chooser=None)
    decision={'shooter':shooter,'first_contacts':first,'potted':potted,'fouls':fouls,'clauses':clauses,
              'outcome':'','winner':None,'respot_eight':False}
    if state['is_break']:
        rails={e['actors'][0] for e in cushion_events if e['actors'][0]!='cue'}
        weak=not targets and len(rails)<4
        decision['break_object_cushions']=len(rails)
        if weak and state['break_warnings'][shooter]:
            out.update(phase='finished',winner=other);decision.update(outcome='被警告后再次未满足合法开球条件，本局判负',winner=other)
        elif weak:
            out.update(phase='choice',chooser=other,choices=['rerack_self','rerack_opponent','accept_free'],turn=other)
            decision['outcome']='开球无目标球入袋且不足四颗目标球碰库，由对手选择'
            fouls.append('未满足合法开球条件');clauses.append('5.1 / 5.2')
        elif '8' in targets:
            decision['respot_eight']=True
            if fouls:
                out.update(phase='choice',chooser=other,turn=other,choices=['accept_head']+([] if 'cue' in potted else ['accept_position']))
                decision['outcome']='开球进8且犯规：重置8号，由对手选择接台或线后自由球'
            else:
                decision['outcome']='合法开球进8：重置8号，开球方继续'
            clauses.append('5.4')
        elif fouls:
            out.update(turn=other,ball_in_hand='head',needs_placement=True)
            decision['outcome']='开球犯规，对手获得线后自由球';clauses.append('5.5')
        else:
            out['turn']=shooter if targets else other
            decision['outcome']='合法开球，球局保持开放；'+('开球方继续' if targets else '换手')
    elif '8' in targets:
        own=legal_ids(state)
        win=own==['8'] and not fouls
        out.update(phase='finished',winner=shooter if win else other)
        decision.update(winner=out['winner'],outcome='合法打进8号，本局获胜' if win else '提前进8或进8同时犯规，本局判负')
        clauses.append('1 / 27')
    elif fouls:
        out.update(turn=other,ball_in_hand='all',needs_placement=True)
        decision['outcome']='犯规，对手获得全台自由球'
    elif state['groups'][shooter] is None:
        valid_groups={group(i) for i in targets if group(i) in {group(j) for j in first}}
        if len(valid_groups)>1:
            out.update(phase='choice',chooser=shooter,choices=['choose_solid','choose_stripe'])
            decision['outcome']='两组同时首碰且均有合法进球，请选择球组'
        elif valid_groups:
            chosen=valid_groups.pop();out['groups'][shooter]=chosen;out['groups'][other]='stripe' if chosen=='solid' else 'solid'
            decision['outcome']='合法进球，确定球组并继续击球';clauses.append('7.2 / 7.5')
        else:
            out['turn']=other;decision['outcome']='开放球局未合法确定球组，换手'
    else:
        keep=any(group(i)==state['groups'][shooter] for i in targets)
        out['turn']=shooter if keep else other
        decision['outcome']='合法进本组球，继续击球' if keep else '本杆结束，换手'
    if out.get('winner') is not None:out['scores'][out['winner']]+=1
    out['last_decision']=decision
    return out


def respot_ball(scene,ball_id,service):
    """Closest clear centre on the spot-to-foot-rail axis, then the other side."""
    balls=scene['balls'];ball=next(b for b in balls if b['id']==ball_id)
    r=service.ball_spec.radius;y=service.table.width/2;foot=service.table.length-HEAD
    candidates={foot,r,service.table.length-r}
    for other in balls:
        if other['id']==ball_id or other['pocket'] is not None:continue
        dy=other['position']['y']-y;diameter=r+other['spec']['radius']
        if abs(dy)<=diameter:
            delta=sqrt(max(0,diameter**2-dy**2))
            candidates.update((other['position']['x']-delta-1e-8,other['position']['x']+delta+1e-8))
    candidates=sorted(candidates,key=lambda x:(x<foot-1e-9,abs(x-foot)))
    for x in candidates:
        if not r<=x<=service.table.length-r:continue
        if all(o['id']==ball_id or o['pocket'] is not None or
               (x-o['position']['x'])**2+(y-o['position']['y'])**2>=(r+o['spec']['radius'])**2-1e-12 for o in balls):
            ball.update(position={'x':x,'y':y},velocity={'x':0,'y':0},omega={'x':0,'y':0,'z':0},pocket=None)
            return
    raise ValueError('置球线上暂时没有可用位置')
