"""Load a versioned equipment profile without inventing missing pocket data."""

from dataclasses import dataclass
import json
from pathlib import Path

from .model import BallSpec, Physics, Table


@dataclass(frozen=True)
class Equipment:
    table: Table
    ball: BallSpec
    pocket_status: str


def load_equipment(path: str | Path, profile: str | None = None) -> Equipment:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported equipment schema")
    name = profile or data["default_profile"]
    spec = data["profiles"][name]
    # Profiles containing only table geometry share the explicitly selected
    # default ball specification; no pocket shape is inferred from a width.
    ball_data = data["profiles"][data["default_profile"]]
    return Equipment(Table(spec["length_m"],spec["width_m"],name),
                     BallSpec(ball_data["ball_diameter_m"]/2,ball_data["nominal_mass_kg"]),
                     data["pocket_geometry"]["status"])


def load_physics_profile(path: str | Path, profile: str | None = None) -> Physics:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported physics profile schema")
    entry = data["profiles"][profile or data["default_profile"]]
    return Physics(**entry["parameters"])

