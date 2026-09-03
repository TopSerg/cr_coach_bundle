from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from cr_coach.adapters.coordinates import ReplayGridAdapter
from cr_coach.engine.protocol import EngineAdapter
from cr_coach.replay.schema import ReplayBattle


@dataclass(slots=True)
class ReplayExecutionError(RuntimeError):
    tick: int
    event_index: int
    reason: str

    def __str__(self) -> str:
        return f"replay divergence at tick={self.tick}, event={self.event_index}: {self.reason}"


def execute_replay(
    battle: ReplayBattle,
    engine: EngineAdapter,
    *,
    coords: ReplayGridAdapter | None = None,
    flip_y_for_opponent: bool = False,
    snapshot_every_ticks: int = 1,
) -> list[dict[str, Any]]:
    """Execute one canonical replay and return periodic authoritative snapshots.

    Engine adapters may buffer actions for the current physics tick. We take a
    pre-action snapshot when the cadence lands exactly on an event tick, queue
    every event at that tick, and force the final event tick to be committed by
    advancing at least one tick beyond it before returning.
    """

    battle.validate()
    if snapshot_every_ticks <= 0:
        raise ValueError("snapshot_every_ticks must be positive")

    coords = coords or ReplayGridAdapter()
    trace: list[dict[str, Any]] = []
    next_snapshot = engine.tick

    def capture_through(target_tick: int) -> None:
        nonlocal next_snapshot
        while next_snapshot <= target_tick:
            engine.advance_to(next_snapshot)
            trace.append(engine.snapshot())
            next_snapshot += snapshot_every_ticks

    for i, event in enumerate(battle.events):
        try:
            # If the cadence lands on the event tick this is intentionally a
            # pre-action snapshot. Actions for that tick are committed only
            # when the engine later advances to tick+1.
            capture_through(event.tick)
            engine.advance_to(event.tick)

            if event.event_type == "card_play":
                assert event.card is not None
                assert event.x_mtile is not None and event.y_mtile is not None
                cell = coords.to_cell(
                    event.x_mtile,
                    event.y_mtile,
                    flip_y=(flip_y_for_opponent and event.side == "opponent"),
                )
                engine.play_card(side=event.side, card=event.card, cell=cell)
            else:
                engine.activate_ability(side=event.side, card=event.ability_card)
        except Exception as exc:
            raise ReplayExecutionError(event.tick, i, repr(exc)) from exc

    if battle.events:
        final_event_tick = battle.events[-1].tick
        flush_tick = final_event_tick + 1
        try:
            # This commits every action queued on the final replay tick.
            capture_through(flush_tick)
            engine.advance_to(flush_tick)
        except Exception as exc:
            raise ReplayExecutionError(
                final_event_tick,
                len(battle.events) - 1,
                repr(exc),
            ) from exc

    final_snapshot = engine.snapshot()
    if not trace or trace[-1] != final_snapshot:
        trace.append(final_snapshot)
    return trace
