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
    battle.validate()
    coords = coords or ReplayGridAdapter()
    trace: list[dict[str, Any]] = []
    next_snapshot = engine.tick

    for i, event in enumerate(battle.events):
        try:
            while next_snapshot <= event.tick:
                engine.advance_to(next_snapshot)
                trace.append(engine.snapshot())
                next_snapshot += snapshot_every_ticks

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

    trace.append(engine.snapshot())
    return trace
