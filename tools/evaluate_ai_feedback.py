"""Compare the user's frozen v2 route and v3 on identical physics and metrics."""
from copy import deepcopy
import json

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.play import PlayService
from billiards.runout import Search, shot_options


def main():
    service=PlayService(table_profile='cbsa_2017')
    package=service.root/'training'/'ai_stage2'
    reference=json.loads((package/'feedback-reference.json').read_text(encoding='utf8'))
    initial=GameStore(service).new({'scenario':'ai_endgame'})
    initial.update(scene=reference['source_scene'],groups=reference['source_groups'],
                   turn=reference['source_turn'],ai_player=reference['source_ai_player'])
    result=Search(service,seconds=45,evaluations=2400).solve(initial)
    assert result['routes'],'No new route found'
    rows={}
    for name,route in [('previous_v2',reference['previous_analysis']['routes'][0]),('current_v3',result['routes'][0])]:
        state=deepcopy(initial);search=Search(service,seconds=30,evaluations=200,trained=False);steps=[]
        for step in route['steps']:
            options=shot_options(service,state,search.policy)
            option=next(o for o in options if o['target']==step['target'] and o['pocket']==step['pocket'])
            trial=search.forward(state,ShotInput(**step['shot']))
            assert trial is not None
            physics,after,access=trial
            assert not after['last_decision']['fouls']
            target=next(b for b in physics.final if b.id==step['target'])
            assert target.pocket==step['pocket']
            steps.append({'target':step['target'],'pocket':step['pocket'],
                          'shot_quality_cost':round(option['cost'],4),
                          'cue_distance_mm':round(option['distance']*1000),
                          'object_distance_mm':round(option['object_distance']*1000),
                          'cut_degrees':round(option['cut'],2),'rear_restricted':bool(access['notes']),
                          'cue_cushions':sum(e.kind=='ball_cushion' and 'cue' in e.actors for e in physics.events),
                          'shot':step['shot']})
            state=after
        rows[name]={'clear':state['winner']==initial['turn'],'steps':steps,
                    'mean_shot_quality_cost':round(sum(s['shot_quality_cost'] for s in steps)/len(steps),4),
                    'hardest_shot_quality_cost':max(s['shot_quality_cost'] for s in steps),
                    'long_object_shots':sum(s['object_distance_mm']>1200 for s in steps),
                    'rear_restricted_shots':sum(s['rear_restricted'] for s in steps)}
    output={'scope':'User feedback is held out of training; both plans replayed on unchanged physics and a common v3 shot-quality metric. No human probability claim.',
            'comparison':rows,'current_analysis':result}
    (package/'feedback-comparison.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(rows,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
