from __future__ import annotations

import json
from pathlib import Path

from scripts.menu_planner import PlannerConfig


def load_planner_config(path: str | None) -> PlannerConfig:
    if not path:
        return PlannerConfig()

    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError("Planner config must be a JSON object")

    return PlannerConfig(
        min_rating=float(payload.get("min_rating", 4.0)),
        max_prep_minutes=int(payload.get("max_prep_minutes", 45)),
        max_per_protein=int(payload.get("max_per_protein", 3)),
        max_per_cuisine=int(payload.get("max_per_cuisine", 4)),
        min_trusted_ratio=float(payload.get("min_trusted_ratio", 0.3)),
    )
