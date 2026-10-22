"""Human-constrained candidate search and a trained short-runout value model.

The shared physics and CBSA adjudicator certify each searched stroke. The model
only ranks continuation states; it never certifies legality or human feasibility.
"""
from copy import deepcopy
from collections import OrderedDict
from dataclasses import asdict, replace
import json
from math import acos, atan2, cos, degrees, radians, sin
from time import monotonic

import numpy as np

from .cue import ShotInput, strike
from .engine import simulate
from .human_stroke import check_stroke, load_policy
from .model import Vec2, Vec3
from .planner_routes import segment_distance
from .pockets import outline
from .rules import adjudicate, legal_ids
from .shot_difficulty import geometric_tolerance
from .shot_prior import ShotPrior,inputs,contact_cost,continuation_cost,human_pot_cost,planning_policy

FEATURE_NAMES = ['remaining', 'best_distance', 'best_object_distance', 'best_cut',
                 'best_clearance', 'option_count', 'available_targets', 'blocked_fraction',
                 'cue_near_rail', 'cue_x', 'cue_y', 'mean_target_distance',
                 'max_target_distance', 'cluster_pairs', 'black_options', 'black_distance',
                 'second_cost', 'third_cost', 'rear_restricted_fraction', 'best_cost',
                 'best_pot_difficulty', 'best_aim_window', 'best_pocket_alignment',
                 'comfortable_options', 'best_bridge_cost', 'best_long_object_cost']
MODEL_VERSION = 'short-runout-value-v4'


def cluster_pressure(state, exclude=None):
    own=set(legal_ids(state))-{exclude}
    balls=[b for b in state['scene']['balls'] if b['pocket'] is None and b['id'] not in ('cue',exclude)]
    return sum((a['id'] in own or b['id'] in own) and
               ((Vec2(**a['position'])-Vec2(**b['position'])).norm()<.115)
               for i,a in enumerate(balls) for b in balls[i+1:])


def stroke_settings():
    # Interleave firm, soft, high/low and side strokes so a bounded search does
    # not spend its entire budget on gentle centre-ball attempts.
    return [(1.1,0.,0.),(2.2,0.,.5),(2.2,0.,-.45),(1.6,.25,.3),
            (.75,0.,0.),(3.2,0.,.5),(1.6,-.25,-.3),(2.5,0.,0.),
            (1.6,0.,.3),(1.6,0.,-.3),(2.5,.3,.3),(2.5,-.3,.3),
            (1.1,0.,.5),(3.2,.25,.4),(3.2,-.25,.4),(2.5,0.,-.5),
            (1.1,.25,0.),(1.1,-.25,0.)]


