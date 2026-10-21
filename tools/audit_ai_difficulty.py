"""Validate execution spread and matched-shot physics; no training or retries."""
from hashlib import sha256
import json
from math import hypot,sqrt
from statistics import mean,pstdev

from billiards.ai_difficulty import LEVELS,configuration,realize
from billiards.game import GameStore
from billiards.play import PlayService


def main():
    service=PlayService(table_profile='cbsa_2017');config=configuration(service)
    old=json.loads((service.root/'training'/'ai_stage3'/'integrated-audit.json').read_text(encoding='utf8'))
    planned=next(r for r in old['rows'] if r['case']=='endgame-cache')['actions'][0]['action']['shot']
    base=GameStore(service);state=base.new({'scenario':'ai_endgame'})
    reference=base.action({'id':state['id'],'revision':0,'action':'shoot','shot':planned})
    ideal=next(b['position'] for b in reference['game_after']['scene']['balls'] if b['id']=='cue')
    output={'scope':'All levels receive exactly the same frozen planned shot. Engineering noise validation, not measured human ratings or full-match win rates.',
            'physics_signature':service.signature,'config':config,'planned_shot':planned,'levels':{}}
    for level in LEVELS:
        angles=[];speeds=[];projections=redraws=0
        state['ai_level']=level
        for seed in range(4000):
            state['ai_noise_seed']=f'statistics-{seed}'
            _,r=realize(service,state,planned)
            angles.append(r['angle_error_deg']);speeds.append(r['speed_error_fraction'])
            projections+=r['angle_projection_scale']!=1.;redraws+=r['speed_bound_redraws']
        rows=[]
        for seed in range(16):
            games=GameStore(service);actual=games.new({'scenario':'ai_endgame','ai_level':level})
            games.games[actual['id']]['ai_noise_seed']=f'cohort-{seed}';actual=games.get({'id':actual['id']})
            shot,report=realize(service,actual,planned)
            result=games.action({'id':actual['id'],'revision':0,'action':'shoot','shot':shot},ai_execution=report)
            assert result['complete'] and result['rule_committed']
            after=result['game_after'];cue=next(b for b in after['scene']['balls'] if b['id']=='cue')
            rows.append({'seed':seed,'execution':report,'potted':after['last_decision']['potted'],
                         'fouls':after['last_decision']['fouls'],'cue_final':cue['position'],
                         'cue_pocket':cue['pocket'],'position_error_m':hypot(cue['position']['x']-ideal['x'],cue['position']['y']-ideal['y'])})
        output['levels'][level]={'sample_count':len(angles),'angle_mean_deg':mean(angles),'angle_std_deg':pstdev(angles),
                                 'speed_mean_fraction':mean(speeds),'speed_std_fraction':pstdev(speeds),
                                 'angle_abs_p95_deg':sorted(map(abs,angles))[3799],
                                 'speed_abs_p95_fraction':sorted(map(abs,speeds))[3799],
                                 'angle_projections':projections,'speed_bound_redraws':redraws,
                                 'cohort':{'shots':len(rows),'target_pots':sum('3' in r['potted'] for r in rows),
                                           'fouls':sum(bool(r['fouls']) for r in rows),
                                           'cue_position_rmse_m':sqrt(mean(r['position_error_m']**2 for r in rows))},'actual_trials':rows}
        print(json.dumps({'level':level,**{k:v for k,v in output['levels'][level].items() if k!='actual_trials'}}),flush=True)
    output['unchanged_model_sha256']={name:sha256((service.root/'configs'/name).read_bytes()).hexdigest()
                                    for name in ('ai_human_policy.json','ai_value_model.json','ai_tactics_model.json','ai_break_model.json')}
    path=service.root/'validation'/'ai_difficulty.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':main()
