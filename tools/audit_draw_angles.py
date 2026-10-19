"""Compare cue aim offset, real sphere cut angle, and post-slide draw direction."""

import json

from billiards import Ball, Table, Vec2, simulate
from billiards.cue import ShotInput, strike
from billiards.play import PlayService, ROOT
from billiards.shot_analysis import first_contact_analysis


def build():
    service=PlayService()
    output=ROOT/'artifacts'/'pocket-v2'
    output.mkdir(parents=True,exist_ok=True)
    reports=[]
    for offset in (0,.25,.5,1,2):
        cue=strike(Ball('cue',Vec2(10,10)),ShotInput(offset,2.8,0,-.5),service.cue)
        result=simulate([cue,Ball('1',Vec2(10.75,10))],Table(100,100),service.physics,max_time=120)
        data=first_contact_analysis(result)
        assert result.status=='stopped'
        assert abs(data['free_roll_return_angle_deg']-data['observed_return_angle_deg'])<1e-8
        reports.append(data)
    (output/'draw-angles.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    for data in reports:
        print(f"aim {data['aim_offset_deg']:.2f}, cut {data['cut_angle_deg']:.3f}, "
              f"q {data['backspin_speed_ratio']:.3f}, return {data['observed_return_angle_deg']:.3f}, "
              f"separation {data['ball_separation_angle_deg']:.3f}")


if __name__=='__main__':
    build()
