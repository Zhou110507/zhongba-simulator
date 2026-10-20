"""Same-input rack regression and timing observations, with reproducible seeds."""
from dataclasses import replace
import gzip
import json
from pathlib import Path
from time import perf_counter

from billiards.cue import ShotInput, strike
from billiards.engine import simulate
from billiards.play import PlayService
from billiards.rules import racked_balls


def run():
    service=PlayService(table_profile='cbsa_2017');rows=[]
    for gap in (0,.2,.5):
        for seed in (0,7,19):
            for angle,speed in ((0,4),(.45,5),(-.45,4)):
                source=racked_balls(service,seed,gap)
                balls=tuple(strike(b,ShotInput(angle,speed),service.cue) if b.id=='cue' else b for b in source)
                solvers=('cluster','hybrid_hertz') if seed==0 and angle==0 and gap<=.2 else ('hybrid_hertz',)
                for solver in solvers:
                    started=perf_counter();result=simulate(balls,service.table,replace(service.physics,contact_solver=solver),max_events=6000)
                    physics=perf_counter()-started
                    assert result.status=='stopped',(gap,seed,angle,speed,solver,result.status)
                    first=next(e for e in result.events if e.kind=='ball_ball' and 'cue' in e.actors)
                    early=result.state_at(first.time+.15);one=result.state_at(1.)
                    objects=early[1:];energy=sum(b.energy for b in objects)
                    fastest=sorted((b.energy for b in objects),reverse=True)
                    raw=json.dumps(result.to_dict(None,compact=True),separators=(',',':')).encode()
                    rows.append(dict(gap_mm=gap,seed=seed,angle_deg=angle,cue_speed=speed,solver=solver,physics_s=physics,
                        status=result.status,duration_s=result.duration,ball_ball_events=sum(e.kind=='ball_ball' for e in result.events),
                        moved_100mm_at_1s=sum(b.pocket is not None or (b.position-a.position).norm()>.1 for a,b in zip(source[1:],one[1:])),
                        cue_speed_150ms_after_hit=early[0].velocity.norm(),objects_over_02m_s=sum(b.velocity.norm()>.2 for b in objects),
                        two_fastest_object_energy_fraction=sum(fastest[:2])/energy if energy else 0,
                        segments=len(result.segments),gzip_bytes=len(gzip.compress(raw,compresslevel=1,mtime=0))))
    out=Path('artifacts/break-fix');out.mkdir(parents=True,exist_ok=True)
    (out/'audit.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    new=[r for r in rows if r['solver']=='hybrid_hertz'];times=sorted(r['physics_s'] for r in new)
    print(json.dumps(dict(cases=len(new),complete=len(new),median_s=times[len(times)//2],maximum_s=max(times),
                          comparison=[r for r in rows if r['seed']==0 and r['angle_deg']==0 and r['gap_mm']<=.2]),indent=2))


if __name__=='__main__':run()
