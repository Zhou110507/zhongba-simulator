"""Repeatable end-to-end benchmarks; timings are observations, not test limits."""
import gzip
import json
from pathlib import Path
from time import perf_counter

from billiards.cue import ShotInput
from billiards.play import PlayService
from billiards.rules import racked_balls


def build():
    service=PlayService(table_profile='cbsa_2017');reports=[]
    for label,gap in [('tight',0),('micro-gap',.2)]:
        scene=service.snapshot(racked_balls(service,0,gap),ShotInput(.45,5))
        started=perf_counter();response=service.shoot(scene,compact=True)
        wall=perf_counter()-started
        started=perf_counter();raw=json.dumps(response,ensure_ascii=False,separators=(',',':')).encode()
        encoding=perf_counter()-started
        packed=gzip.compress(raw,compresslevel=1,mtime=0)
        assert response['complete']
        reports.append(dict(case=label,gap_mm=gap,wall_s=wall,physics_ms=response['compute_ms'],
                            encode_s=encoding,bytes=len(raw),gzip_bytes=len(packed),
                            events=len(response['result']['events']),segments=len(response['result']['segments'])))
    output=Path(__file__).resolve().parents[1]/'artifacts'/'performance';output.mkdir(parents=True,exist_ok=True)
    (output/'benchmark.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(reports,indent=2))


if __name__=='__main__':build()
