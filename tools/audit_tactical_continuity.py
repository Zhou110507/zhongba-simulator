"""Replay the persisted user table that exposed the single-pot queue deadlock."""
from copy import deepcopy
import json
from threading import BoundedSemaphore,Event
from time import monotonic,perf_counter

from billiards.ai_cache import model_stamp
from billiards.ai_jobs import AIJobs
from billiards.ai_rolling import readiness
from billiards.game import GameStore
from billiards.play import APP_VERSION,PlayService


def main():
    service=PlayService(table_profile='cbsa_2017')
    fixture=service.root/'tests/fixtures/ai-tactical-gate-deadlock.json'
    value=json.loads(fixture.read_text(encoding='utf8'))
    state=value['state'];analysis=value['analysis']
    old_gate_ready=(analysis['action']['action']!='shoot' or state['is_break'] or
                    not analysis['routes'] and analysis.get('tactic') in ('safety','escape','best_effort'))
    assert not old_gate_ready and not analysis.get('_forecasts')
    games=GameStore(service);games.games[state['id']]=deepcopy(state)
    jobs=AIJobs(games,BoundedSemaphore(1))
    jobs.jobs['replay']={'id':'replay','status':'found','created':monotonic(),'cancel':Event(),
        'game_id':state['id'],'revision':state['revision'],'source':deepcopy(state),
        'stamp':model_stamp(service),'analysis':analysis}
    gate=jobs.status({'id':'replay'})['analysis']['execution_gate'];assert gate['ready']
    started=perf_counter();result=jobs.execute({'id':'replay'});elapsed=perf_counter()-started
    after=result['game_after'];decision=after['last_decision']
    assert result['complete'] and result['rule_committed'] and decision['potted'] and not decision['fouls']
    assert after['revision']==state['revision']+1
    try:jobs.execute({'id':'replay'})
    except ValueError:duplicate_rejected=True
    else:raise AssertionError('Same revision committed twice')
    report={'app_version':APP_VERSION,'fixture':str(fixture.relative_to(service.root)),
        'scope':'Replay of a persisted user table and regenerated tactical shot; not a training or human-success benchmark.',
        'original_match_modified':False,'tactic':analysis['tactic'],'shot':analysis['action']['shot'],
        'old_gate_ready':old_gate_ready,'execution_gate':gate,'revision_before':state['revision'],
        'revision_after':after['revision'],'complete':result['complete'],
        'rule_committed':result['rule_committed'],'potted':decision['potted'],'fouls':decision['fouls'],
        'duplicate_rejected':duplicate_rejected,'execution_seconds':round(elapsed,4),
        'next_turn':after['turn'],'next_phase':after['phase']}
    path=service.root/'validation/tactical_continuity_v12.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
