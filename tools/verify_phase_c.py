"""Published-equation throw controls and reproducible full-engine lab checks."""

from dataclasses import replace
import json
from math import asin, atan, cos, degrees, exp, hypot, radians, sin

from billiards import Ball, Vec2, Vec3
from billiards.ball_contact import impact_report, resolve_ball_contact
from billiards.physics_lab import run_experiment
from billiards.play import PlayService, ROOT


def build():
    service=PlayService();physics=replace(service.physics,ball_restitution=1)
    comparisons=[]
    # TP A.14 eq.15-17, equal balls, resting object ball, e=1. This control is
    # deliberately separate from the production model's e=.95 setting.
    for speed in (.447,1.341,3.129):
        for cut in (0,15,30,60):
            phi=radians(cut)
            for follow in (-1,0,1):
                for side in (-.5,0,.5):
                    horizontal=speed*(side-sin(phi));vertical=follow*speed*cos(phi)
                    slip=hypot(horizontal,vertical)
                    mu=.009951+.108*exp(-1.088*slip)
                    factor=min(mu*speed*cos(phi)/slip,1/7) if slip>1e-12 else 0
                    expected=degrees(atan(factor*horizontal/(speed*cos(phi))))
                    a=Ball('cue',Vec2(1,1),Vec2(speed,0),Vec3(0,follow*speed/service.ball_spec.radius,side*speed/service.ball_spec.radius),service.ball_spec)
                    b=Ball('1',a.position+Vec2(cos(phi),sin(phi))*(2*a.spec.radius),spec=service.ball_spec)
                    _,after=resolve_ball_contact(a,b,physics)
                    actual=impact_report(a,b,after,physics)['throw_angle_deg']
                    assert abs(actual-expected)<1e-9,(actual,expected)
                    comparisons.append({'speed':speed,'cut':cut,'follow':follow,'side':side,'expected_deg':expected,'actual_deg':actual})
    cases={}
    for name,kind,cut,follow,side in [('throw','ball',30,0,0),('side','ball',0,0,.5),('gear','ball',30,0,.5),
                                    ('follow','ball',30,1,0),('draw','ball',6,-1,0),('rail','cushion',30,1,.5)]:
        args=dict(kind=kind,speed=1.341,cut=cut,follow=follow,side=side)
        cases[name]=run_experiment(service,args)
        assert all(v['complete'] for v in cases[name]['variants'])
        repeated=run_experiment(service,args)
        assert repeated==cases[name]
    out=ROOT/'artifacts'/'phase-c';out.mkdir(parents=True,exist_ok=True)
    (out/'acceptance.json').write_text(json.dumps({'model_signature':service.signature,'equation_controls':comparisons,'experiments':cases},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(comparisons)} published-equation controls pass; {len(cases)} lab experiments stop and reproduce exactly')


if __name__=='__main__':build()
