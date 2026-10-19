"""Generate the offline phase-A viewer and machine-readable traces.

Run from the repository root: python -m tools.build_acceptance
"""

from pathlib import Path
from hashlib import sha256
import json
import platform
import time

import numpy as np

from billiards import Ball, Physics, Table, Vec2, Vec3, simulate
from billiards.scenarios import acceptance_scenes
from billiards.diagnostics import cushion_observations

ROOT = Path(__file__).resolve().parents[1]


def analytic_checks():
    checks, physics = [], Physics()
    for speed in (.01,.5,1,4):
        b = Ball("cue",Vec2(10,10),Vec2(speed,0),Vec3(0,speed/.028575,0))
        result = simulate([b],Table(1000,500))
        expected = speed*speed/(2*physics.rolling_friction*physics.gravity)
        actual = result.final[0].position.x-10
        error = abs(actual-expected)
        checks.append({"case":f"rolling_stop_{speed}","quantity":"distance_m",
                       "expected":expected,"actual":actual,"absolute_error":error,
                       "tolerance":1e-10,"passed":error<1e-10 and result.status=="stopped"})
    speed = 1.2
    transition_time = 2*speed/(7*physics.sliding_friction*physics.gravity)
    result = simulate([Ball("cue",Vec2(10,10),Vec2(speed,0))],
                      Table(1000,500),max_time=transition_time)
    expected, actual = 5*speed/7, result.final[0].velocity.x
    error = abs(expected-actual)
    checks.append({"case":"sliding_transition","quantity":"speed_m_per_s",
                   "expected":expected,"actual":actual,"absolute_error":error,
                   "tolerance":1e-10,"passed":error<1e-10})
    if not all(c["passed"] for c in checks):
        raise RuntimeError("Analytic benchmark failed")
    return checks


def build():
    output = ROOT / "artifacts" / "phase-a"
    output.mkdir(parents=True, exist_ok=True)
    scenes, summaries = [], []
    for scenario in acceptance_scenes():
        start = time.perf_counter()
        result = simulate(scenario["balls"], scenario["table"], scenario["physics"],
                          max_time=scenario.get("max_time",60))
        elapsed = (time.perf_counter()-start)*1000
        if result.status != scenario.get("expected_status","stopped"):
            raise RuntimeError(f"{scenario['id']}: {result.status}")
        payload = result.to_dict(60)
        payload["cushion_audit"] = cushion_observations(result)
        payload["calibration_status"] = "uncalibrated"
        payload.update({k: scenario[k] for k in ("id","name","description","observe")})
        (output/f"{scenario['id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),encoding="utf-8")
        scenes.append(payload)
        summaries.append({"id":scenario["id"],"name":scenario["name"],
                          "status":result.status,"duration_s":result.duration,
                          "events":len(result.events),"compute_ms":elapsed,
                          "initial_energy_j":sum(b.energy for b in result.initial),
                          "final_energy_j":sum(b.energy for b in result.final),
                          "final_positions_m":{b.id:[b.position.x,b.position.y] for b in result.final}})
    benchmark_start = time.perf_counter()
    repeats = 50
    for _ in range(repeats):
        for s in acceptance_scenes():
            simulate(s["balls"],s["table"],s["physics"],max_time=s.get("max_time",60))
    benchmark = {"runs":repeats*len(scenes),
                 "elapsed_s":time.perf_counter()-benchmark_start,
                 "python":platform.python_version(),"numpy":np.__version__,
                 "scope":f"{len(scenes)} phase-A scenes, including explicitly truncated ideal controls; no export/rendering"}
    report = {"schema_version":1,"stage":"A","scenes":summaries,
              "analytic_checks":analytic_checks(),"benchmark":benchmark}
    (output/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    template = (ROOT/"tools"/"acceptance_viewer.html").read_text(encoding="utf-8")
    encoded = json.dumps(scenes,ensure_ascii=False,allow_nan=False).replace("<","\\u003c")
    build_id = sha256((template+encoded).encode("utf-8")).hexdigest()[:12]
    rendered = template.replace("__SCENE_DATA__",encoded).replace("__BUILD_ID__",build_id)
    (output/"验收演示.html").write_text(rendered.replace("__DEFAULT_SCENE__","rail"),encoding="utf-8")
    (output/"05-薄厚球专项复核.html").write_text(rendered.replace("__DEFAULT_SCENE__","cut"),encoding="utf-8")
    manifest = {"build_id":build_id,"engine_version":scenes[0]["engine_version"],
                "scenes":[{"id":s["id"],"cushion_model":s["physics"]["cushion_model"]} for s in scenes]}
    (output/"build-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    build()

