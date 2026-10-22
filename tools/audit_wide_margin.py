"""Reproduce the v9 horizon and execution-margin audit without changing games."""
from copy import deepcopy
import gzip
import hashlib
import json
from time import perf_counter

from billiards.game import GameStore
from billiards.play import PlayService
from billiards.runout import Search
from billiards.shot_prior import planning_policy
from tools.train_runout import layout


def main():
    service=PlayService(table_profile='cbsa_2017');root=service.root
    fixture=json.loads((root/'tests/fixtures/ai-invalid-final-state.json').read_text(encoding='utf8'))
    cases=[('endgame',GameStore(service).new({'scenario':'ai_endgame'})),
           ('previous-user-layout',fixture['original']),
           ('unseen-980001',layout(service,980001,ball_count=3))]
    rows=[]
    for name,state in cases:
        original=deepcopy(state);search=Search(service,seconds=30,evaluations=1800)
        started=perf_counter();result=search.plan(state,max_depth=3)
        row={k:v for k,v in result.items() if k not in ('_forecasts','routes')}
        row.update(case=name,wall_seconds=perf_counter()-started,routes=result['routes'])
        assert state==original
        for source,after in (result['_forecasts'][0] if result['_forecasts'] else []):
            service.decode(source['scene']);service.decode(after['scene'])
            assert not after['last_decision']['fouls']
        for route in result['routes']:
            for step in route['steps']:
                margin=step['human_margin']
                assert margin['allowed'] and margin['pot_passed']==4 and margin['leaf_passed']>=3
                cue_other=[p for p in step['secondary_contacts'] if 'cue' in p and step['target'] not in p]
                assert not cue_other or step['opened_targets'] and margin['leaf_passed']==4
        rows.append(row)
        print(json.dumps({k:row[k] for k in ('case','status','requested_depth','verified_depth','horizon_complete','horizon_limit','elapsed','evaluations')},ensure_ascii=True),flush=True)
    dataset=gzip.decompress((root/'training/ai_stage5/shot-prior-dataset.json.gz').read_bytes())
    training=json.loads((root/'training/ai_stage5/shot-prior-training.json').read_text(encoding='utf8'))
    report={'version':'wide-margin-full-horizon-v9','planning_policy':planning_policy(),
            'training_simulations':training['simulations'],'dataset_sha256':hashlib.sha256(dataset).hexdigest(),
            'heldout_prior_metrics':training['model']['training']['metrics']['test'],
            'rows':rows,'limits':'Three-case synthetic/feedback engineering audit, not a calibrated human pot/clear probability. Full target depth is preserved; failure to find a longer robust route is reported explicitly. No latency improvement claim.'}
    (root/'validation/wide_margin_v9.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':main()
