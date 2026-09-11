"""Canonical replay input objects.

The replay layer deliberately contains only facts that can be supplied by a
replay extractor: actions, their match tick, and the side which issued them.
The simulator owns all derived state. Validation here is intentionally
strict; accepting a coerced boolean, an unknown side, or an unordered event
stream makes a replay impossible to reproduce deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


Side = Literal["team", "opponent"]
EventType = Literal["card_play", "ability_activation"]
ReplayMode = Literal["placements", "match"]
CoordinateSystem = Literal["world_cells", "player_cells", "world_mtile"]

SIDES = frozenset(("team", "opponent"))
EVENT_TYPES = frozenset(("card_play", "ability_activation"))
REPLAY_MODES = frozenset(("placements", "match"))
COORDINATE_SYSTEMS = frozenset(("world_cells", "player_cells", "world_mtile"))


def _exact_int(value: Any, field_name: str) -> None:
    """Require a real JSON/Python integer, explicitly excluding booleans."""

    if type(value) is not int:
        raise ValueError(f"{field_name} must be an integer")


def _optional_string(value: Any, field_name: str) -> None:
    if value is not None and (type(value) is not str or not value.strip()):
        raise ValueError(f"{field_name} must be a non-empty string or None")


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """One action at an exact simulator tick.

    ``x_mtile``/``y_mtile`` are world coordinates in the canonical schema.
    Human-facing JSON/CSV loaders may accept cell coordinates and convert them
    to the cell centre before constructing this object.
    """

    tick: int
    side: Side
    event_type: EventType
    card: str | None = None
    x_mtile: int | None = None
    y_mtile: int | None = None
    ability_card: str | None = None

    def validate(self) -> None:
        _exact_int(self.tick, "tick")
        if self.tick < 0:
            raise ValueError("tick must be >= 0")

        if type(self.side) is not str or self.side not in SIDES:
            raise ValueError(
                f"side must be one of 'team' or 'opponent', got {self.side!r}"
            )
        if type(self.event_type) is not str or self.event_type not in EVENT_TYPES:
            raise ValueError(
                "event_type must be one of 'card_play' or "
                f"'ability_activation', got {self.event_type!r}"
            )

        if self.card is not None and (
            type(self.card) is not str or not self.card.strip()
        ):
            raise ValueError("card must be a non-empty string or None")
        if self.ability_card is not None and (
            type(self.ability_card) is not str or not self.ability_card.strip()
        ):
            raise ValueError("ability_card must be a non-empty string or None")

        if self.event_type == "card_play":
            if self.card is None or not self.card.strip():
                raise ValueError("card_play requires card")
            if self.x_mtile is None or self.y_mtile is None:
                raise ValueError("card_play requires x/y")
            _exact_int(self.x_mtile, "x_mtile")
            _exact_int(self.y_mtile, "y_mtile")
            if self.x_mtile < 0 or self.y_mtile < 0:
                raise ValueError("card_play coordinates must be >= 0")
            if self.ability_card is not None:
                raise ValueError("card_play cannot carry ability_card")
        else:
            if self.card is not None or self.x_mtile is not None or self.y_mtile is not None:
                raise ValueError("ability_activation cannot carry card-play fields")

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON-safe canonical representation."""

        self.validate()
        value: dict[str, Any] = {
            "tick": self.tick,
            "side": self.side,
            "event_type": self.event_type,
        }
        if self.card is not None:
            value["card"] = self.card
        if self.x_mtile is not None:
            value["x_mtile"] = self.x_mtile
        if self.y_mtile is not None:
            value["y_mtile"] = self.y_mtile
        if self.ability_card is not None:
            value["ability_card"] = self.ability_card
        return value


