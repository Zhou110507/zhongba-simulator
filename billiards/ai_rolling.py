"""Extend only the unsearched endpoint of an already verified shot queue."""
from copy import deepcopy

from .ai_cache import matches
from .runout import Search

HORIZON=3


def endpoint(analysis):
    routes=analysis.get('routes',[]) if analysis else []
    forecasts=analysis.get('_forecasts',[]) if analysis else []
    if not routes or not forecasts or len(routes[0]['steps'])!=len(forecasts[0]):return None
    return forecasts[0][-1][1] if forecasts[0] else None


def extend(service,state,depth,*,cancelled,progress):
    # Never replay/re-search the prefix: start at its certified final state.
    return Search(service,seconds=12,evaluations=700,cancelled=cancelled,progress=progress).solve(state,max_depth=depth)


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