def shot_options(service, state, policy):
    balls, _ = service.decode(state['scene'])
    cue = next(b for b in balls if b.id == 'cue')
    if cue.pocket is not None: return []
    options = []
    for target in balls:
        if target.id not in legal_ids(state) or target.pocket is not None: continue
        for pocket in outline(service.table).pockets:
            delta = (pocket.fall_center or pocket.gate)-target.position
            if delta.norm() < 1e-8: continue
            unit = delta*(1/delta.norm())
            ghost = target.position-unit*(cue.spec.radius+target.spec.radius)
            ray = ghost-cue.position
            if ray.norm() < 1e-7: continue
            cosine = max(-1., min(1., ray.dot(unit)/ray.norm()))
            if cosine <= cos(radians(policy['max_cut_degrees'])): continue
            if ray.norm() > policy['max_cue_object_distance_m']: continue
            clearance = min((min(segment_distance(b.position, cue.position, ghost),
                                 segment_distance(b.position, target.position, pocket.mouth))
                             -target.spec.radius-b.spec.radius
                             for b in balls if b.pocket is None and b.id not in ('cue', target.id)), default=.3)
            if clearance < .003: continue
            angle = degrees(atan2(ray.y, ray.x)) % 360
            access = check_stroke(balls, ShotInput(angle, 1., 0., .5), service.table, policy)
            if not access['allowed']: continue
            cut = degrees(acos(cosine))
            if cut>policy['normal_cut_degrees'] and delta.norm()>policy['near_pocket_cut_exception_m']:continue
            pot=geometric_tolerance(pocket.half_width,unit.dot(pocket.outward),cue.spec.radius,
                                    ray.norm(),delta.norm(),cut)
            distance_cost = .30*abs(ray.norm()-policy['preferred_cue_object_distance_m'])
            distance_cost += 2.*max(0., policy['comfortable_min_distance_m']-ray.norm())
            distance_cost += .8*max(0., ray.norm()-policy['comfortable_max_distance_m'])
            edge = min(cue.position.x, service.table.length-cue.position.x,
                       cue.position.y, service.table.width-cue.position.y)
            # Potting accuracy dominates: a near-pocket cut can be easier than
            # a straighter shot sending the object ball across the table.
            bridge_cost=5.*max(0.,policy['comfortable_rail_clearance_m']-edge)+.65*bool(access['notes'])
            long_object_cost=.9*max(0.,delta.norm()-.85)
            cost = 1.8*pot['pot_difficulty']+.65*distance_cost+.25*(1-cosine)+.014/max(.014, clearance)
            cost += bridge_cost+long_object_cost
            options.append({'target': target.id, 'pocket': pocket.id, 'angle': angle,
                            'desired': unit, 'distance': ray.norm(), 'object_distance': delta.norm(),
                            'cut': cut, 'clearance': clearance, 'cost': cost,
                            'rear_restricted': bool(access['notes']),'bridge_cost':bridge_cost,
                            'long_object_cost':long_object_cost,**pot})
    return sorted(options, key=lambda v: (human_pot_cost(v), v['target'], v['pocket']))


def features(service, state, policy, options=None):
    options = shot_options(service, state, policy) if options is None else options
    balls, _ = service.decode(state['scene']); cue = next(b for b in balls if b.id == 'cue')
    own = [b for b in balls if b.id in legal_ids(state) and b.pocket is None]
    targets = [b for b in balls if b.id != 'cue' and b.pocket is None]
    distances = [(b.position-cue.position).norm() for b in own]
    best = options[0] if options else {}
    black_state = deepcopy(state)
    black_state['scene']['balls'] = [b for b in black_state['scene']['balls']
                                    if b['id'] in ('cue', '8') or b['id'] not in legal_ids(state)]
    black_options = shot_options(service, black_state, policy) if state['groups'][state['turn']] else []
    black = next((b for b in targets if b.id == '8'), None)
    rail = min(cue.position.x, service.table.length-cue.position.x, cue.position.y, service.table.width-cue.position.y)
    costs = [o['cost'] for o in options]
    values = [len(own)/4, best.get('distance', 2.54)/2.54, best.get('object_distance', 2.54)/2.54,
              best.get('cut', 90)/90, min(.3, best.get('clearance', 0))/.3,
              min(12, len(options))/12, len({o['target'] for o in options})/max(1, len(own)),
              1-len({o['target'] for o in options})/max(1, len(own)),
              max(0., .18-rail)/.18, cue.position.x/service.table.length, cue.position.y/service.table.width,
              sum(distances)/max(1, len(distances))/2.54, max(distances, default=0)/2.54,
              sum((a.position-b.position).norm() < .14 for i, a in enumerate(targets) for b in targets[i+1:])/10,
              min(6, len(black_options))/6, (black.position-cue.position).norm()/2.54 if black else 0,
              costs[1]/3 if len(costs)>1 else 1, costs[2]/3 if len(costs)>2 else 1,
              sum(o['rear_restricted'] for o in options)/max(1, len(options)), best.get('cost', 3)/3,
              best.get('pot_difficulty',3)/3,min(1.,best.get('aim_half_window_deg',0.)/.3),
              best.get('pocket_entry_cosine',0.),
              sum(o['cost']<2.5 and not o['rear_restricted'] and .18<=o['distance']<=1.2 for o in options)/max(1,len(options)),
              best.get('bridge_cost',1.),best.get('long_object_cost',1.)]
    return np.asarray(values, dtype=float)


