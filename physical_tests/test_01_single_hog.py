from __future__ import annotations

import json

from common import compact_entity, load_backend, non_tower_entities

from cr_coach.engine.crbot import CrBotEngineAdapter
from cr_coach.replay.executor import execute_replay
from cr_coach.replay.schema import ReplayBattle, ReplayEvent


def main() -> int:
    engine, deck = load_backend()
    battle = ReplayBattle(
        battle_id="physical-single-hog",
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

    adapter = CrBotEngineAdapter.from_replay(battle, engine=engine)
    trace = execute_replay(battle, adapter)
    before = trace[0]
    after = trace[-1]

    hogs = [
        entity
        for entity in non_tower_entities(after)
        if entity.get("card_id") == "hog-rider" and entity.get("owner") == 0
    ]

    print("\n=== TEST 01: single Hog placement ===")
    print(
        json.dumps(
            {
                "before_tick": before.get("tick"),
                "after_tick": after.get("tick"),
                "team_hand_before": before["players"][0]["hand"],
                "team_hand_after": after["players"][0]["hand"],
                "team_elixir_before": before["players"][0]["elixir_milli"],
                "team_elixir_after": after["players"][0]["elixir_milli"],
                "spawned_hogs": [compact_entity(entity) for entity in hogs],
            },
            indent=2,
            sort_keys=True,
        )
    )

    assert before.get("tick") == 0, "expected pre-action snapshot at tick 0"
    assert after.get("tick") == 1, "final action must be committed by one physics tick"
    assert len(hogs) == 1, f"expected exactly one team Hog, got {len(hogs)}"
    hog = hogs[0]
    assert (hog["x_mtile"], hog["y_mtile"]) == (3_500, 20_500), (
        "Hog should initially spawn at the center of replay cell (3, 20); "
        f"got {(hog['x_mtile'], hog['y_mtile'])}"
    )
    assert hog["spawn_tick"] == 0, f"unexpected spawn tick: {hog['spawn_tick']}"
    assert "hog-rider" not in after["players"][0]["hand"], (
        "played Hog should no longer be in the immediate hand after the action"
    )

    print("PASS: ReplayEvent -> coordinate adapter -> CrBotEngineAdapter -> cr-bot state works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
