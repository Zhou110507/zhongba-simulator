"""Extend only the unsearched endpoint of an already verified shot queue."""
from copy import deepcopy
from time import monotonic

from .ai_cache import matches
from .rules import legal_ids
from .runout import Search

HORIZON=3
TACTICS=('attack','kick_attack','safety','escape','best_effort')


def readiness(analysis,state):
    """A shot consumes a queue slot only after the verified horizon is full."""
    action=analysis.get('action',{});routes=analysis.get('routes',[])
    # A tactical pot is a single stroke, just like a safety or escape. It does
    # not promise a runout queue. Never exempt an incomplete offensive route.
    if action.get('action')!='shoot' or state['is_break'] or (not routes and analysis.get('tactic') in TACTICS):
        return {'ready':True,'required':0,'available':0,'kind':'rule_or_tactic'}
    own=legal_ids(state)
    required=min(HORIZON,1 if own==['8'] else len(own)+1) if state['groups'][state['turn']] else HORIZON
    forecasts=analysis.get('_forecasts',[])
    chain=forecasts[0] if forecasts and routes and len(forecasts[0])==len(routes[0]['steps']) else []
    valid=bool(chain) and matches(chain[0][0],state)
    valid &= all(matches(a[1],b[0]) for a,b in zip(chain,chain[1:]))
    clear=bool(valid and chain[-1][1]['phase']=='finished' and chain[-1][1]['winner']==state['turn'])
    available=len(chain) if valid else 0
    ready=valid and (clear or available>=required and required==HORIZON)
    return {'ready':bool(ready),'required':required,'available':available,'kind':'offense','clear_verified':clear}


def endpoint(analysis):
    routes=analysis.get('routes',[]) if analysis else []
    forecasts=analysis.get('_forecasts',[]) if analysis else []
    if not routes or not forecasts or len(routes[0]['steps'])!=len(forecasts[0]):return None
    return forecasts[0][-1][1] if forecasts[0] else None


def extend(service,state,depth,*,cancelled,progress):
    # Never replay/re-search the prefix: start at its certified final state.
    search=Search(service,seconds=24,evaluations=1500,cancelled=cancelled,progress=progress)
    result=search.plan(state,max_depth=depth);rounds=0
    while not result.get('routes') and result.get('horizon_limit')=='budget_exhausted' and not cancelled():
        # A time slice ending is not proof that the endpoint has no route.
        # Keep this worker and its exact candidate/probe caches, not a new job.
        rounds+=1;search.deadline=monotonic()+24;search.search_deadline=search.deadline-3
        search.cap+=1500;search.search_cap=search.cap-24
        result=search.solve(state,max_depth=depth)
    if rounds:result['budget_continuations']=rounds
    return result


def append(prefix,suffix,anchor):
    """Keep every queued stroke unchanged; append a verified endpoint search."""
    if not suffix.get('routes') or not suffix.get('_forecasts'):return None
    if not matches(suffix['_forecasts'][0][0][0],anchor):return None
    if prefix and not matches(endpoint(prefix),anchor):return None
    result=deepcopy(prefix or suffix)
    route=deepcopy(suffix['routes'][0])
    if prefix:
        route['steps']=deepcopy(prefix['routes'][0]['steps'])+route['steps']
        route.pop('perturbations',None)  # suffix probes are not full-queue probes
        route['reasons']=list(dict.fromkeys(prefix['routes'][0]['reasons']+route['reasons']))
        result['_forecasts']=[prefix['_forecasts'][0]+suffix['_forecasts'][0]]
    else:result['_forecasts']=[suffix['_forecasts'][0]]
    reason='保留已验证前序杆，只从队尾预测球位向后补算'
    if reason not in route['reasons']:route['reasons'].append(reason)
    steps=route['steps']
    route.update(mean_cost=round(sum(s['cost'] for s in steps)/len(steps),4),
                 max_shot_cost=round(max(s['cost']-s['position_effort'] for s in steps),4),
                 mean_position_effort=round(sum(s['position_effort'] for s in steps)/len(steps),4))
    result.update(status='found',routes=[route],
                  action={'action':'shoot','shot':deepcopy(steps[0]['shot'])},
                  extension_evaluations=result.get('extension_evaluations',0)+suffix.get('evaluations',0),
                  extended_steps=result.get('extended_steps',0)+len(suffix['routes'][0]['steps']))
    return result
