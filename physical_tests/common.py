from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "starter"
CRBOT_PIN = "40ca2b16bc276fc982a3aa80c7415b24439cbd3c"


def _crbot_path() -> Path:
    explicit = os.environ.get("CRBOT_PATH")
    candidates = [
        Path(explicit) if explicit else None,
        ROOT / ".physical_deps" / "cr-bot",
        ROOT / "upstream" / "cr-bot",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "simulator").exists():
            return candidate
    return ROOT / ".physical_deps" / "cr-bot"


CRBOT = _crbot_path()

for path in (STARTER, CRBOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def require_crbot() -> None:
    if not (CRBOT / "simulator").exists():
        raise SystemExit(
            "cr-bot simulator checkout is missing. From repository root run:\n"
            "  powershell -ExecutionPolicy Bypass -File physical_tests/setup_crbot.ps1\n"
            "or on bash:\n"
            "  bash physical_tests/setup_crbot.sh"
        )


def load_backend() -> tuple[Any, tuple[str, ...]]:
    require_crbot()
    from simulator.engine import BASE_HOG_CYCLE_DECK, BattleEngine

    return BattleEngine(), tuple(BASE_HOG_CYCLE_DECK)


def non_tower_entities(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entity
        for entity in snapshot.get("entities", [])
        if entity.get("kind") != "tower"
    ]


def compact_entity(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "uid": entity.get("uid"),
        "card_id": entity.get("card_id"),
        "owner": entity.get("owner"),
        "x_mtile": entity.get("x_mtile"),
        "y_mtile": entity.get("y_mtile"),
        "hp": entity.get("hp"),
        "spawn_tick": entity.get("spawn_tick"),
        "deploy_remaining_us": entity.get("deploy_remaining_us"),
        "target_uid": entity.get("target_uid"),
    }
