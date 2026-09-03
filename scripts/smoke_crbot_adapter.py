#!/usr/bin/env python3
"""Run the first real glue smoke test against Keschler/cr-bot.

Recommended lightweight setup from repository root:

    powershell -ExecutionPolicy Bypass -File physical_tests/setup_crbot.ps1
    python scripts/smoke_crbot_adapter.py

The script intentionally tests only our boundary: one known Hog placement at
replay tick 0 should enter cr-bot through ReplayEvent -> coordinate adapter ->
CrBotEngineAdapter -> BattleEngine.step without an action rejection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "starter"

explicit = os.environ.get("CRBOT_PATH")
candidates = [
    Path(explicit) if explicit else None,
    ROOT / ".physical_deps" / "cr-bot",
    ROOT / "upstream" / "cr-bot",
]
CRBOT = next(
    (candidate for candidate in candidates if candidate is not None and (candidate / "simulator").exists()),
    ROOT / ".physical_deps" / "cr-bot",
)

for path in (STARTER, CRBOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def main() -> int:
    if not (CRBOT / "simulator").exists():
        raise SystemExit(
            "cr-bot simulator checkout is missing; run physical_tests/setup_crbot.ps1 "
            "or physical_tests/setup_crbot.sh"
        )

    from cr_coach.engine.crbot import CrBotEngineAdapter
    from cr_coach.replay.executor import execute_replay
    from cr_coach.replay.schema import ReplayBattle, ReplayEvent
    from simulator.engine import BASE_HOG_CYCLE_DECK, BattleEngine

    deck = tuple(BASE_HOG_CYCLE_DECK)
    battle = ReplayBattle(
        battle_id="smoke-hog-t0",
        ticks_per_second=20,
        team_deck=deck,
        opponent_deck=deck,
        team_initial_queue=deck,
        opponent_initial_queue=deck,
        events=[
            ReplayEvent(
                tick=0,
                side="team",
                event_type="card_play",
                card="hog-rider",
                x_mtile=3_500,
                y_mtile=20_500,
            )
        ],
    )

    adapter = CrBotEngineAdapter.from_replay(
        battle,
        engine=BattleEngine(),
    )
    trace = execute_replay(battle, adapter)
    final = trace[-1]

    non_towers = [
        entity
        for entity in final.get("entities", [])
        if entity.get("kind") != "tower"
    ]
    summary = {
        "battle_id": battle.battle_id,
        "crbot_path": str(CRBOT),
        "final_tick": adapter.tick,
        "team_hand": final["players"][0]["hand"],
        "team_elixir_milli": final["players"][0]["elixir_milli"],
        "non_tower_entities": [
            {
                "card_id": entity.get("card_id"),
                "owner": entity.get("owner"),
                "x_mtile": entity.get("x_mtile"),
                "y_mtile": entity.get("y_mtile"),
                "deploy_remaining_us": entity.get("deploy_remaining_us"),
            }
            for entity in non_towers
        ],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if not any(
        entity.get("card_id") == "hog-rider" and entity.get("owner") == 0
        for entity in non_towers
    ):
        raise SystemExit("smoke failed: Hog Rider was not spawned")

    print("OK: replay action reached cr-bot and spawned Hog Rider")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
