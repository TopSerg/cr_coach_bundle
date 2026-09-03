from __future__ import annotations

import json

from common import compact_entity, load_backend, non_tower_entities

from cr_coach.engine.crbot import CrBotEngineAdapter
from cr_coach.replay.executor import execute_replay
from cr_coach.replay.schema import ReplayBattle, ReplayEvent


def main() -> int:
    engine, deck = load_backend()
    battle = ReplayBattle(
        battle_id="physical-dual-hog-same-tick",
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
            ),
            ReplayEvent(
                tick=0,
                side="opponent",
                event_type="card_play",
                card="hog-rider",
                x_mtile=14_500,
                y_mtile=11_500,
            ),
        ],
    )

    adapter = CrBotEngineAdapter.from_replay(battle, engine=engine)
    trace = execute_replay(battle, adapter)
    after = trace[-1]

    hogs = sorted(
        [
            entity
            for entity in non_tower_entities(after)
            if entity.get("card_id") == "hog-rider"
        ],
        key=lambda entity: entity["owner"],
    )

    print("\n=== TEST 02: two players act on the same replay tick ===")
    print(
        json.dumps(
            {
                "final_tick": after.get("tick"),
                "hogs": [compact_entity(entity) for entity in hogs],
            },
            indent=2,
            sort_keys=True,
        )
    )

    assert after.get("tick") == 1, "both tick-0 actions must be resolved in one physics step"
    assert len(hogs) == 2, f"expected two Hogs, got {len(hogs)}"
    assert [entity["owner"] for entity in hogs] == [0, 1], (
        "expected one Hog per player"
    )
    assert all(entity["spawn_tick"] == 0 for entity in hogs), (
        "both Hogs must have the same spawn_tick; otherwise the adapter advanced between actions"
    )
    assert (hogs[0]["x_mtile"], hogs[0]["y_mtile"]) == (3_500, 20_500)
    assert (hogs[1]["x_mtile"], hogs[1]["y_mtile"]) == (14_500, 11_500)

    print("PASS: simultaneous replay actions are batched into one BattleEngine.step()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