class ValueModel:
    def __init__(self, service):
        import json
        path = service.root/'configs'/'ai_value_model.json'
        self.data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        if self.data and (self.data['version'] != MODEL_VERSION or self.data['features'] != FEATURE_NAMES
                          or self.data['physics_signature'] != service.signature
                          or self.data['human_policy'] != load_policy(service)):
            raise ValueError('AI 训练模型与当前物理或出杆限制不匹配，请重新训练')

    def score(self, x):
        if self.data is None: return 0.
        d = self.data
        z = (x-np.asarray(d['mean']))/np.asarray(d['scale'])
        hidden = np.tanh(z@np.asarray(d['w1'])+np.asarray(d['b1']))
        return float(1/(1+np.exp(-np.clip(hidden@np.asarray(d['w2'])+d['b2'], -30, 30))))


class Search:
    def __init__(self, service, *, seconds=30, evaluations=1800, cancelled=lambda: False,
                 progress=lambda value: None, trained=True, use_prior=True):
        self.service = service; self.policy = load_policy(service)
        self.model = ValueModel(service) if trained else None
        self.prior = ShotPrior(service) if trained and use_prior else None
        self.started = monotonic(); self.deadline = self.started+seconds
        self.search_deadline = self.deadline-min(3., seconds*.2)
        self.cap = evaluations; self.count = 0; self.cancelled = cancelled; self.progress = progress
        self.search_cap = self.cap-min(24, self.cap//4)
        self.rejected = {}; self.expanded = 0
        self.forecasts={}
        self.simulations=OrderedDict();self.reused_simulations=0
        self.aimed_trials={};self.margin_trials={};self.reused_candidate_trials=0

    def stopped(self):
        return self.cancelled() or monotonic() >= self.deadline or self.count >= self.cap

    def forward(self, state, shot, *, opening=False):
        if self.stopped(): return None
        balls, _ = self.service.decode(state['scene'])
        access = check_stroke(balls, shot, self.service.table, self.policy)
        if opening:
            # Break uses the same rear-space restrictions, with a separate speed cap.
            access = check_stroke(balls, replace(shot, cue_speed=min(shot.cue_speed, 2.5)), self.service.table, self.policy)
        if not access['allowed']:
            for reason in access['reasons']: self.rejected[reason] = self.rejected.get(reason, 0)+1
            return None
        # Repeated aiming corrections/pocket variants can request the exact
        # same stroke. Cache only within this immutable search, with rules and
        # the complete source state in the key; never approximate ball positions.
        key=(json.dumps(state,sort_keys=True),shot,opening)
        if key in self.simulations:
            result,after,saved_access=self.simulations[key]
            self.simulations.move_to_end(key);self.reused_simulations+=1
            return result,deepcopy(after),deepcopy(saved_access)
        cue = next(b for b in balls if b.id == 'cue')
        launched = strike(cue, shot, self.service.cue)
        result = simulate(tuple(launched if b.id == 'cue' else b for b in balls), self.service.table,
                          self.service.physics, max_time=60, max_events=6000, record_segments=False,
                          cancel=lambda: self.cancelled() or monotonic() >= self.deadline)
        self.count += 1
        if result.status != 'stopped':
            reason = 'simulation:'+result.status
            self.rejected[reason] = self.rejected.get(reason, 0)+1
            return None
        final = tuple(replace(b, velocity=Vec2(), omega=Vec3()) for b in result.final)
        response = {'complete': True, 'snapshot': self.service.snapshot(balls, shot),
                    'result': result.to_dict(None, compact=True)}
        after = adjudicate(state, response, self.service)
        after['scene'] = self.service.snapshot(final, shot)
        self.simulations[key]=(result,deepcopy(after),deepcopy(access))
        if len(self.simulations)>24:self.simulations.popitem(last=False)
        return result, after, access

    def human_margin(self,state,shot,target,pocket,*,require_leaf=False):
        policy=planning_policy();key=(json.dumps(state,sort_keys=True),shot,target,pocket,require_leaf)
        if key in self.margin_trials:return self.margin_trials[key]
        angle=policy['angle_probe_deg'];spread=policy['speed_probe_fraction']
        balls,_=self.service.decode(state['scene'])
        access=check_stroke(balls,shot,self.service.table,self.policy)
        upper=self.policy['rail_max_cue_speed_mps'] if access['notes'] else self.policy['max_normal_cue_speed_mps']
        passed=leaves=0
        for da,ds in ((-angle,1.),(angle,1.),(0.,1-spread),(0.,1+spread)):
            if self.stopped():return None
            trial=self.forward(state,replace(shot,angle_deg=(shot.angle_deg+da)%360,cue_speed=min(upper,shot.cue_speed*ds)))
            if trial is None:continue
            result,after,_=trial
            ball=next(b for b in result.final if b.id==target)
            valid=ball.pocket==pocket and not after['last_decision']['fouls'] and after['winner'] in (None,state['turn'])
            passed+=bool(valid)
            if valid:
                options=shot_options(self.service,after,self.policy) if after['winner'] is None else []
                leaves+=bool(after['winner']==state['turn'] or any(o['aim_half_window_deg']>=.03 and not o['rear_restricted'] and .18<=o['distance']<=1.2 for o in options))
        value={'pot_passed':passed,'leaf_passed':leaves,'checked':4,
               'allowed':passed==4 and (not require_leaf or leaves==4),
               'angle_deg':angle,'speed_fraction':spread,'not_human_probability':True}
        self.margin_trials[key]=value
        return value

    def aimed(self,state,option,speed,tip_y,tip_x=0.):
        key=(json.dumps(state,sort_keys=True),option['target'],option['pocket'],option['angle'],option['desired'],speed,tip_y,tip_x)
        if key in self.aimed_trials:
            self.reused_candidate_trials+=1
            return deepcopy(self.aimed_trials[key])
        value=self._aimed(state,option,speed,tip_y,tip_x)
        if not self.stopped():self.aimed_trials[key]=deepcopy(value)
        return value

    def _aimed(self, state, option, speed, tip_y, tip_x=0.):
        if option['aim_half_window_deg']<planning_policy()['minimum_aim_half_window_deg']:return None
        angle = option['angle']; previous = None; best = None
        for _ in range(3):
            shot = ShotInput(angle % 360, speed, tip_x, tip_y)
            trial = self.forward(state, shot)
            if trial is None: break
            result, after, access = trial
            event = next((e for e in result.events if e.kind == 'ball_ball' and 'cue' in e.actors), None)
            if not event or option['target'] not in event.actors: break
            target = next(b for b in result.final if b.id == option['target'])
            cue = next(b for b in result.final if b.id == 'cue')
            d = after['last_decision']
            cue_hits=[e for e in result.events if e.kind=='ball_ball' and 'cue' in e.actors]
            target_hits=[e for e in result.events if e.kind=='ball_ball' and option['target'] in e.actors]
            banks=sum(e.kind=='ball_cushion' and 'cue' in e.actors for e in result.events)
            simple=(self.policy['allow_secondary_ball_contacts'] or len(cue_hits)==len(target_hits)==1)
            simple &= banks<=self.policy['max_normal_cushions']
            if simple and target.pocket == option['pocket'] and not d['fouls'] and (
                    after['turn'] == state['turn'] and after['phase'] == 'playing'
                    or after['winner'] == state['turn']):
                pocket=next(p for p in outline(self.service.table).pockets if p.id==target.pocket)
                jaw_hits=sum(e.kind=='ball_cushion' and option['target'] in e.actors and e.detail.startswith('jaw:') for e in result.events)
                entry=next(e for e in result.events if e.kind=='ball_pocket' and option['target'] in e.actors)
                entry_ball=next(b for b in entry.before if b.id==option['target'])
                offset=abs((entry_ball.position-pocket.mouth).dot(pocket.tangent))
                pocket_cost=self.policy['jaw_contact_cost']*min(2,jaw_hits)+self.policy['pocket_offset_cost']*min(1.,offset/pocket.half_width)
                step = {'target': option['target'], 'pocket': target.pocket, 'shot': asdict(shot),
                        'cue_final': asdict(cue.position), 'cut_degrees': round(option['cut'], 1),
                        'distance_mm': round(option['distance']*1000), 'human': access,
                        'object_distance_mm':round(option['object_distance']*1000),
                        'aim_half_window_deg':round(option['aim_half_window_deg'],4),
                        'pot_difficulty':round(option['pot_difficulty'],5),
                        'potted': d['potted'], 'verified': True,
                        'cue_cushions':banks,'cue_ball_contacts':len(cue_hits),
                        'jaw_contacts':jaw_hits,'clean_pot':jaw_hits==0,'pocket_offset_mm':round(offset*1000,2),
                        'pocket_entry_cost':round(pocket_cost,5),
                        'position_effort':round(.035*speed+.08*abs(tip_y)+.16*abs(tip_x)+.025*banks,5),
                        'cost': human_pot_cost(option)+.035*speed+.08*abs(tip_y)+.16*abs(tip_x)+.025*banks+pocket_cost}
                contacts=[list(e.actors) for e in result.events if e.kind=='ball_ball' and e is not event and e.time>=event.time]
                gain=max(0,cluster_pressure(state,option['target'])-cluster_pressure(after,option['target'])) if contacts else 0
                next_options=shot_options(self.service,after,self.policy) if after['winner'] is None else []
                before_options=shot_options(self.service,state,self.policy) if contacts else []
                opened=sorted(({o['target'] for o in next_options}-{o['target'] for o in before_options}-{option['target']})&set(legal_ids(state)),key=int) if contacts else []
                cue_others={b if a=='cue' else a for a,b in contacts if 'cue' in (a,b) and option['target'] not in (a,b)}
                cue_jaws=sum(e.kind=='ball_cushion' and 'cue' in e.actors and e.detail.startswith('jaw:') for e in result.events)
                collision_cost=contact_cost(contacts,option['target'],opened)
                link_cost=continuation_cost(next_options,after['winner']==state['turn'])
                margin=self.human_margin(state,shot,option['target'],target.pocket,require_leaf=bool(cue_others)) if not cue_others or opened else None
                step.update(secondary_contacts=contacts,breakout_gain=gain,opened_targets=opened,cue_jaw_contacts=cue_jaws,human_margin=margin,
                            contact_cost=collision_cost,continuation_cost=link_cost)
                step['cost']+=collision_cost+link_cost+planning_policy()['cue_jaw_contact_cost']*cue_jaws+planning_policy()['object_jaw_contact_cost']*jaw_hits
                step['next_shot']=({k:next_options[0][k] for k in ('target','pocket','cost','distance','object_distance','cut','rear_restricted')}
                                   if next_options else None)
                key=len(self.forecasts);self.forecasts[key]=(state,after);step['_forecast_key']=key
                if margin and margin['allowed']:best = (after, step)
            outgoing = next(b for b in event.after if b.id == option['target']).velocity
            if outgoing.norm() < 1e-8: break
            desired = option['desired']
            error = degrees(atan2(outgoing.x*desired.y-outgoing.y*desired.x, outgoing.dot(desired)))
            if abs(error) < .015: break
            if previous is None:
                previous = (angle, error); angle += .035
            else:
                old_angle, old_error = previous
                derivative = (error-old_error)/(angle-old_angle) if abs(angle-old_angle)>1e-9 else 0
                previous = (angle, error)
                angle += max(-.4, min(.4, -error/derivative)) if abs(derivative)>1e-6 else .035
        return best

    def candidates(self, state, *, attempts=48):
        options = shot_options(self.service, state, self.policy)
        # Reserve an option for each legal target, then add alternative pockets.
        chosen = []; seen = set()
        for o in options:
            if o['target'] not in seen: chosen.append(o); seen.add(o['target'])
        for o in options:
            if o not in chosen: chosen.append(o)
        chosen = chosen[:max(6,len(seen))]
        # Keep off-centre alternatives, but certify their margin and charge
        # explicit object-jaw and cue-jaw risks before recommending them.
        biased=[]
        for base in options[:2]:
            pocket=next(p for p in outline(self.service.table).pockets if p.id==base['pocket'])
            target=next(b for b in self.service.decode(state['scene'])[0] if b.id==base['target'])
            for offset in (-.012,.012):
                delta=(pocket.fall_center or pocket.gate)+pocket.tangent*offset-target.position
                biased.append({**base,'desired':delta*(1/delta.norm()),'pocket_bias_m':offset})
        settings = stroke_settings()
        pool = []; tried = 0
        tasks=[(o,(speed,side,tip)) for index,(speed,side,tip) in enumerate(settings)
               for o in chosen+(biased if index==5 else [])]
        if self.prior and self.prior.data:
            values=self.prior.predict([inputs(self.service,state,o,s) for o,s in tasks])
            ranked=sorted(zip(values,tasks),key=lambda v:-v[0])
            # Reserve exploration for each target/pocket, then use learned order.
            selected=[];lines=set()
            for _,task in ranked:
                key=task[0]['target'],task[0]['pocket']
                if key not in lines:selected.append(task);lines.add(key)
            tasks=selected+[task for _,task in ranked if task not in selected]
        for o,(speed,tip_x,tip_y) in tasks:
            if self.stopped() or self.count >= self.search_cap or tried >= attempts:return pool
            tried+=1
            value=self.aimed(state,o,speed,tip_y,tip_x)
            if value is not None:
                after,step=value
                if after['winner']==state['turn'] or step['human_margin']['leaf_passed']>=3:pool.append(value)
                else:self.rejected['human:fragile_next_position']=self.rejected.get('human:fragile_next_position',0)+1
        return pool

    def position_value(self, state):
        if state['phase'] == 'finished': return 10. if state['winner'] == state['turn'] else -10.
        options = shot_options(self.service, state, self.policy)
        if not options: return -4.
        heuristic = -options[0]['cost']+.12*min(3, len({o['target'] for o in options}))
        if self.model and self.model.data:
            heuristic += 1.5*self.model.score(features(self.service, state, self.policy, options))
        return heuristic

    def route_cost(self, entry):
        state,path,total=entry
        hardest=max((s['cost']-s['position_effort'] for s in path),default=0.)
        leaves=[s['next_shot']['cost'] for s in path if s['next_shot']]
        # A cheap current stroke must pay for the awkward next shot it leaves.
        # Extra rails/spin remain a small tie-breaker, not a hard preference.
        return total/max(1,len(path))+.65*hardest+.25*sum(leaves)/max(1,len(leaves))-.65*self.position_value(state)

    def plan(self,state,*,max_depth=None):
        result=self.solve(state,max_depth=max_depth)
        # Latency is not a reason to publish a shallower plan. Continue once
        # with the same exact candidate cache if the first budget stopped short.
        if (result.get('routes') and not result.get('horizon_complete',True) and not self.cancelled()
                and (self.stopped() or monotonic()>=self.search_deadline)):
            duration=self.deadline-self.started
            self.deadline=self.started+2*duration;self.search_deadline=self.deadline-3.
            self.cap*=2;self.search_cap=self.cap-24
            forecasts=result.get('_forecasts')
            if forecasts and forecasts[0]:
                # Preserve the certified prefix; spend the extra budget at its
                # endpoint instead of widening the root for a second time.
                from .ai_rolling import append
                anchor=forecasts[0][-1][1]
                requested=result['requested_depth']
                before_count=self.count
                suffix=self.solve(anchor,max_depth=max(1,requested-result['verified_depth']))
                if self.cancelled():return {**suffix,'continued_for_horizon':True}
                suffix['evaluations']=self.count-before_count
                combined=append(result,suffix,anchor)
                if combined:result=combined
                actual=len(result['routes'][0]['steps'])
                done=result['routes'][0]['clear_verified'] or actual>=requested
                result.update(requested_depth=requested,verified_depth=actual,horizon_complete=done,
                              horizon_limit=None if done else suffix['horizon_limit'],
                              evaluations=self.count,elapsed=round(monotonic()-self.started,2),
                              reused_simulations=self.reused_simulations,reused_candidate_trials=self.reused_candidate_trials)
            else:result=self.solve(state,max_depth=max_depth)
            result['continued_for_horizon']=True
        return result

    def solve(self, state, *, max_depth=None):
        owner = state['turn']; own = legal_ids(state)
        endgame = state['groups'][owner] is not None and len(own) <= 3
        depth = (1 if own == ['8'] else len(own)+1) if endgame else 3
        if max_depth is not None:depth=min(depth,max(1,max_depth))
        frontier = [(state, [], 0.)]; paths = []; complete = []
        # Establish a full-depth seed before spending the budget widening the
        # beam. Learned order saves work; it must never lower the target depth.
        seed_deadline=self.started+(self.deadline-self.started)*.45
        def seed(node,path,total):
            if len(path)>=depth or node['winner']==owner:return True
            if self.stopped() or monotonic()>=seed_deadline:return False
            pool=self.candidates(node,attempts=12)
            ranked=[]
            for after,step in pool:
                entry=(after,path+[step],total+step['cost']);paths.append(entry)
                if after['winner']==owner:complete.append(entry)
                elif after['turn']!=owner or after['phase']!='playing':continue
                ranked.append(entry)
            ranked.sort(key=self.route_cost)
            for after,route,cost in ranked[:2]:
                if seed(after,route,cost):return True
            return False
        seed(state,[],0.)
        for level in range(depth):
            expanded = []
            for node, path, cost in frontier:
                if self.stopped() or monotonic() >= self.search_deadline: break
                self.expanded += 1
                candidates = self.candidates(node, attempts=72 if level == 0 else 36)
                for after, step in candidates:
                    route = path+[step]; total = cost+step['cost']
                    entry = (after, route, total)
                    paths.append(entry)
                    if after['winner'] == owner: complete.append(entry)
                    elif after['turn'] == owner and after['phase'] == 'playing': expanded.append(entry)
                self.progress({'stage': f'规划第 {level+1} 杆 · 检查出杆空间与续接',
                               'evaluations': self.count, 'depth': level+1,
                               'elapsed': round(monotonic()-self.started, 1)})
            if complete or not expanded: break
            expanded.sort(key=lambda n: (-len(n[1]), self.route_cost(n)))
            frontier = []; signatures = set();first_lines={}
            for entry in expanded:
                # Keep distinct ball orders and stroke choices; don't fill the beam
                # with almost identical first-stroke variants.
                route = entry[1]
                endpoint=next(b['position'] for b in entry[0]['scene']['balls'] if b['id']=='cue')
                signature = (tuple((s['target'],s['pocket']) for s in route),
                             tuple(round(route[0]['shot'][k],1) for k in ('tip_x','tip_y','cue_speed')),
                             round(endpoint['x'],1),round(endpoint['y'],1))
                if signature in signatures: continue
                first_line=(route[0]['target'],route[0]['pocket'])
                if first_lines.get(first_line,0)>=2:continue
                first_lines[first_line]=first_lines.get(first_line,0)+1
                signatures.add(signature); frontier.append(entry)
                if len(frontier) == 6: break
            if self.stopped() or monotonic() >= self.search_deadline: break
        longest=max((len(p[1]) for p in paths),default=0)
        candidates = complete or [p for p in paths if len(p[1])==longest]
        candidates.sort(key=lambda n:(not n[0]['winner']==owner,self.route_cost(n)))
        routes = []; keys = set();forecasts=[]
        for after, path, cost in candidates:
            key = tuple((s['target'],s['pocket']) for s in path)
            if key in keys: continue
            keys.add(key)
            clear = after['winner'] == owner
            reasons = ['每杆通过当前物理模型与中八规则检查；使用普通水平杆法限制']
            reasons.append('综合当前进球、下一球好打度与走位代价；允许五库内及适度加塞换取更舒服的续接')
            if clear and len(path)>1: reasons.append(f'保留 {path[-2]["target"]} 号作为黑八连接球')
            if any(s['human']['notes'] for s in path): reasons.append('近库杆采用高杆限制；未用低杆强拉')
            if any(s['secondary_contacts'] for s in path):reasons.append('优先不借碰的自然走位；借碰增加不确定性代价，仅在打开堵球等收益足够时采用')
            if not clear: reasons.append('这是预算内找到的部分路线，后续需根据实际落点重算')
            forecasts.append([self.forecasts[s['_forecast_key']] for s in path])
            routes.append({'steps': [{k:v for k,v in s.items() if k!='_forecast_key'} for s in path], 'clear_verified': clear, 'reasons': reasons,
                           'mean_cost': round(cost/len(path), 4),
                           'max_shot_cost':round(max(s['cost']-s['position_effort'] for s in path),4),
                           'mean_position_effort':round(sum(s['position_effort'] for s in path)/len(path),4)})
            if len(routes) == 3: break
        # Joint legality/continuation checks are discrete engineering probes,
        # never a calibrated human success probability. Check every stroke in
        # the preferred route, including human access at the perturbed endpoint.
        if routes and not self.stopped():
            route=routes[0]; node=state; passed=checked=0; expected=4*len(route['steps'])
            for index,step in enumerate(route['steps']):
                original=ShotInput(**step['shot'])
                for da,ds in ((-.05,1.),(.05,1.),(0.,.98),(0.,1.02)):
                    if self.stopped():break
                    trial=self.forward(node,replace(original,angle_deg=original.angle_deg+da,cue_speed=original.cue_speed*ds))
                    checked+=1
                    if trial is None:continue
                    result,after,_=trial
                    target=next(b for b in result.final if b.id==step['target'])
                    valid=not after['last_decision']['fouls'] and target.pocket==step['pocket']
                    if not self.policy['allow_secondary_ball_contacts']:
                        valid &= sum(e.kind=='ball_ball' and 'cue' in e.actors for e in result.events)==1
                        valid &= sum(e.kind=='ball_ball' and step['target'] in e.actors for e in result.events)==1
                    valid &= after['winner'] in (None,state['turn'])
                    valid &= sum(e.kind=='ball_cushion' and 'cue' in e.actors for e in result.events)<=self.policy['max_normal_cushions']
                    if index+1<len(route['steps']):
                        options=shot_options(self.service,after,self.policy)
                        # Require an accessible continuation with a modest angle,
                        # moderate distance and room away from the cushion.
                        cue=next(b for b in result.final if b.id=='cue')
                        edge=min(cue.position.x,self.service.table.length-cue.position.x,
                                 cue.position.y,self.service.table.width-cue.position.y)
                        valid &= any(o['cut']<=50 and .18<=o['distance']<=1.2 and not o['rear_restricted']
                                     for o in options) and edge>=.07
                    passed+=bool(valid)
                node=forecasts[0][index][1]  # exact stroke was already certified
            route['perturbations']={'passed':passed,'checked':checked,'expected':expected,
                                    'complete':checked==expected,'not_human_probability':True,
                                    'definition':'Individual angle +/-0.05 degrees and cue speed +/-2%; actual legal pot plus an accessible moderate continuation. Not a joint full-route probability.'}
        return {'status': 'cancelled' if self.cancelled() else 'found' if routes else 'not_found',
                'routes': [] if self.cancelled() else routes, 'endgame': endgame,
                'model': self.model.data['version'] if self.model and self.model.data else 'heuristic-baseline',
                'evaluations': self.count, 'elapsed': round(monotonic()-self.started, 2),
                'reused_simulations':self.reused_simulations,
                'reused_candidate_trials':self.reused_candidate_trials,
                'requested_depth':depth,'verified_depth':len(routes[0]['steps']) if routes else 0,
                'horizon_complete':bool(routes and (routes[0]['clear_verified'] or len(routes[0]['steps'])>=depth)),
                'horizon_limit':None if routes and (routes[0]['clear_verified'] or len(routes[0]['steps'])>=depth) else 'budget_exhausted' if self.stopped() or monotonic()>=self.search_deadline else 'no_robust_continuation_found',
                'human_policy': self.policy['version'], 'rejected_strokes': self.rejected,
                '_forecasts':forecasts,
                'scope': 'simulation-trained ranking; ordinary horizontal strokes; no professional success claim'}
