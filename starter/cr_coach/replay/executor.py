"""Deterministic replay scheduling over a backend-neutral engine adapter."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import Any, Iterator

from cr_coach.adapters.coordinates import ReplayGridAdapter
from cr_coach.engine.protocol import EngineAdapter
from cr_coach.replay.schema import ReplayBattle, ReplayEvent


@dataclass(slots=True)
class ReplayExecutionError(RuntimeError):
    tick: int
    event_index: int
    reason: str

    def __str__(self) -> str:
        return f"replay divergence at tick={self.tick}, event={self.event_index}: {self.reason}"


def _terminal(snapshot: Any, engine: EngineAdapter | None = None) -> bool:
    """Read terminal state from the public snapshot or optional adapter flag."""

    if isinstance(snapshot, dict):
        if snapshot.get("terminal") is True:
            return True
        phase = snapshot.get("phase")
        if isinstance(phase, str) and phase.lower() in {
            "ended",
            "complete",
            "completed",
            "finished",
            "game_over",
            "game-over",
            "terminal",
        }:
            return True
        for key in ("game_over", "game_over", "ended", "finished"):
            if snapshot.get(key) is True:
                return True
    if engine is not None:
        for name in ("terminal", "is_terminal"):
            value = getattr(engine, name, None)
            if callable(value):
                value = value()
            if value is True:
                return True
    return False


def _event_groups(events: list[ReplayEvent]) -> Iterator[tuple[int, int, list[ReplayEvent]]]:
    """Yield stable same-tick groups with the original first event index."""

    for tick, group in groupby(enumerate(events), key=lambda item: item[1].tick):
        rows = list(group)
        yield tick, rows[0][0], [event for _, event in rows]


def iter_replay(
    battle: ReplayBattle,
    engine: EngineAdapter,
    *,
    coords: ReplayGridAdapter | None = None,
    flip_y_for_opponent: bool = False,
    snapshot_every_ticks: int = 1,
    end_tick: int | None = None,
    horizon_tick: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream authoritative snapshots while executing one replay.

    Actions sharing a tick are queued before any physics step crosses that
    tick.  ``end_tick`` is an absolute exclusive physics cursor: a buffered
    action at tick ``N`` is committed by advancing to at least ``N + 1``.
    With no explicit horizon, a replay ends after that flush tick, preserving
    the original low-level executor behaviour.  A terminal backend state stops
    the horizon loop immediately; an action encountered after that state is a
    replay error with the original event index.
    """

    battle.validate()
    if type(snapshot_every_ticks) is not int or snapshot_every_ticks <= 0:
        raise ValueError("snapshot_every_ticks must be positive")
    if end_tick is not None and horizon_tick is not None and end_tick != horizon_tick:
        raise ValueError("end_tick and horizon_tick disagree")
    requested_end = horizon_tick if horizon_tick is not None else end_tick
    if requested_end is not None and (type(requested_end) is not int or requested_end < 0):
        raise ValueError("end_tick must be a non-negative integer")
    if battle.end_tick is not None:
        if requested_end is not None and requested_end != battle.end_tick:
            raise ValueError("executor end_tick differs from replay end_tick")
        requested_end = battle.end_tick

    coords = coords or ReplayGridAdapter()
    next_snapshot = engine.tick
    last_snapshot_tick: int | None = None

    def snapshot_now() -> dict[str, Any]:
        snapshot = engine.snapshot()
        if not isinstance(snapshot, dict):
            raise TypeError("engine.snapshot() must return a dictionary")
        return snapshot

    def advance_to(target: int, *, event_tick: int, event_index: int) -> dict[str, Any]:
        try:
            engine.advance_to(target)
            snapshot = snapshot_now()
        except ReplayExecutionError:
            raise
        except Exception as exc:
            raise ReplayExecutionError(event_tick, event_index, repr(exc)) from exc
        return snapshot

    def capture_until(target: int, *, context_tick: int, context_index: int) -> Iterator[dict[str, Any]]:
        nonlocal next_snapshot, last_snapshot_tick
        while next_snapshot <= target:
            snapshot = advance_to(
                next_snapshot,
                event_tick=context_tick,
                event_index=context_index,
            )
            current_tick = engine.tick
            if current_tick < next_snapshot and not _terminal(snapshot, engine):
                raise ReplayExecutionError(
                    context_tick,
                    context_index,
                    f"engine stopped at tick={current_tick} before requested tick={next_snapshot}",
                )
            # Adapters expose one snapshot per cursor tick. Keep a duplicate
            # terminal snapshot from polluting the trace if advance_to is a
            # no-op after terminal.
            if current_tick != last_snapshot_tick:
                last_snapshot_tick = current_tick
                yield snapshot
            next_snapshot += snapshot_every_ticks
            if _terminal(snapshot, engine):
                return

    # Capture the initial state and every requested cadence point before each
    # same-tick action group. A current tick may already have a queued action;
    # advancing to it remains a deliberate pre-action no-op.
    grouped = list(_event_groups(battle.events))
    terminal_seen = False
    for tick, first_index, events in grouped:
        for snapshot in capture_until(tick, context_tick=tick, context_index=first_index):
            terminal_seen = _terminal(snapshot, engine)
            yield snapshot
            if terminal_seen:
                break
        if terminal_seen or _terminal(snapshot_now(), engine):
            raise ReplayExecutionError(tick, first_index, "match_ended before replay event")

        pre_event = advance_to(tick, event_tick=tick, event_index=first_index)
        if _terminal(pre_event, engine):
            raise ReplayExecutionError(tick, first_index, "match_ended before replay event")

        for offset, event in enumerate(events):
            event_index = first_index + offset
            try:
                if event.event_type == "card_play":
                    # validate() guarantees these are present and typed.
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
                raise ReplayExecutionError(event.tick, event_index, repr(exc)) from exc

    if grouped:
        default_end = grouped[-1][0] + 1
    else:
        default_end = engine.tick
    target_end = default_end if requested_end is None else requested_end
    if target_end < default_end:
        raise ValueError(
            f"end_tick={target_end} is before the action flush tick {default_end}"
        )

    context_tick = grouped[-1][0] if grouped else engine.tick
    context_index = grouped[-1][1] if grouped else -1
    for snapshot in capture_until(target_end, context_tick=context_tick, context_index=context_index):
        yield snapshot
        if _terminal(snapshot, engine):
            return

    # ``capture_until`` advances only to cadence points. Ensure an explicit
    # horizon and the final action tick are committed even when the cadence
    # skips over the exact endpoint.
    if engine.tick < target_end:
        snapshot = advance_to(target_end, event_tick=context_tick, event_index=context_index)
        if engine.tick < target_end and not _terminal(snapshot, engine):
            raise ReplayExecutionError(
                context_tick,
                context_index,
                f"engine stopped at tick={engine.tick} before requested tick={target_end}",
            )
        if engine.tick != last_snapshot_tick:
            yield snapshot
        if _terminal(snapshot, engine):
            return

    final = snapshot_now()
    if engine.tick != last_snapshot_tick or not _terminal(final, engine):
        # If the last yielded sample is at this tick but is the pre-action
        # snapshot, the state has changed only when a physics step committed
        # an action; in that case the tick differs. This branch mainly keeps
        # no-event/empty-cadence adapters useful.
        if engine.tick != last_snapshot_tick:
            yield final


def execute_replay(
    battle: ReplayBattle,
    engine: EngineAdapter,
    *,
    coords: ReplayGridAdapter | None = None,
    flip_y_for_opponent: bool = False,
    snapshot_every_ticks: int = 1,
    end_tick: int | None = None,
    horizon_tick: int | None = None,
) -> list[dict[str, Any]]:
    """Execute one replay and collect the snapshots produced by ``iter_replay``."""

    return list(
        iter_replay(
            battle,
            engine,
            coords=coords,
            flip_y_for_opponent=flip_y_for_opponent,
            snapshot_every_ticks=snapshot_every_ticks,
            end_tick=end_tick,
            horizon_tick=horizon_tick,
        )
    )
