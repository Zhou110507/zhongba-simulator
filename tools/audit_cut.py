"""Audit every 05 contact for both balls, alongside its ideal control."""

from dataclasses import asdict, replace
from pathlib import Path
import json

from billiards import simulate
from billiards.diagnostics import cushion_observations
from billiards.scenarios import acceptance_scenes


def build():
    scenes = {s["id"]:s for s in acceptance_scenes()}
    actual,ideal = scenes["cut"],scenes["cut_mirror"]
    variants = {"coupled_512":(actual,actual["physics"]),
                "coupled_2048":(actual,replace(actual["physics"],cushion_steps=2048)),
                "ideal_control":(ideal,ideal["physics"])}
    records = {}
    for name,(scene,physics) in variants.items():
        result = simulate(scene["balls"],scene["table"],physics,
                          max_time=scene.get("max_time",60))
        records[name] = {"physics":asdict(physics),"status":result.status,
                         "duration":result.duration,"cushions":cushion_observations(result)}
    payload = {"initial":[asdict(b) for b in actual["balls"]],
               "same_physics_as_06":actual["physics"]==scenes["rail"]["physics"],
               "calibration_status":"not_calibrated_to_JOY_Liber_Win",
               "variants":records}
    target = Path(__file__).resolve().parents[1]/"artifacts"/"phase-a"/"cut-audit.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,indent=2),encoding="utf-8")
    for name,data in records.items():
        print(name,data["status"])
        for row in data["cushions"]:
            print(row["ball"],row["wall"],row["incident_deg"],row["immediate_deg"],row["rolling_deg"])


if __name__ == "__main__":
    build()
