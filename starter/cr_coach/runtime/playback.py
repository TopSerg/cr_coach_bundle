"""Deterministic playback boundary for the pinned Clash Royale engine.

The upstream simulator deliberately keeps its authoritative state and its
physics engine separate from replay ingestion.  This module is the small
bridge used by :mod:`cr_coach.runtime.runner`:

* ``match`` inputs use the normal ``PlayCardAction`` path, including hand,
  elixir, cycle and legality checks;
* ``placements`` inputs represent placements that have already been observed
  in a real match.  They are injected *inside* the engine's action phase so
  deployment delays and every later physics phase remain unchanged.  No hand
  or elixir value is rewritten for an observed placement.

The module intentionally has no import-time dependency on the upstream
checkout.  This keeps the starter package importable for schema/unit tests;
the real engine is required when a replay is executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


PHYSICS_PROFILE = "hog-crown-bridge-v1"


def _load_physics_base() -> tuple[type, str]:
    """Load the strict coach engine without making imports eager.

    The maintained physics module lives at ``cr_coach.physics``.  The
    ``engine.physics`` fallback is kept for old checkouts that contain the
    first bridge profile but not the new root module.  A plain upstream
    ``BattleEngine`` is deliberately not selected here: runtime playback must
    use the evidence-backed coach profile whenever it is available.
    """

    try:  # normal package layout
        from ..physics import CoachBattleEngine, PHYSICS_PROFILE as profile

        return CoachBattleEngine, str(profile)
    except (ImportError, ModuleNotFoundError):
        try:  # compatibility with the first local bridge commit
            from ..engine.physics import CoachBattleEngine, PHYSICS_PROFILE as profile

            return CoachBattleEngine, str(profile)
        except (ImportError, ModuleNotFoundError):
            # Importing runtime for lightweight tests should still work when
            # the external checkout has not been initialized.  Instantiation
            # then fails with a useful dependency error below.
            class _UnavailableCoachEngine:
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    raise RuntimeError(
                        "CoachBattleEngine is unavailable; initialize the pinned "
                        "cr-bot checkout and make its root importable"
                    )

            return _UnavailableCoachEngine, PHYSICS_PROFILE


_CoachBattleEngine, _loaded_profile = _load_physics_base()
PHYSICS_PROFILE = _loaded_profile or PHYSICS_PROFILE


try:  # only available once the pinned simulator is importable
    from simulator.engine import ActionResult as _UpstreamActionResult
except (ImportError, ModuleNotFoundError):  # pragma: no cover - import guard
    _UpstreamActionResult = None


@dataclass(frozen=True, slots=True)
class _FallbackActionResult:
    player: int
    accepted: bool
    reason: str | None = None
    card_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayPlacementAction:
    """An already-observed card placement consumed during an action phase."""

    player: int
    card_id: str
    cell: tuple[int, int]


# A short public alias is convenient for callers constructing a low-level
# action stream.  Keep the descriptive name above as the canonical one.
PlacementAction = ReplayPlacementAction


class PlaybackActionRejected(RuntimeError):
    """Raised when a queued replay action is rejected by the simulator."""

    def __init__(self, *, tick: int, player: int, reason: str) -> None:
        self.tick = int(tick)
        self.player = int(player)
        self.reason = str(reason)
        super().__init__(
            f"replay action rejected at tick={self.tick}, "
            f"player={self.player}: {self.reason}"
        )


def _result(
    player: int,
    accepted: bool,
    reason: str | None = None,
    card_id: str | None = None,
) -> Any:
    cls = _UpstreamActionResult or _FallbackActionResult
    return cls(player, accepted, reason, card_id)


def _event_value(event: Any, name: str, default: Any = None) -> Any:
    if hasattr(event, name):
        return getattr(event, name)
    if isinstance(event, Mapping):
        if name in event:
            return event[name]
        data = event.get("data")
        if isinstance(data, Mapping):
            return data.get(name, default)
    getter = getattr(event, "get", None)
    if callable(getter):
        return getter(name, default)
    return default


def event_to_dict(event: Any) -> dict[str, Any]:
    """Convert a simulator event or a JSON-like event to a plain dictionary."""

    if isinstance(event, Mapping):
        raw = dict(event)
        data = raw.get("data")
        if isinstance(data, Mapping):
            raw["data"] = dict(data)
        return raw
    serializer = getattr(event, "to_dict", None)
    if callable(serializer):
        raw = serializer()
        if isinstance(raw, Mapping):
            return dict(raw)
    data = _event_value(event, "data", {})
    if not isinstance(data, Mapping):
        data = {}
    return {
        "tick": int(_event_value(event, "tick", 0)),
        "sequence": int(_event_value(event, "sequence", 0)),
        "kind": str(_event_value(event, "kind", _event_value(event, "event_type", "event"))),
        "data": dict(data),
    }


def _state_events(state: Any) -> list[Any]:
    events = getattr(state, "events", ())
    try:
        return list(events)
    except TypeError:
        return []


class PlaybackEngine(_CoachBattleEngine):
    """Coach physics engine with a replay-placement action path.

    ``CoachBattleEngine`` remains the authoritative implementation of every
    mechanic.  The only extra behavior is recognition of
    :class:`ReplayPlacementAction` in ``apply_actions``; it happens at the
    exact point where upstream normally applies a ``PlayCardAction``.  In
    particular, ``_spawn_card_entities`` and ``_spawn_spell`` still create
    normal deployable bodies and do not have their deployment clocks cleared.
    """

    def __init__(
        self,
        *args: Any,
        mode: str = "match",
        validate_placements: bool = True,
        **kwargs: Any,
    ) -> None:
        if mode not in {"placements", "match"}:
            raise ValueError("mode must be placements or match")
        self.playback_mode = mode
        self.validate_placements = bool(validate_placements)
        super().__init__(*args, **kwargs)

    def apply_actions(self, state: Any, actions: Iterable[Any]) -> tuple[Any, ...]:
        actions = tuple(actions)
        replay_actions = tuple(
            action for action in actions if isinstance(action, ReplayPlacementAction)
        )
        normal_actions = tuple(
            action for action in actions if not isinstance(action, ReplayPlacementAction)
        )
        if replay_actions and self.playback_mode != "placements":
            raise ValueError("ReplayPlacementAction is only valid in placements mode")

        # In match mode this is exactly the upstream action implementation.
        results = list(super().apply_actions(state, normal_actions))
        seen_players: set[int] = set()
        for action in replay_actions:
            if action.player in seen_players:
                self._emit(
                    state,
                    "action_rejected",
                    player=action.player,
                    reason="multiple_actions_in_tick",
                )
                results.append(
                    _result(action.player, False, "multiple_actions_in_tick")
                )
                continue
            seen_players.add(action.player)
            results.append(self._apply_replay_placement(state, action))
        return tuple(results)

    def _apply_replay_placement(
        self,
        state: Any,
        action: ReplayPlacementAction,
    ) -> Any:
        player = action.player
        if type(player) is not int or player not in (0, 1):
            self._emit(state, "action_rejected", player=player, reason="invalid_player")
            return _result(player, False, "invalid_player")
        cell = action.cell
        if (
            not isinstance(cell, tuple)
            or len(cell) != 2
            or any(type(value) is not int for value in cell)
        ):
            self._emit(
                state,
                "action_rejected",
                player=player,
                reason="invalid_cell",
            )
            return _result(player, False, "invalid_cell")
        try:
            card_id = str(self.ruleset.resolve_card_id(action.card_id))
            card = self.ruleset.card(card_id)
        except (KeyError, TypeError, ValueError):
            self._emit(
                state,
                "action_rejected",
                player=player,
                reason="unknown_card",
            )
            return _result(player, False, "unknown_card")

        col, row = cell
        grid = getattr(self.ruleset, "arena", None)
        columns = int(getattr(grid, "grid_columns", 18))
        rows = int(getattr(grid, "grid_rows", 32))
        if not (0 <= col < columns and 0 <= row < rows):
            self._emit(
                state,
                "action_rejected",
                player=player,
                reason="invalid_cell",
            )
            return _result(player, False, "invalid_cell", card_id)

        if self.validate_placements:
            legal = self._legal_deployment(state, player, card, cell)
            if not legal:
                self._emit(
                    state,
                    "action_rejected",
                    player=player,
                    reason="illegal_placement",
                )
                return _result(player, False, "illegal_placement", card_id)

        # Keep the action event in the same relative order as upstream
        # ``_play_card``.  The replay path has no hand slot or payable cost;
        # null values make that distinction explicit in JSON without inventing
        # economic facts that were not present in a placement-only replay.
        self._emit(
            state,
            "card_played",
            player=player,
            card_id=card_id,
            card_slot=None,
            col=col,
            row=row,
            cost_milli=None,
            replay_mode="placements",
        )
        if card.kind == "spell":
            self._spawn_spell(state, player, card, cell)
        else:
            self._spawn_card_entities(state, player, card, cell)
        return _result(player, True, card_id=card_id)

    def authoritative_snapshot(
        self,
        state: Any,
        *,
        include_events: bool = False,
    ) -> dict[str, Any]:
        """Return the full engine state used by checkpoint serialization."""

        serializer = getattr(state, "to_primitive", None)
        if callable(serializer):
            raw = serializer(include_events=include_events)
            return dict(raw)
        if isinstance(state, Mapping):
            return dict(state)
        raise TypeError("battle state does not provide to_primitive()")

    def public_snapshot(
        self,
        state: Any,
        *,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Return a JSON-safe public snapshot for trace/viewer consumers.

        Placement-only inputs intentionally contain no recoverable economic
        timeline.  Hide all hand/cycle/elixir fields in those snapshots while
        retaining crowns and the complete physical state.  Match mode uses
        the normal upstream player values unchanged.
        """

        selected_mode = mode or self.playback_mode
        if selected_mode not in {"placements", "match"}:
            raise ValueError("mode must be placements or match")
        raw = self.authoritative_snapshot(state, include_events=False)
        raw["backend"] = "coach"
        raw["physics_profile"] = PHYSICS_PROFILE
        raw["mode"] = selected_mode
        if selected_mode == "placements":
            for player in raw.get("players", ()):
                if not isinstance(player, dict):
                    continue
                # These are the economic/hidden-cycle values.  Crown outcome
                # and king activation remain observable match state.
                for key in (
                    "deck",
                    "hand",
                    "draw_pile",
                    "elixir_milli",
                    "elixir_remainder",
                    "cards_played",
                    "seen_enemy_cards",
                    "last_played_card_id",
                    "next_card_cooldown_us",
                ):
                    if key in player:
                        player[key] = None
        return raw

    # A familiar ``snapshot`` spelling keeps the object useful in small
    # integrations that pass an engine rather than a boundary adapter.
    def snapshot(self, state: Any, *, mode: str | None = None) -> dict[str, Any]:
        return self.public_snapshot(state, mode=mode)


