"""Exercise the real autonomous queue on the existing integration demo."""
import json
from threading import BoundedSemaphore
from time import monotonic,sleep

from billiards.ai_jobs import AIJobs
from billiards.game import GameStore
from billiards.play import APP_VERSION,PlayService


def main():
    service=PlayService(table_profile='cbsa_2017');games=GameStore(service,compact=True)
    state=games.new({'scenario':'ai_endgame','ai_level':'expert'})
    jobs=AIJobs(games,BoundedSemaphore(1));started=monotonic();rows=[]
    key=jobs.start({'id':state['id'],'revision':state['revision']})['id']
    while state['phase']=='playing' and state['turn']==state['ai_player'] and len(rows)<8:
        deadline=monotonic()+240;last_stage=None
        while monotonic()<deadline:
            status=jobs.status({'id':key});analysis=status.get('analysis',{})
            stage=analysis.get('rolling',{}).get('progress',{}).get('stage') or status.get('progress',{}).get('stage')
            if stage!=last_stage:
                print(json.dumps({'revision':state['revision'],'stage':stage},ensure_ascii=True),flush=True);last_stage=stage
            if status['status']=='error':raise AssertionError(status)
            if status['status']=='found' and analysis['execution_gate']['ready']:break
            sleep(.05)
        else:raise AssertionError('Autonomous queue stalled')
        value=jobs.execute({'id':key,'prefetch':True});state=value['game_after'];d=state['last_decision']
        assert value['complete'] and value['rule_committed'] and not d['fouls']
        row={'revision_after':state['revision'],'tactic':analysis.get('tactic'),
             'gate':analysis['execution_gate'],'queue':[s['target'] for s in analysis.get('routes',[{'steps':[]}])[0]['steps']],
             'repaired_tail':analysis.get('repaired_tail',False),'recovery':analysis.get('offensive_recovery'),
             'potted':d['potted'],'fouls':d['fouls'],'elapsed_seconds':round(monotonic()-started,3)}
        rows.append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
        if state['phase']=='playing' and state['turn']==state['ai_player']:
            next_job=value.get('prefetch') or jobs.start({'id':state['id'],'revision':state['revision']})
            key=next_job['id']
    report={'app_version':APP_VERSION,'scope':'Known integration-demo autonomous playback; not held-out strength or human-success evidence.',
            'finished':state['phase']=='finished','winner':state['winner'],'ai_player':state['ai_player'],
            'elapsed_seconds':round(monotonic()-started,3),'metrics':jobs.metrics,'rows':rows}
    path=service.root/'validation/offensive_continuation_v13.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
