"""Strict whole-table continuation reuse; prediction never commits game state."""
from copy import deepcopy
import hashlib


def model_stamp(service):
    value=hashlib.sha256(service.signature.encode())
    for name in ('ai_human_policy.json','ai_value_model.json','ai_tactics_model.json','ai_break_model.json'):
        path=service.root/'configs'/name
        if path.is_file():value.update(path.read_bytes())
    return value.hexdigest()


def matches(expected,actual,tolerance=1e-6):
    # Never reuse just because the white ball matches: a K can move an opponent,
    # a pocketed ball or black-eight enough to invalidate the rest of a plan.
    keys=('id','turn','phase','groups','winner','is_break','ball_in_hand','needs_placement',
          'ai_player','rule_version','rack_number','break_warnings')
    if any(expected.get(k)!=actual.get(k) for k in keys):return False
    if expected['scene']['model_signature']!=actual['scene']['model_signature']:return False
    left={b['id']:b for b in expected['scene']['balls']};right={b['id']:b for b in actual['scene']['balls']}
    if left.keys()!=right.keys():return False
    for key,a in left.items():
        b=right[key]
        if a.get('pocket')!=b.get('pocket'):return False
        if a['spec']!=b['spec']:return False
        for field,axes in (('position',('x','y')),('velocity',('x','y')),('omega',('x','y','z'))):
            if any(abs(a[field][axis]-b[field][axis])>tolerance for axis in axes):return False
    return True


def continuation(analysis,actual):
    routes=analysis.get('routes',[]);forecasts=analysis.get('_forecasts',[])
    if not routes or not forecasts or len(routes[0]['steps'])<2 or len(forecasts[0])<2:return None
    if not matches(forecasts[0][0][1],actual):return None
    route=deepcopy(routes[0]);route['steps']=route['steps'][1:]
    route['reasons'].append('所有球位及规则状态与预测相符，复用已验证后续路线')
    route.pop('perturbations',None)
    route['mean_cost']=sum(s['cost'] for s in route['steps'])/len(route['steps'])
    next_analysis={k:deepcopy(v) for k,v in analysis.items() if k not in ('routes','_forecasts','action')}
    next_analysis.update(game_id=actual['id'],revision=actual['revision'],routes=[route],
                         action={'action':'shoot','shot':deepcopy(route['steps'][0]['shot'])},
                         evaluations=0,elapsed=0.,cache_hit=True,
                         cached_from_evaluations=analysis.get('cached_from_evaluations',analysis.get('evaluations',0)),
                         _forecasts=[forecasts[0][1:]])
    return next_analysis


def public_analysis(analysis):
    return deepcopy({k:v for k,v in analysis.items() if not k.startswith('_')})