@dataclass(slots=True)
class ReplayBattle:
    """A deterministic action stream plus simulator provenance.

    The extra metadata fields are optional for callers that construct the
    original low-level object directly. ``replay.io.load_replay`` fills them
    for user-facing JSON/CSV inputs.
    """

    battle_id: str
    ticks_per_second: int = 20
    patch_id: str | None = None
    team_deck: tuple[str, ...] = ()
    opponent_deck: tuple[str, ...] = ()
    team_initial_queue: tuple[str, ...] | None = None
    opponent_initial_queue: tuple[str, ...] | None = None
    events: list[ReplayEvent] = field(default_factory=list)
    schema_version: int = 1
    mode: ReplayMode = "placements"
    ruleset_id: str = "2026-08-04-roster"
    level: int = 11
    seed: int = 0
    coordinate_system: CoordinateSystem = "world_cells"
    end_tick: int | None = None
    initial_state: str | Path | None = None
    physics_profile: str | None = None
    notes: str | None = None

    def validate(self) -> None:
        if type(self.battle_id) is not str or not self.battle_id.strip():
            raise ValueError("battle_id must be a non-empty string")

        _exact_int(self.ticks_per_second, "ticks_per_second")
        if self.ticks_per_second <= 0:
            raise ValueError("ticks_per_second must be positive")

        _exact_int(self.schema_version, "schema_version")
        if self.schema_version != 1:
            raise ValueError("unsupported replay schema version")

        if type(self.mode) is not str or self.mode not in REPLAY_MODES:
            raise ValueError(
                f"mode must be one of 'placements' or 'match', got {self.mode!r}"
            )
        if type(self.coordinate_system) is not str or self.coordinate_system not in COORDINATE_SYSTEMS:
            raise ValueError(
                "coordinate_system must be one of 'world_cells', "
                f"'player_cells', or 'world_mtile', got {self.coordinate_system!r}"
            )

        _optional_string(self.patch_id, "patch_id")
        if type(self.ruleset_id) is not str or not self.ruleset_id.strip():
            raise ValueError("ruleset_id must be a non-empty string")
        _exact_int(self.level, "level")
        if self.level != 11:
            raise ValueError("only level 11 replays are supported")
        _exact_int(self.seed, "seed")
        if self.seed < 0:
            raise ValueError("seed must be >= 0")
        _optional_string(self.notes, "notes")
        _optional_string(self.physics_profile, "physics_profile")
        if self.initial_state is not None and not isinstance(self.initial_state, (str, Path)):
            raise ValueError("initial_state must be a path string or None")
        if isinstance(self.initial_state, str) and not self.initial_state.strip():
            raise ValueError("initial_state must be a non-empty path string or None")

        self._validate_deck("team", self.team_deck)
        self._validate_deck("opponent", self.opponent_deck)
        self._validate_queue("team", self.team_initial_queue, self.team_deck)
        self._validate_queue("opponent", self.opponent_initial_queue, self.opponent_deck)

        if self.mode == "match":
            if len(self.team_deck) != 8 or len(self.opponent_deck) != 8:
                raise ValueError("match mode requires both 8-card decks")

        if not isinstance(self.events, list):
            raise ValueError("events must be a list")
        last = -1
        for index, event in enumerate(self.events):
            if not isinstance(event, ReplayEvent):
                raise ValueError(f"events[{index}] must be ReplayEvent")
            event.validate()
            if event.tick < last:
                raise ValueError("events must be ordered by tick")
            last = event.tick

        if self.end_tick is not None:
            _exact_int(self.end_tick, "end_tick")
            if self.end_tick < 0:
                raise ValueError("end_tick must be >= 0")
            if self.events and self.end_tick < self.events[-1].tick + 1:
                raise ValueError(
                    "end_tick must include at least one physics tick after the last event"
                )

    @staticmethod
    def _validate_deck(side: str, deck: Any) -> None:
        if not isinstance(deck, tuple):
            raise ValueError(f"{side} deck must be a tuple")
        if deck and len(deck) != 8:
            raise ValueError(f"{side} deck must have 8 cards")
        if any(type(card) is not str or not card.strip() for card in deck):
            raise ValueError(f"{side} deck cards must be non-empty strings")
        if len(set(deck)) != len(deck):
            raise ValueError(f"{side} deck cards must be unique")

    @staticmethod
    def _validate_queue(side: str, queue: Any, deck: tuple[str, ...]) -> None:
        if queue is None:
            return
        if not isinstance(queue, tuple) or len(queue) != 8:
            raise ValueError(f"{side} initial queue must have 8 cards")
        if any(type(card) is not str or not card.strip() for card in queue):
            raise ValueError(f"{side} initial queue cards must be non-empty strings")
        if not deck:
            raise ValueError(f"{side} initial queue requires a declared deck")
        if sorted(queue) != sorted(deck):
            raise ValueError(f"{side} initial queue must be a permutation of its deck")

    def to_mapping(self) -> dict[str, Any]:
        """Return a JSON-safe complete replay specification."""

        self.validate()
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "battle_id": self.battle_id,
            "ticks_per_second": self.ticks_per_second,
            "mode": self.mode,
            "ruleset_id": self.ruleset_id,
            "level": self.level,
            "seed": self.seed,
            "coordinate_system": self.coordinate_system,
            "events": [event.to_mapping() for event in self.events],
        }
        if self.patch_id is not None:
            value["patch_id"] = self.patch_id
        if self.team_deck:
            value["team_deck"] = list(self.team_deck)
        if self.opponent_deck:
            value["opponent_deck"] = list(self.opponent_deck)
        if self.team_initial_queue is not None:
            value["team_initial_queue"] = list(self.team_initial_queue)
        if self.opponent_initial_queue is not None:
            value["opponent_initial_queue"] = list(self.opponent_initial_queue)
        if self.end_tick is not None:
            value["end_tick"] = self.end_tick
        if self.initial_state is not None:
            value["initial_state"] = str(self.initial_state)
        if self.physics_profile is not None:
            value["physics_profile"] = self.physics_profile
        if self.notes is not None:
            value["notes"] = self.notes
        return value
