"""Run strict replay inputs and write reproducible playback artifacts.

The runner is intentionally small and file based.  A replay is normalized by
``cr_coach.replay.io`` before it reaches this module; the runner only executes
that normalized object, records public snapshots/events, and writes a full
checkpoint that can be resumed at a later absolute tick.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from .playback import (
    PHYSICS_PROFILE,
    PlaybackActionRejected,
    PlaybackAdapter,
    PlaybackEngine,
    event_to_dict,
)


RUNTIME_VERSION = "cr-coach-replay-v1"
CRBOT_PIN = "40ca2b16bc276fc982a3aa80c7415b24439cbd3c"
DEFAULT_END_TICK = 300 * 20
FIDELITY_STATUS = "unverified_against_real_game"
_OUTPUT_NAMES = frozenset(
    {"report.json", "checkpoint.json", "events.jsonl", "snapshots.jsonl", "replay.html"}
)


class ReplayRuntimeError(RuntimeError):
    """Base exception raised by the runtime runner."""


class CheckpointMismatchError(ReplayRuntimeError, ValueError):
    """Raised when a checkpoint belongs to another runtime or replay mode."""


def write_json(path: str | Path, payload: Any) -> Path:
    """Write JSON atomically and return the destination path."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    )
    _atomic_write(destination, text + "\n")
    return destination


