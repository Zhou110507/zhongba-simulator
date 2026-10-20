"""Reproducible route benchmarks, including replay and perturbation evidence."""
from pathlib import Path
import json

from billiards.planner import decode_request, solve
from billiards.planner_examples import example
from billiards.play import PlayService


def main():
    service = PlayService(); reports = []
    for kind in ('one_bank', 'two_bank'):
        task = example(service, kind)
        response = solve(service, decode_request(service, task))
        assert response['status'] == 'found', (kind, response['status'])
        for solution in response['solutions']:
            scene = {**task['scene'], 'shot': solution['shot']}
            actual = service.shoot(scene, compact=True)
            cue = next(b for b in actual['result']['final'] if b['id'] == 'cue')
            assert actual['complete'] and not actual['summary']['scratch']
            assert abs(cue['position']['x']-solution['cue_final']['x']) < 1e-10
            assert abs(cue['position']['y']-solution['cue_final']['y']) < 1e-10
        reports.append({'kind': kind, 'request': task, 'result': response})
        print(kind, response['status'], response['evaluations'], 'evaluations,', response['elapsed'], 'seconds',
              [round(s['error_m']*1000, 1) for s in response['solutions']], flush=True)
    target = Path('artifacts/phase-e'); target.mkdir(parents=True, exist_ok=True)
    (target/'route-verification.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
