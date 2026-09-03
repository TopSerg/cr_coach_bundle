from __future__ import annotations

from common import load_backend

from cr_coach.engine.crbot import CrBotEngineAdapter
from cr_coach.replay.executor import ReplayExecutionError, execute_replay
from cr_coach.replay.schema import ReplayBattle, ReplayEvent


def main() -> int:
    engine, deck = load_backend()
    battle = ReplayBattle(
        battle_id="physical-hand-mismatch",
        ticks_per_second=20,
        team_deck=deck,
        opponent_deck=deck,
        team_initial_queue=deck,
        opponent_initial_queue=deck,
        events=[
            # BASE_HOG_CYCLE_DECK opens with Hog/Cannon/Musketeer/Skeletons,
            # so Fireball is deliberately not playable at tick 0.
            ReplayEvent(
                tick=0,
                side="team",
                event_type="card_play",
                card="fireball",
                x_mtile=9_500,
                y_mtile=15_500,
            )
        ],
    )

    adapter = CrBotEngineAdapter.from_replay(battle, engine=engine)

    print("\n=== TEST 03: impossible replay action must stop reconstruction ===")
    try:
        execute_replay(battle, adapter)
    except ReplayExecutionError as exc:
        print(f"Expected divergence: {exc}")
        assert "card_not_in_hand" in exc.reason, (
            "expected card_not_in_hand, got: " + exc.reason
        )
        assert adapter.tick == 0, (
            "adapter must not advance physics after detecting an impossible hand action"
        )
        print("PASS: impossible replay action is rejected instead of corrupting state")
        return 0

    raise AssertionError("expected ReplayExecutionError, but replay continued")


if __name__ == "__main__":
    raise SystemExit(main())
