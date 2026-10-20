"""Build real engine cases for independent, synchronous JS first-contact QA."""

from copy import deepcopy
import json

from billiards.play import PlayService, ROOT


def build():
    service = PlayService()
    cases = [(p['id'],p['scene']) for p in service.presets()]
    base = next(p['scene'] for p in service.presets() if p['id']=='draw-angle')
    for angle in (0,.25,.5,1,2,15,45,90,180,270):
        for speed,tip in ((.25,0),(1,0),(2.8,-.5),(2.8,.5),(1.8,.55)):
            scene = deepcopy(base)
            scene['shot'].update(angle_deg=angle,cue_speed=speed,tip_y=tip,tip_x=0)
            cases.append((f'angle={angle},speed={speed},tip={tip}',scene))
    reports = []
    for name,scene in cases:
        response = service.shoot(scene)
        assert response['complete'],(name,response['result']['status'])
        reports.append({'name':name,'scene':scene,'result':response['result']})
    output = ROOT/'artifacts'/'aim-v5'
    output.mkdir(parents=True,exist_ok=True)
    (output/'parity.json').write_text(json.dumps({'config':service.config(),'cases':reports}),encoding='utf-8')
    print(f'Built {len(reports)} engine cases for synchronous aim parity')


if __name__=='__main__':
    build()
