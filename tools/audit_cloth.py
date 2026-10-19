"""Separate cloth changes from the UI stroke range using reproducible shots."""

from dataclasses import replace
import json

import numpy as np

from billiards import Ball, Table, Vec2, simulate
from billiards.cue import ShotInput, strike
from billiards.equipment import load_physics_profile
from billiards.play import PlayService, ROOT


def path_length(result, identifier='cue'):
    nodes, weights = np.polynomial.legendre.leggauss(32)
    distance = 0.0
    for segment in result.segments:
        index = next(i for i,b in enumerate(segment.balls) if b.id==identifier)
        ball, motion = segment.balls[index], segment.motions[index]
        if ball.pocket is not None:
            continue
        duration = segment.end-segment.start
        distance += duration/2*sum(float(weight)*(ball.velocity+motion.acceleration*
                          (duration*(float(node)+1)/2)).norm() for node,weight in zip(nodes,weights))
    return distance


def compare():
    service = PlayService()
    old = load_physics_profile(ROOT/'configs'/'physics_profiles.json','uncalibrated_coupled_v3')
    variants = [('old',old,1.8),('cloth_only',service.physics,1.8),
                ('power_only',old,service.cue.max_speed),('current',service.physics,service.cue.max_speed)]
    reports = []
    for label,physics,max_speed in variants:
        cue = replace(service.cue,max_speed=max_speed)
        shots = []
        for fraction in (.25,.5,.75,1):
            launched = strike(Ball('cue',Vec2(.4,.42),spec=service.ball_spec),
                              ShotInput(0,max_speed*fraction,0,.4),cue)
            result = simulate([launched],service.table,physics,max_time=120)
            shots.append({'power_percent':fraction*100,'launch_speed_m_s':launched.velocity.norm(),
                          'distance_m':path_length(result),'duration_s':result.duration,'status':result.status,
                          'cushions':sum(event.kind=='ball_cushion' for event in result.events)})
        draw = []
        for fraction in (.5,.7,1):
            launched = strike(Ball('cue',Vec2(10,10),spec=service.ball_spec),
                              ShotInput(0,max_speed*fraction,0,-.5),cue)
            result = simulate([launched,Ball('1',Vec2(11,10),spec=service.ball_spec)],
                              Table(1000,1000),physics,max_time=120)
            impact = next((e for e in result.events if e.kind=='ball_ball'),None)
            impact_ball = next((b for b in impact.before if b.id=='cue'),None) if impact else None
            final = next(b for b in result.final if b.id=='cue')
            draw.append({'power_percent':fraction*100,'launch_speed_m_s':launched.velocity.norm(),
                         'contact':impact is not None,'backspin_at_contact_rad_s':impact_ball.omega.y if impact else None,
                         'final_displacement_from_contact_m':final.position.x-(11-2*service.ball_spec.radius),
                         'status':result.status})
        reports.append({'variant':label,'sliding':physics.sliding_friction,'rolling':physics.rolling_friction,
                        'max_cue_speed':max_speed,'roll_shots':shots,'one_metre_draw':draw})
    return {'model_signature':service.signature,'note':'Model diagnostics, not a new hardware measurement. '
            'Roll shots use a 0.4 R high tip to launch natural roll. Draw centre spacing is 1 m; '
            'draw distances use a large virtual surface to exclude cushions. Negative displacement is draw.',
            'variants':reports}


def build():
    output = ROOT/'artifacts'/'cloth-v1'
    output.mkdir(parents=True,exist_ok=True)
    report = compare()
    (output/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for variant in report['variants']:
        middle = variant['roll_shots'][1]
        print(variant['variant'], '50% natural roll:',round(middle['distance_m'],3),'m,',
              middle['cushions'],'cushions; 70% one-metre draw:',
              round(variant['one_metre_draw'][1]['final_displacement_from_contact_m'],3),'m')


if __name__=='__main__':
    build()
