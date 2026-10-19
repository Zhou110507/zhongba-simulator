"""Record the 06 root cause, controlled comparisons and step convergence."""

from dataclasses import asdict, replace
from pathlib import Path
import json

from billiards import simulate
from billiards.diagnostics import cushion_observations
from billiards.scenarios import acceptance_scenes


def build():
    root = Path(__file__).resolve().parents[1]
    scene = next(s for s in acceptance_scenes() if s["id"]=="rail")
    variants = {"legacy_e080":replace(scene["physics"],cushion_model="frictionless",cushion_restitution=.80,
                                version="phase-a-frictionless-contacts-v1"),
                "coupled_e080":replace(scene["physics"],cushion_restitution=.80,
                                       version="phase-a-coupled-cushion-v2"),
                "current_512":scene["physics"],
                "current_1024":replace(scene["physics"],cushion_steps=1024),
                "current_2048":replace(scene["physics"],cushion_steps=2048)}
    records = {}
    for name,physics in variants.items():
        result = simulate(scene["balls"],scene["table"],physics)
        records[name] = {"physics":asdict(physics),"status":result.status,
                         "cushions":cushion_observations(result),
                         "first_post_contact_curved_segments":[]}
        first = next(e for e in result.events if e.kind=="ball_cushion")
        for segment in result.segments:
            if segment.start < first.time:
                continue
            if segment.start > first.time+.55:
                break
            b,m = segment.balls[0],segment.motions[0]
            cross = b.velocity.x*m.acceleration.y-b.velocity.y*m.acceleration.x
            records[name]["first_post_contact_curved_segments"].append({
                "start":segment.start,"end":segment.end,"phase":m.phase,
                "velocity":asdict(b.velocity),"acceleration":asdict(m.acceleration),
                "omega":asdict(b.omega),"slip":asdict(b.slip),
                "velocity_cross_acceleration":cross,"curved":abs(cross)>1e-9})
    payload = {"initial":[asdict(b) for b in scene["balls"]],"table":asdict(scene["table"]),
               "calibration_status":"not_calibrated_to_JOY_Liber_Win",
               "variants":records}
    target = root/"artifacts"/"phase-a"/"cushion-audit.json"
    target.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,indent=2),encoding="utf-8")
    for name,data in records.items():
        print(name,data["cushions"][0])


if __name__ == "__main__":
    build()