class PlaybackAdapter:
    """Replay-time adapter with strict tick and event handling."""

    def __init__(
        self,
        *,
        engine: PlaybackEngine,
        state: Any,
        mode: str = "match",
        include_existing_events: bool = True,
    ) -> None:
        if mode not in {"placements", "match"}:
            raise ValueError("mode must be placements or match")
        self._engine = engine
        self._state = state
        self.mode = mode
        self._pending_actions: dict[int, dict[int, Any]] = {}
        self._event_cursor = 0 if include_existing_events else len(_state_events(state))
        self._event_records: list[dict[str, Any]] = []
        self._collect_new_events()

    @property
    def tick(self) -> int:
        return int(self._state.tick)

    @property
    def state(self) -> Any:
        return self._state

    @property
    def engine(self) -> PlaybackEngine:
        return self._engine

    @property
    def event_records(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._event_records]

    def take_event_records(self) -> list[dict[str, Any]]:
        records = self._event_records
        self._event_records = []
        return [dict(row) for row in records]

    def play_card(
        self,
        *,
        side: str,
        card: str,
        cell: tuple[int, int],
    ) -> None:
        player = self._player(side)
        pending = self._pending_actions.setdefault(self.tick, {})
        if player in pending:
            raise PlaybackActionRejected(
                tick=self.tick,
                player=player,
                reason="multiple_actions_in_tick",
            )
        if self.mode == "placements":
            pending[player] = ReplayPlacementAction(player, str(card), tuple(cell))
            return

        # Match mode follows the same hand/slot logic as CrBotEngineAdapter,
        # but keeps the actual engine class strict by receiving our
        # CoachBattleEngine instance.
        card_id = self._resolve_card_id(card)
        slot = self._slot_available_on_current_tick(player, card_id)
        if slot is None:
            hand = list(getattr(self._state.players[player], "hand", ()))
            raise PlaybackActionRejected(
                tick=self.tick,
                player=player,
                reason=f"card_not_in_hand:{card_id}; hand={hand}",
            )
        try:
            from simulator.actions import PlayCardAction
        except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover
            raise RuntimeError("pinned simulator actions are unavailable") from exc
        pending[player] = PlayCardAction(player, slot, tuple(cell))

    def activate_ability(self, *, side: str, card: str | None) -> None:
        # The pinned backend deliberately rejects unsupported abilities.  Fail
        # before mutating the pending stream so a report points at this event.
        raise NotImplementedError(
            f"ability replay is not supported yet: tick={self.tick}, "
            f"side={side}, card={card!r}"
        )

    def advance_to(self, tick: int) -> None:
        if type(tick) is not int or tick < 0:
            raise ValueError("target tick must be a non-negative integer")
        if tick < self.tick:
            raise ValueError(f"cannot rewind replay from tick {self.tick} to {tick}")
        while self.tick < tick:
            if bool(getattr(self._state, "terminal", False)):
                # Upstream intentionally returns without incrementing a
                # terminal state.  Stop cleanly instead of spinning forever.
                break
            current_tick = self.tick
            pending = self._pending_actions.pop(current_tick, {})
            actions = tuple(pending[player] for player in sorted(pending))
            before = len(_state_events(self._state))
            self._engine.step(self._state, actions)
            self._collect_new_events(start=before, fallback_tick=current_tick)
            if self.tick <= current_tick:
                raise RuntimeError(
                    "engine.step did not advance the battle tick; "
                    "cannot continue deterministic playback"
                )
            self._raise_on_rejected_actions(current_tick, pending)

    def snapshot(self) -> dict[str, Any]:
        return self._engine.public_snapshot(self._state, mode=self.mode)

    def authoritative_snapshot(self) -> dict[str, Any]:
        return self._engine.authoritative_snapshot(self._state, include_events=False)

    def _collect_new_events(
        self,
        *,
        start: int | None = None,
        fallback_tick: int | None = None,
    ) -> None:
        events = _state_events(self._state)
        begin = self._event_cursor if start is None else max(0, int(start))
        if begin > len(events):
            begin = len(events)
        for event in events[begin:]:
            record = event_to_dict(event)
            kind = str(record.get("kind", record.get("event_type", "event")))
            raw_tick = record.get("tick", fallback_tick if fallback_tick is not None else self.tick)
            try:
                event_tick = int(raw_tick)
            except (TypeError, ValueError):
                event_tick = int(fallback_tick if fallback_tick is not None else self.tick)
            # ``match_started`` is emitted while state.tick is still zero.
            # Every event produced by the physics step at tick N is observed
            # after that step, at state tick N+1.
            record["tick"] = event_tick
            record["state_tick"] = event_tick if kind == "match_started" else event_tick + 1
            record["mode"] = self.mode
            record["physics_profile"] = PHYSICS_PROFILE
            self._event_records.append(record)
        self._event_cursor = len(events)

    def _raise_on_rejected_actions(
        self,
        tick: int,
        pending: Mapping[int, Any],
    ) -> None:
        if not pending:
            return
        pending_players = set(pending)
        for record in reversed(self._event_records):
            if int(record.get("tick", -1)) != tick:
                # Records are append-only and ordered; once earlier ticks are
                # reached no action rejection for this step can follow.
                if int(record.get("tick", -1)) < tick:
                    break
                continue
            if str(record.get("kind", "")) != "action_rejected":
                continue
            data = record.get("data")
            if not isinstance(data, Mapping):
                data = record
            player = data.get("player")
            if player not in pending_players:
                continue
            raise PlaybackActionRejected(
                tick=tick,
                player=int(player),
                reason=str(data.get("reason", "unknown")),
            )

    def _player(self, side: str) -> int:
        if side == "team":
            return 0
        if side == "opponent":
            return 1
        raise ValueError(f"unknown replay side: {side!r}")

    def _resolve_card_id(self, card: str) -> str:
        resolver = getattr(self._engine.ruleset, "resolve_card_id", None)
        if callable(resolver):
            return str(resolver(card))
        return str(card)

    def _slot_available_on_current_tick(self, player: int, card_id: str) -> int | None:
        player_state = self._state.players[player]
        hand = list(getattr(player_state, "hand", ()))
        if card_id in hand:
            return hand.index(card_id)
        hand_size = int(getattr(self._engine.ruleset.match, "hand_size", 4))
        draw_pile = list(getattr(player_state, "draw_pile", ()))
        if len(hand) >= hand_size or not draw_pile or draw_pile[0] != card_id:
            return None
        cooldown = int(getattr(player_state, "next_card_cooldown_us", 0))
        tick_us = int(getattr(self._engine.ruleset, "tick_us", 50_000))
        if cooldown == 0 or cooldown <= tick_us:
            return len(hand)
        return None


__all__ = [
    "PHYSICS_PROFILE",
    "PlaybackActionRejected",
    "PlaybackAdapter",
    "PlaybackEngine",
    "PlacementAction",
    "ReplayPlacementAction",
    "event_to_dict",
]
