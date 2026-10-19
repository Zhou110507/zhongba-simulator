"""Rebuild reviewable stage-B preset inputs, outputs and acceptance checks."""

import json
from pathlib import Path

from billiards.play import PlayService


def build():
    service = PlayService()
    output = Path(__file__).resolve().parents[1]/'artifacts'/'phase-b'
    output.mkdir(parents=True,exist_ok=True)
    reports = []
    for preset in service.presets():
        response = service.shoot(preset['scene'])
        if not response['complete']:
            raise RuntimeError(f"{preset['id']}: {response['result']['status']}")
        repeated = service.shoot(json.loads(json.dumps(response['snapshot'])))
        if response['result'] != repeated['result']:
            raise RuntimeError('Scene did not reproduce deterministically')
        if preset['id'] in ('corner','side') and response['summary']['potted'] != ['1']:
            raise RuntimeError('Pocket preset did not pot its target ball')
        (output/f"{preset['id']}.json").write_text(json.dumps(response,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
        (output/f"{preset['id']}.scene.json").write_text(json.dumps(response['snapshot'],ensure_ascii=False,indent=2),encoding='utf-8')
        reports.append({'id':preset['id'],'name':preset['name'],'status':response['result']['status'],
                        'duration_s':response['result']['duration'],'compute_ms':response['compute_ms'],
                        'events':len(response['result']['events']),**response['summary'],'reproduced':True})
    payload = {'stage':'B','model_signature':service.signature,'table':service.model['table'],
               'presets':reports,'calibration_status':service.config()['calibration_status']}
    (output/'acceptance.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(reports,ensure_ascii=True,indent=2))


if __name__=='__main__':
    build()
