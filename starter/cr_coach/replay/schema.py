from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Side = Literal["team", "opponent"]
EventType = Literal["card_play", "ability_activation"]

@dataclass(frozen=True, slots=True)
class ReplayEvent:
    tick: int
    side: Side
    event_type: EventType
    card: str | None = None
    x_mtile: int | None = None
    y_mtile: int | None = None
    ability_card: str | None = None

    def validate(self) -> None:
        if self.tick < 0:
            raise ValueError("tick must be >= 0")
        if self.event_type == "card_play":
            if not self.card:
                raise ValueError("card_play requires card")
            if self.x_mtile is None or self.y_mtile is None:
                raise ValueError("card_play requires x/y")

@dataclass(slots=True)
class ReplayBattle:
    battle_id: str
    ticks_per_second: int = 20
    patch_id: str | None = None
    team_deck: tuple[str, ...] = ()
    opponent_deck: tuple[str, ...] = ()
    team_initial_queue: tuple[str, ...] | None = None
    opponent_initial_queue: tuple[str, ...] | None = None
    events: list[ReplayEvent] = field(default_factory=list)

    def validate(self) -> None:
        if self.ticks_per_second <= 0:
            raise ValueError("ticks_per_second must be positive")
        if self.team_deck and len(self.team_deck) != 8:
            raise ValueError("team deck must have 8 cards")
        if self.opponent_deck and len(self.opponent_deck) != 8:
            raise ValueError("opponent deck must have 8 cards")
        last = -1
        for event in self.events:
            event.validate()
            if event.tick < last:
                raise ValueError("events must be ordered by tick")
            last = event.tick
