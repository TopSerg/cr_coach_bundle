from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "starter"
CRBOT = ROOT / "upstream" / "cr-bot"

for path in (STARTER, CRBOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def require_crbot() -> None:
    if not CRBOT.exists() or not (CRBOT / "simulator").exists():
        raise SystemExit(
            "upstream/cr-bot is not initialized. From repository root run:\n"
            "  git submodule update --init upstream/cr-bot"
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
