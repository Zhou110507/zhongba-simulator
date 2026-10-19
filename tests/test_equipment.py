from pathlib import Path
import json

import pytest

from billiards import BallSpec, Physics, Table
from billiards.equipment import load_equipment
from billiards.equipment import load_physics_profile

CONFIG = Path(__file__).resolve().parents[1]/"configs"/"chinese_eight_ball.json"


def test_default_equipment_matches_verified_cbsa_dimensions():
    equipment = load_equipment(CONFIG)
    assert (equipment.table.length,equipment.table.width) == (2.540,1.270)
    assert equipment.ball.radius*2 == pytest.approx(.05715)
    assert equipment.ball.mass == .163
    assert equipment.table.length == Table().length
    assert equipment.table.width == Table().width
    assert equipment.ball == BallSpec()


def test_manufacturer_geometry_is_a_separate_profile():
    equipment = load_equipment(CONFIG,"joy_q8_manufacturer")
    assert equipment.table.width == 1.260
    assert equipment.ball.radius == pytest.approx(.028575)


def test_unverified_pocket_curve_remains_explicitly_unset():
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    pocket = data["pocket_geometry"]
    assert not pocket["enabled_in_phase_a"]
    assert pocket["corner"]["jaw_curve"] is None
    assert pocket["side"]["jaw_curve"] is None
    assert load_equipment(CONFIG).pocket_status == "pending_verified_drawing"


def test_physics_profile_records_target_and_uncalibrated_provenance():
    path = CONFIG.with_name("physics_profiles.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    p = load_physics_profile(path)
    assert p == Physics()
    assert p.cushion_model == "coupled_impulse"
    assert p.cushion_friction == .14
    assert "乔氏" in data["calibration_target"]["table_brand"]
    assert "利百文" in data["calibration_target"]["cloth_brand"]
    assert data["profiles"][data["default_profile"]]["calibration_status"] == "uncalibrated"