def write_jsonl(path: str | Path, rows: Iterable[Any]) -> Path:
    """Write one JSON value per line atomically."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default)
        for row in rows
    ]
    _atomic_write(destination, ("\n".join(lines) + "\n") if lines else "")
    return destination


def _atomic_write(destination: Path, text: str) -> None:
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _mode(spec: Any) -> str:
    mode = str(_get(spec, "mode", "placements") or "placements").strip().lower()
    if mode not in {"placements", "match"}:
        raise ValueError("mode must be placements or match")
    return mode


def _events(spec: Any) -> tuple[Any, ...]:
    raw = _get(spec, "events", ())
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
        raise ValueError("replay events must be an iterable")
    return tuple(raw)


def _event_tick(event: Any) -> int:
    for name in ("tick", "ticks", "time_tick"):
        value = _get(event, name, None)
        if value is not None:
            if type(value) is not int or value < 0:
                raise ValueError(f"event {name} must be a non-negative integer")
            return value
    # A strict ReplayInput should already have converted seconds to ticks.
    # Keeping this fallback makes the runner useful with a hand-built object,
    # but refuses lossy floating point conversion.
    seconds = _get(event, "time", _get(event, "seconds", None))
    if type(seconds) is int and seconds >= 0:
        return seconds * 20
    raise ValueError("normalized replay event is missing integer tick")


def _event_side(event: Any) -> str:
    side = str(_get(event, "side", "")).strip().lower()
    if side not in {"team", "opponent"}:
        raise ValueError(f"event side must be team or opponent, got {side!r}")
    return side


def _event_type(event: Any) -> str:
    raw = _get(event, "event_type", _get(event, "type", "card_play"))
    value = str(raw or "card_play").strip().lower()
    if value in {"card", "play", "card_play", "placement"}:
        return "card_play"
    if value in {"ability", "ability_activation", "activate_ability"}:
        return "ability_activation"
    raise ValueError(f"unsupported replay event type: {raw!r}")


def _cell_from_event(event: Any, *, spec: Any = None) -> tuple[int, int]:
    raw_cell = _get(event, "cell", None)
    if raw_cell is not None:
        if (
            not isinstance(raw_cell, (tuple, list))
            or len(raw_cell) != 2
            or any(type(value) is not int for value in raw_cell)
        ):
            raise ValueError("event cell must contain two integers")
        return int(raw_cell[0]), int(raw_cell[1])

    world = _get(event, "world_mtile", None)
    if world is not None:
        if isinstance(world, Mapping):
            x_value, y_value = world.get("x"), world.get("y")
        elif isinstance(world, (tuple, list)) and len(world) == 2:
            x_value, y_value = world
        else:
            raise ValueError("world_mtile must be an [x, y] pair")
        if type(x_value) is not int or type(y_value) is not int:
            raise ValueError("world_mtile coordinates must be integers")
        if x_value % 1_000 != 500 or y_value % 1_000 != 500:
            raise ValueError("world_mtile coordinates must be cell centers")
        return x_value // 1_000, y_value // 1_000

    x_value = _get(event, "x", None)
    y_value = _get(event, "y", None)
    if x_value is None or y_value is None:
        x_value = _get(event, "x_mtile", None)
        y_value = _get(event, "y_mtile", None)
        if type(x_value) is int and type(y_value) is int:
            if x_value % 1_000 != 500 or y_value % 1_000 != 500:
                raise ValueError("milli-tile coordinates must be cell centers")
            return x_value // 1_000, y_value // 1_000
    if type(x_value) is not int or type(y_value) is not int:
        raise ValueError("card-play event requires integer x/y cell coordinates")
    cell = (x_value, y_value)

    # ``replay/io.py`` normally performs this transformation.  Apply it only
    # for a hand-built input that explicitly retains player-local coordinates.
    coordinate_system = str(
        _get(event, "coordinate_system", _get(spec, "coordinate_system", "world_cells"))
        or "world_cells"
    ).strip().lower()
    if coordinate_system in {"player_cells", "player_local", "local_cells"}:
        if _event_side(event) == "opponent":
            return 17 - cell[0], 31 - cell[1]
    return cell


def _event_card(event: Any) -> str | None:
    value = _get(event, "card", None)
    if value is None:
        value = _get(event, "ability_card", None)
    return None if value is None else str(value)


def _seed(spec: Any) -> int:
    value = _get(spec, "seed", 0)
    if type(value) is not int:
        raise ValueError("seed must be an integer")
    return value


def _ruleset_id(spec: Any) -> str:
    value = _get(spec, "ruleset_id", "2026-08-04-roster") or "2026-08-04-roster"
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ruleset_id must be a non-empty string")
    return value


def _end_tick(spec: Any, events: Sequence[Any]) -> int:
    value = _get(spec, "end_tick", None)
    if value is None:
        value = _get(spec, "duration_ticks", None)
    if value is None:
        value = DEFAULT_END_TICK
    if type(value) is not int or value < 0:
        raise ValueError("end_tick must be a non-negative integer")
    if events:
        last = max(_event_tick(event) for event in events)
        if value < last + 1:
            raise ValueError("end_tick must include at least one tick after the last event")
    return value


def _deck(spec: Any, side: str) -> tuple[str, ...] | None:
    value = _get(spec, f"{side}_deck", None)
    # ``ReplayBattle`` represents an omitted optional deck as ``()``.  In
    # placements mode this must select the inert fallback deck rather than be
    # mistaken for an explicitly malformed declaration.
    if value is None or value == () or value == []:
        return None
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{side}_deck must be a sequence of eight card IDs")
    deck = tuple(str(card) for card in value)
    if len(deck) != 8:
        raise ValueError(f"{side}_deck must contain exactly eight cards")
    return deck


def _initial_queue(spec: Any, side: str) -> tuple[str, ...] | None:
    value = _get(spec, f"{side}_initial_queue", None)
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{side}_initial_queue must be a sequence of eight card IDs")
    queue = tuple(str(card) for card in value)
    if len(queue) != 8:
        raise ValueError(f"{side}_initial_queue must contain exactly eight cards")
    return queue


def _deck_pair(spec: Any, mode: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    team = _deck(spec, "team")
    opponent = _deck(spec, "opponent")
    if team is not None and opponent is not None:
        return team, opponent
    if mode == "match":
        raise ValueError("match mode requires team_deck and opponent_deck")
    # Placements mode deliberately has no economic reconstruction.  The
    # canonical cycle deck only seeds the inert state fields which are masked
    # from public snapshots; observed cards are spawned by the replay action
    # path itself.
    try:
        from simulator.engine import BASE_HOG_CYCLE_DECK

        fallback = tuple(BASE_HOG_CYCLE_DECK)
    except (ImportError, ModuleNotFoundError):
        fallback = (
            "hog-rider",
            "cannon",
            "musketeer",
            "skeletons",
            "ice-golem",
            "ice-spirit",
            "fireball",
            "the-log",
        )
    if team is None:
        team = fallback
    if opponent is None:
        opponent = fallback
    return team, opponent


def _load_ruleset(ruleset_id: str) -> Any:
    try:
        from simulator.ruleset import load_ruleset
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover
        raise RuntimeError(
            "pinned cr-bot is unavailable; initialize the backend and add it "
            "to PYTHONPATH"
        ) from exc
    return load_ruleset(ruleset_id)


def _engine_version(engine: Any, state: Any) -> str | None:
    value = _get(state, "engine_version", None)
    if value is None:
        try:
            from simulator.engine import ENGINE_VERSION

            value = ENGINE_VERSION
        except (ImportError, ModuleNotFoundError):
            value = _get(engine, "engine_version", None)
    return None if value is None else str(value)


def _ruleset_hash(engine: Any, state: Any) -> str | None:
    value = _get(state, "ruleset_hash", None)
    if value is None:
        ruleset = _get(engine, "ruleset", None)
        value = _get(ruleset, "content_hash", None)
    return None if value is None else str(value)


def _state_raw(adapter: Any) -> dict[str, Any]:
    state = getattr(adapter, "state", None)
    engine = getattr(adapter, "engine", None)
    if state is None:
        raise RuntimeError("replay adapter does not expose authoritative state")
    serializer = getattr(engine, "authoritative_snapshot", None)
    if callable(serializer):
        return dict(serializer(state, include_events=True))
    serializer = getattr(state, "to_primitive", None)
    if callable(serializer):
        return dict(serializer(include_events=True))
    if isinstance(state, Mapping):
        return dict(state)
    raise RuntimeError("authoritative state cannot be serialized")


def _state_hash(state_raw: Mapping[str, Any], state: Any = None) -> str:
    if state is not None:
        method = getattr(state, "state_hash", None)
        if callable(method):
            return str(method())
    # state_hash intentionally excludes event history in cr-bot; mirror that
    # contract for a JSON-only/fake state as far as possible.
    canonical = dict(state_raw)
    canonical.pop("events", None)
    encoded = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _snapshot_record(adapter: PlaybackAdapter, *, runtime_version: str = RUNTIME_VERSION) -> dict[str, Any]:
    record = dict(adapter.snapshot())
    record.setdefault("tick", int(adapter.tick))
    record["state_tick"] = int(record.get("tick", adapter.tick))
    record["runtime_version"] = runtime_version
    record["physics_profile"] = PHYSICS_PROFILE
    record["mode"] = adapter.mode
    return record


def _event_records(adapter: PlaybackAdapter) -> list[dict[str, Any]]:
    rows = adapter.take_event_records()
    output: list[dict[str, Any]] = []
    for event in rows:
        record = event_to_dict(event)
        record.setdefault("mode", adapter.mode)
        record.setdefault("physics_profile", PHYSICS_PROFILE)
        record.setdefault("runtime_version", RUNTIME_VERSION)
        kind = str(record.get("kind", record.get("event_type", "event")))
        tick = record.get("tick")
        if type(tick) is int:
            record.setdefault("state_tick", tick if kind == "match_started" else tick + 1)
        output.append(record)
    return output


def _metadata(
    *,
    mode: str,
    state: Any,
    engine: Any,
    state_hash: str,
    resumable: bool,
) -> dict[str, Any]:
    ruleset_id = _get(state, "ruleset_id", _get(_get(engine, "ruleset", None), "ruleset_id", None))
    ruleset_hash = _ruleset_hash(engine, state)
    engine_version = _engine_version(engine, state)
    metadata: dict[str, Any] = {
        "runtime_version": RUNTIME_VERSION,
        "upstream_commit": CRBOT_PIN,
        "physics_profile": PHYSICS_PROFILE,
        "mode": mode,
        "resumable": bool(resumable),
        "state_hash": state_hash,
        "statehash": state_hash,
        "ruleset_id": None if ruleset_id is None else str(ruleset_id),
        "ruleset_hash": ruleset_hash,
        "engine_version": engine_version,
        "engineversion": engine_version,
    }
    metadata["ruleset"] = {
        "id": metadata["ruleset_id"],
        "hash": metadata["ruleset_hash"],
    }
    return metadata


def _checkpoint_payload(
    *,
    adapter: PlaybackAdapter,
    state_raw: Mapping[str, Any],
    state_hash: str,
    mode: str,
    resumable: bool,
    report_status: str,
) -> dict[str, Any]:
    metadata = _metadata(
        mode=mode,
        state=adapter.state,
        engine=adapter.engine,
        state_hash=state_hash,
        resumable=resumable,
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "checkpoint_version": 1,
        **metadata,
        "status": report_status,
        "state": dict(state_raw),
    }
    return payload


def _checkpoint_state(path: Path, *, spec: Any, mode: str, engine: Any) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointMismatchError(f"cannot read checkpoint {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CheckpointMismatchError("checkpoint root must be an object")

    def require(name: str, expected: Any) -> None:
        actual = payload.get(name)
        if actual != expected:
            raise CheckpointMismatchError(
                f"checkpoint {name} mismatch: expected {expected!r}, got {actual!r}"
            )

    require("runtime_version", RUNTIME_VERSION)
    require("upstream_commit", CRBOT_PIN)
    require("physics_profile", PHYSICS_PROFILE)
    require("mode", mode)
    if payload.get("resumable") is not True:
        raise CheckpointMismatchError("checkpoint is not resumable")

    raw_state = payload.get("state")
    if not isinstance(raw_state, Mapping):
        raise CheckpointMismatchError("checkpoint is missing state object")
    try:
        from simulator.state import battle_state_from_primitive

        state = battle_state_from_primitive(dict(raw_state))
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover
        raise RuntimeError("pinned simulator state loader is unavailable") from exc
    except (TypeError, KeyError, ValueError) as exc:
        raise CheckpointMismatchError(f"invalid checkpoint state: {exc}") from exc

    expected_hash = _state_hash(raw_state, state)
    stored_hash = payload.get("state_hash", payload.get("statehash"))
    if stored_hash != expected_hash:
        raise CheckpointMismatchError(
            f"checkpoint state hash mismatch: stored {stored_hash!r}, computed {expected_hash!r}"
        )
    if payload.get("statehash", expected_hash) != expected_hash:
        raise CheckpointMismatchError("checkpoint statehash does not match state_hash")

    state_ruleset_id = _get(state, "ruleset_id", None)
    state_ruleset_hash = _get(state, "ruleset_hash", None)
    state_engine_version = _get(state, "engine_version", None)
    requested_ruleset = _ruleset_id(spec)
    if state_ruleset_id != requested_ruleset:
        raise CheckpointMismatchError(
            f"checkpoint ruleset mismatch: expected {requested_ruleset!r}, got {state_ruleset_id!r}"
        )
    if payload.get("ruleset_id") != state_ruleset_id:
        raise CheckpointMismatchError("checkpoint ruleset_id does not match state")
    if payload.get("ruleset_hash") != state_ruleset_hash:
        raise CheckpointMismatchError("checkpoint ruleset_hash does not match state")
    if payload.get("engine_version") != state_engine_version:
        raise CheckpointMismatchError("checkpoint engine_version does not match state")
    if payload.get("engineversion") != state_engine_version:
        raise CheckpointMismatchError("checkpoint engineversion does not match state")
    ruleset = _get(engine, "ruleset", None)
    if ruleset is not None and _get(ruleset, "content_hash", state_ruleset_hash) != state_ruleset_hash:
        raise CheckpointMismatchError("checkpoint ruleset hash does not match the runtime ruleset")
    validator = getattr(engine, "validate_state", None)
    if callable(validator):
        try:
            validator(state)
        except (TypeError, ValueError) as exc:
            raise CheckpointMismatchError(f"checkpoint state failed validation: {exc}") from exc
    return state


def make_adapter(
    spec: Any,
    *,
    state: Any | None = None,
    engine: Any | None = None,
    include_existing_events: bool = True,
) -> PlaybackAdapter:
    """Construct the strict coach adapter for a normalized replay input."""

    mode = _mode(spec)
    ruleset_id = _ruleset_id(spec)
    ruleset = _load_ruleset(ruleset_id)
    if engine is None:
        # Importing this class from playback is intentional: a plain upstream
        # BattleEngine would silently skip the evidence-backed routing profile.
        engine = PlaybackEngine(ruleset=ruleset, mode=mode)
    else:
        configured_ruleset = _get(engine, "ruleset", None)
        if configured_ruleset is not None:
            configured_id = _get(configured_ruleset, "ruleset_id", ruleset_id)
            if configured_id != ruleset_id:
                raise ValueError(
                    f"engine ruleset {configured_id!r} differs from replay {ruleset_id!r}"
                )
    if state is None:
        decks = _deck_pair(spec, mode)
        queues = (_initial_queue(spec, "team"), _initial_queue(spec, "opponent"))
        # The upstream constructor accepts a deck order but not a separate
        # queue.  ``ReplayInput`` uses initial_queue as the deck order in match
        # mode, matching CrBotEngineAdapter's deterministic contract.
        if mode == "match":
            decks = (
                queues[0] if queues[0] is not None else decks[0],
                queues[1] if queues[1] is not None else decks[1],
            )
        state = engine.new_battle(decks=decks, seed=_seed(spec), shuffle_decks=False)
    if not isinstance(engine, PlaybackEngine):
        # A caller supplied fake/test engine is supported, but a production
        # adapter must be the coach engine.  Test doubles can implement the
        # same surface without importing the heavy checkout.
        if not hasattr(engine, "step") or not hasattr(engine, "ruleset"):
            raise TypeError("engine must be a CoachBattleEngine-compatible object")
    return PlaybackAdapter(
        engine=engine,
        state=state,
        mode=mode,
        include_existing_events=include_existing_events,
    )


def run_replay(
    spec: Any,
    out_dir: str | Path,
    *,
    sample_ticks: int = 1,
) -> dict[str, Any]:
    """Execute a strict ``ReplayInput`` and write all replay artifacts.

    Errors are represented in ``report.json`` and leave a partial trace and a
    non-resumable checkpoint behind.  The report is returned in both success
    and failure cases; the CLI maps ``status=failed`` to a non-zero exit code.
    """

    if type(sample_ticks) is not int or sample_ticks <= 0:
        raise ValueError("sample_ticks must be a positive integer")
    validator = getattr(spec, "validate", None)
    if callable(validator):
        validator()
    mode = _mode(spec)
    replay_events = _events(spec)
    # Strict input validation is the source of truth.  These checks catch
    # hand-built objects while preserving its exact no-rounding contract.
    previous_tick = -1
    for index, event in enumerate(replay_events):
        tick = _event_tick(event)
        if tick < previous_tick:
            raise ValueError("replay events must be ordered by tick")
        previous_tick = tick
        _event_side(event)
        event_type = _event_type(event)
        if event_type == "card_play":
            if not _event_card(event):
                raise ValueError(f"event {index} card_play requires card")
            _cell_from_event(event, spec=spec)
    requested_end_tick = _end_tick(spec, replay_events)
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshots: list[dict[str, Any]] = []
    generated_events: list[dict[str, Any]] = []
    adapter: PlaybackAdapter | None = None
    error: Exception | None = None
    failed_index: int | None = None
    failed_tick: int | None = None
    active_event_index: int | None = None
    status = "horizon_reached"

    try:
        initial_path = _get(spec, "initial_state", None)
        engine: Any | None = None
        state: Any | None = None
        if initial_path:
            checkpoint_path = Path(initial_path)
            if not checkpoint_path.is_absolute():
                source_file = _get(spec, "source_file", None)
                if source_file:
                    checkpoint_path = Path(source_file).resolve().parent / checkpoint_path
            checkpoint_path = checkpoint_path.resolve()
            # Build an engine first so checkpoint ruleset/hash can be checked
            # against the current pinned runtime.
            ruleset = _load_ruleset(_ruleset_id(spec))
            engine = PlaybackEngine(ruleset=ruleset, mode=mode)
            state = _checkpoint_state(checkpoint_path, spec=spec, mode=mode, engine=engine)
            adapter = make_adapter(
                spec,
                state=state,
                engine=engine,
                include_existing_events=False,
            )
        else:
            adapter = make_adapter(spec)

        assert adapter is not None
        next_snapshot = adapter.tick

        def capture_until(target_tick: int) -> None:
            nonlocal next_snapshot
            while next_snapshot <= target_tick:
                if adapter is None:
                    return
                adapter.advance_to(next_snapshot)
                snapshots.append(_snapshot_record(adapter))
                generated_events.extend(_event_records(adapter))
                next_snapshot += sample_ticks
                if bool(getattr(adapter.state, "terminal", False)):
                    break

        # Match-start metadata is emitted by new_battle before the first
        # snapshot.  Capture it once for fresh runs; continuation traces start
        # at their restored state and retain only newly generated events.
        generated_events.extend(_event_records(adapter))
        if adapter.tick <= requested_end_tick:
            capture_until(adapter.tick)

        index = 0
        while index < len(replay_events):
            event_tick = _event_tick(replay_events[index])
            if event_tick > requested_end_tick:
                raise ValueError(f"event {index} is beyond requested end_tick")
            if bool(getattr(adapter.state, "terminal", False)):
                raise PlaybackActionRejected(
                    tick=adapter.tick,
                    player=0,
                    reason="match_ended_before_replay_event",
                )
            capture_until(event_tick)
            adapter.advance_to(event_tick)
            generated_events.extend(_event_records(adapter))
            group_start = index
            active_event_index = group_start
            while index < len(replay_events) and _event_tick(replay_events[index]) == event_tick:
                event = replay_events[index]
                try:
                    side = _event_side(event)
                    if _event_type(event) == "card_play":
                        cell = _cell_from_event(event, spec=spec)
                        card = _event_card(event)
                        assert card is not None
                        adapter.play_card(side=side, card=card, cell=cell)
                    else:
                        adapter.activate_ability(side=side, card=_event_card(event))
                except Exception as exc:
                    failed_index = index
                    failed_tick = event_tick
                    raise
                index += 1
            # If the next event is later, this advance commits all actions in
            # the group.  It also captures every periodic snapshot in between.
            if index < len(replay_events):
                next_tick = _event_tick(replay_events[index])
                if next_tick > event_tick:
                    capture_until(next_tick)
                    generated_events.extend(_event_records(adapter))
            elif event_tick < requested_end_tick:
                capture_until(requested_end_tick)
                generated_events.extend(_event_records(adapter))
            active_event_index = None

        if not bool(getattr(adapter.state, "terminal", False)) and adapter.tick < requested_end_tick:
            capture_until(requested_end_tick)
            generated_events.extend(_event_records(adapter))
        if bool(getattr(adapter.state, "terminal", False)):
            status = "terminal"
        else:
            status = "horizon_reached"
        # Ensure the final current state is represented, even when the sample
        # cadence does not land on the requested horizon.
        final_snapshot = _snapshot_record(adapter)
        if not snapshots or snapshots[-1].get("tick") != final_snapshot.get("tick"):
            snapshots.append(final_snapshot)
        generated_events.extend(_event_records(adapter))
    except Exception as exc:
        error = exc
        if failed_index is None:
            failed_index = active_event_index
        if failed_tick is None and adapter is not None:
            failed_tick = adapter.tick
        status = "failed"

    if adapter is None:
        # Engine construction/checkpoint failures happen before a state exists.
        report = {
            "schema_version": 1,
            "runtime_version": RUNTIME_VERSION,
            "upstream_commit": CRBOT_PIN,
            "physics_profile": PHYSICS_PROFILE,
            "battle_id": _get(spec, "battle_id", "replay"),
            "mode": mode,
            "status": "failed",
            "fidelity": FIDELITY_STATUS,
            "error": repr(error) if error else "runtime initialization failed",
            "failed_event_index": failed_index,
            "failed_tick": failed_tick,
            "resumable": False,
        }
        write_jsonl(output_dir / "snapshots.jsonl", snapshots)
        write_jsonl(output_dir / "events.jsonl", generated_events)
        write_json(output_dir / "report.json", report)
        # No authoritative checkpoint can be produced without a state.
        write_json(output_dir / "checkpoint.json", {**report, "checkpoint_version": 1, "state": None})
        from .viewer import write_viewer

        write_viewer(output_dir / "replay.html", snapshots=snapshots, events=generated_events, report=report)
        return report

    state_raw = _state_raw(adapter)
    state_hash = _state_hash(state_raw, adapter.state)
    resumable = error is None
    metadata = _metadata(
        mode=mode,
        state=adapter.state,
        engine=adapter.engine,
        state_hash=state_hash,
        resumable=resumable,
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "battle_id": _get(spec, "battle_id", "replay"),
        "status": status,
        "fidelity": FIDELITY_STATUS,
        "requested_end_tick": requested_end_tick,
        "end_tick": int(adapter.tick),
        "seed": _seed(spec),
        "event_count": len(replay_events),
        "simulated_event_count": len(generated_events),
        "failed_event_index": failed_index,
        "failed_tick": failed_tick,
        "error": None if error is None else repr(error),
        **metadata,
    }
    write_jsonl(output_dir / "snapshots.jsonl", snapshots)
    write_jsonl(output_dir / "events.jsonl", generated_events)
    write_json(output_dir / "report.json", report)
    checkpoint = _checkpoint_payload(
        adapter=adapter,
        state_raw=state_raw,
        state_hash=state_hash,
        mode=mode,
        resumable=resumable,
        report_status=status,
    )
    write_json(output_dir / "checkpoint.json", checkpoint)
    from .viewer import write_viewer

    write_viewer(output_dir / "replay.html", snapshots=snapshots, events=generated_events, report=report)
    return report


__all__ = [
    "CRBOT_PIN",
    "CheckpointMismatchError",
    "DEFAULT_END_TICK",
    "FIDELITY_STATUS",
    "PHYSICS_PROFILE",
    "RUNTIME_VERSION",
    "ReplayRuntimeError",
    "make_adapter",
    "run_replay",
    "write_json",
    "write_jsonl",
]
