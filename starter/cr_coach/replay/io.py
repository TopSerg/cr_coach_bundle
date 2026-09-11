"""Strict JSON/CSV replay loading and canonical serialization.

The public input format is deliberately small and human editable.  A replay
may use seconds plus 18x32 cell coordinates (the format used by the examples)
or provide canonical integer ticks and milli-tile centres.  Parsing performs
all unit conversion once and constructs :class:`ReplayBattle` objects whose
events are safe to feed to any backend adapter.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TextIO

from cr_coach.replay.schema import ReplayBattle, ReplayEvent


DEFAULT_TICKS_PER_SECOND = 20
DEFAULT_DURATION_SECONDS = 300
DEFAULT_END_TICK = DEFAULT_TICKS_PER_SECOND * DEFAULT_DURATION_SECONDS
DEFAULT_RULESET = "2026-08-04-roster"
GRID_COLUMNS = 18
GRID_ROWS = 32
MTILE_PER_CELL = 1_000


class ReplayParseError(ValueError):
    """Raised when a JSON/CSV source is malformed or ambiguous."""


ReplayIOError = ReplayParseError

_MISSING = object()

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "battle_id",
        "ticks_per_second",
        "mode",
        "ruleset_id",
        "level",
        "seed",
        "coordinate_system",
        "duration_s",
        "end_tick",
        "initial_state",
        "physics_profile",
        "patch_id",
        "team_deck",
        "opponent_deck",
        "team_initial_queue",
        "opponent_initial_queue",
        "events",
        "notes",
    }
)

_EVENT_KEYS = frozenset(
    {
        "tick",
        "time",
        "time_s",
        "seconds",
        "side",
        "event_type",
        "card",
        "ability_card",
        "x",
        "y",
        "x_mtile",
        "y_mtile",
    }
)

_CSV_EVENT_KEYS = frozenset(
    {
        "tick",
        "time",
        "time_s",
        "seconds",
        "side",
        "event_type",
        "card",
        "ability_card",
        "x",
        "y",
        "x_mtile",
        "y_mtile",
    }
)

_CSV_METADATA_KEYS = frozenset(
    {
        "battle_id",
        "mode",
        "ruleset_id",
        "level",
        "seed",
        "ticks_per_second",
        "coordinate_system",
        "duration_s",
        "end_tick",
        "initial_state",
        "physics_profile",
        "patch_id",
        "team_deck",
        "opponent_deck",
        "team_initial_queue",
        "opponent_initial_queue",
        "notes",
    }
)


def _integer(value: Any, field_name: str) -> int:
    if type(value) is not int:
        raise ReplayParseError(f"{field_name} must be an integer")
    return value


def _non_empty_string(value: Any, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ReplayParseError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field_name)


def _csv_integer(value: str, field_name: str, *, row: int) -> int:
    raw = value.strip()
    if not raw or any(char not in "-+0123456789" for char in raw) or raw in {"+", "-"}:
        raise ReplayParseError(f"CSV row {row}: {field_name} must be an integer")
    try:
        return int(raw, 10)
    except ValueError as exc:  # pragma: no cover - guarded above
        raise ReplayParseError(f"CSV row {row}: {field_name} must be an integer") from exc


def _csv_number(value: str, field_name: str, *, row: int) -> int | float:
    raw = value.strip()
    if not raw:
        raise ReplayParseError(f"CSV row {row}: {field_name} is required")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ReplayParseError(f"CSV row {row}: {field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise ReplayParseError(f"CSV row {row}: {field_name} must be finite")
    if parsed == parsed.to_integral_value():
        return int(parsed)
    return float(parsed)


def seconds_to_tick(seconds: int | float | Decimal | str, ticks_per_second: int = DEFAULT_TICKS_PER_SECOND) -> int:
    """Convert an exact, tick-aligned seconds value to an integer tick.

    Rounding a hand-labelled event silently moves it to a different physics
    tick, so fractional values such as ``0.025`` are rejected at 20 Hz.
    Decimal conversion through ``str`` avoids binary floating point artefacts
    for ordinary values such as ``2.45``.
    """

    _integer(ticks_per_second, "ticks_per_second")
    if ticks_per_second <= 0:
        raise ReplayParseError("ticks_per_second must be positive")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float, Decimal, str)):
        raise ReplayParseError("time must be a finite number of seconds")
    try:
        value = Decimal(str(seconds).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ReplayParseError("time must be a finite number of seconds") from exc
    if not value.is_finite() or value < 0:
        raise ReplayParseError("time must be finite and >= 0")
    scaled = value * ticks_per_second
    if scaled != scaled.to_integral_value():
        raise ReplayParseError(
            f"time {seconds!r} does not align to a {ticks_per_second} Hz physics tick"
        )
    return int(scaled)


def tick_to_seconds(tick: int, ticks_per_second: int = DEFAULT_TICKS_PER_SECOND) -> float:
    _integer(tick, "tick")
    if tick < 0:
        raise ReplayParseError("tick must be >= 0")
    _integer(ticks_per_second, "ticks_per_second")
    if ticks_per_second <= 0:
        raise ReplayParseError("ticks_per_second must be positive")
    return tick / ticks_per_second


def _read_text(source: str | Path | TextIO) -> tuple[str, Path | None]:
    if hasattr(source, "read"):
        text = source.read()
        if not isinstance(text, str):
            raise ReplayParseError("replay source must provide text")
        return text, None
    if isinstance(source, Path):
        path = source
    elif isinstance(source, str):
        stripped = source.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return source, None
        path = Path(source)
    else:
        raise ReplayParseError("replay source must be a path or text stream")
    try:
        return path.read_text(encoding="utf-8"), path
    except OSError as exc:
        raise ReplayParseError(f"cannot read replay source {path}: {exc}") from exc


def _check_keys(raw: Mapping[str, Any], allowed: frozenset[str], context: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ReplayParseError(f"{context} has unknown field(s): {', '.join(unknown)}")


def _sequence(raw: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ReplayParseError(f"{field_name} must be an array of card IDs")
    result: list[str] = []
    for index, card in enumerate(raw):
        result.append(_non_empty_string(card, f"{field_name}[{index}]") )
    if len(result) != 8:
        raise ReplayParseError(f"{field_name} must contain exactly 8 cards")
    if len(set(result)) != len(result):
        raise ReplayParseError(f"{field_name} cards must be unique")
    return tuple(result)


def _sequence_csv(value: str, field_name: str, *, row: int) -> tuple[str, ...]:
    raw = value.strip()
    if not raw:
        raise ReplayParseError(f"CSV row {row}: {field_name} is empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [part.strip() for part in raw.split(",")]
    try:
        return _sequence(parsed, field_name)
    except ReplayParseError as exc:
        raise ReplayParseError(f"CSV row {row}: {exc}") from exc


def _time_tick(raw: Mapping[str, Any], *, ticks_per_second: int, context: str) -> int:
    tick = raw.get("tick", _MISSING)
    time_values = [raw[name] for name in ("time", "time_s", "seconds") if name in raw and raw[name] is not None and raw[name] != ""]
    if tick is _MISSING and not time_values:
        raise ReplayParseError(f"{context} requires tick or time")
    if len(time_values) > 1:
        first = seconds_to_tick(time_values[0], ticks_per_second)
        if any(seconds_to_tick(value, ticks_per_second) != first for value in time_values[1:]):
            raise ReplayParseError(f"{context} has conflicting time fields")
        time_tick = first
    else:
        time_tick = None if not time_values else seconds_to_tick(time_values[0], ticks_per_second)
    if tick is not _MISSING and tick is not None and tick != "":
        if isinstance(tick, str):
            # JSON callers must use integer JSON values; CSV callers convert
            # the field before reaching this helper.
            raise ReplayParseError(f"{context}.tick must be an integer")
        exact_tick = _integer(tick, f"{context}.tick")
        if exact_tick < 0:
            raise ReplayParseError(f"{context}.tick must be >= 0")
        if time_tick is not None and exact_tick != time_tick:
            raise ReplayParseError(f"{context} has conflicting tick and time")
        return exact_tick
    assert time_tick is not None
    return time_tick


def _coordinate_pair(raw: Mapping[str, Any], *, side: str, coordinate_system: str, context: str) -> tuple[int, int]:
    has_cells = "x" in raw or "y" in raw
    has_mtiles = "x_mtile" in raw or "y_mtile" in raw
    if has_cells and has_mtiles:
        raise ReplayParseError(f"{context} cannot mix x/y with x_mtile/y_mtile")
    if not has_cells and not has_mtiles:
        raise ReplayParseError(f"{context} requires x/y coordinates")
    if has_cells:
        if "x" not in raw or "y" not in raw:
            raise ReplayParseError(f"{context} requires both x and y")
        x = _integer(raw["x"], f"{context}.x")
        y = _integer(raw["y"], f"{context}.y")
        if coordinate_system == "world_mtile":
            if not (0 <= x < GRID_COLUMNS * MTILE_PER_CELL and 0 <= y < GRID_ROWS * MTILE_PER_CELL):
                raise ReplayParseError(f"{context} milli-tile coordinate is outside 18x32 arena")
            if x % MTILE_PER_CELL != MTILE_PER_CELL // 2 or y % MTILE_PER_CELL != MTILE_PER_CELL // 2:
                raise ReplayParseError(f"{context} milli-tile coordinates must be cell centres")
            return x, y
        if not (0 <= x < GRID_COLUMNS and 0 <= y < GRID_ROWS):
            raise ReplayParseError(f"{context} cell is outside 18x32 arena")
        if coordinate_system == "player_cells" and side == "opponent":
            x = GRID_COLUMNS - 1 - x
            y = GRID_ROWS - 1 - y
        return x * MTILE_PER_CELL + MTILE_PER_CELL // 2, y * MTILE_PER_CELL + MTILE_PER_CELL // 2

    if "x_mtile" not in raw or "y_mtile" not in raw:
        raise ReplayParseError(f"{context} requires both x_mtile and y_mtile")
    x = _integer(raw["x_mtile"], f"{context}.x_mtile")
    y = _integer(raw["y_mtile"], f"{context}.y_mtile")
    if coordinate_system == "player_cells" and side == "opponent":
        x = GRID_COLUMNS * MTILE_PER_CELL - x
        y = GRID_ROWS * MTILE_PER_CELL - y
    if not (0 <= x < GRID_COLUMNS * MTILE_PER_CELL and 0 <= y < GRID_ROWS * MTILE_PER_CELL):
        raise ReplayParseError(f"{context} milli-tile coordinate is outside 18x32 arena")
    if x % MTILE_PER_CELL != MTILE_PER_CELL // 2 or y % MTILE_PER_CELL != MTILE_PER_CELL // 2:
        raise ReplayParseError(f"{context} milli-tile coordinates must be cell centres")
    return x, y


def _parse_event(raw: Mapping[str, Any], *, ticks_per_second: int, coordinate_system: str, context: str) -> ReplayEvent:
    _check_keys(raw, _EVENT_KEYS, context)
    if not isinstance(raw, Mapping):
        raise ReplayParseError(f"{context} must be an object")
    side = raw.get("side", _MISSING)
    if type(side) is not str or side not in {"team", "opponent"}:
        raise ReplayParseError(f"{context}.side must be 'team' or 'opponent'")
    tick = _time_tick(raw, ticks_per_second=ticks_per_second, context=context)
    event_type = raw.get("event_type")
    if event_type is None or event_type == "":
        if raw.get("card") not in (None, ""):
            event_type = "card_play"
        elif raw.get("ability_card") not in (None, ""):
            event_type = "ability_activation"
        else:
            raise ReplayParseError(f"{context} requires event_type or card")
    if type(event_type) is not str or event_type not in {"card_play", "ability_activation"}:
        raise ReplayParseError(f"{context}.event_type is unsupported")

    if event_type == "card_play":
        card = raw.get("card")
        if type(card) is not str or not card.strip():
            raise ReplayParseError(f"{context}.card is required for card_play")
        if raw.get("ability_card") not in (None, ""):
            raise ReplayParseError(f"{context} card_play cannot carry ability_card")
        x_mtile, y_mtile = _coordinate_pair(
            raw,
            side=side,
            coordinate_system=coordinate_system,
            context=context,
        )
        return ReplayEvent(
            tick=tick,
            side=side,
            event_type="card_play",
            card=card.strip(),
            x_mtile=x_mtile,
            y_mtile=y_mtile,
        )

    if raw.get("card") not in (None, ""):
        raise ReplayParseError(f"{context} ability_activation cannot carry card")
    if any(name in raw and raw[name] not in (None, "") for name in ("x", "y", "x_mtile", "y_mtile")):
        raise ReplayParseError(f"{context} ability_activation cannot carry coordinates")
    ability_card = raw.get("ability_card")
    if ability_card is not None and type(ability_card) is not str:
        raise ReplayParseError(f"{context}.ability_card must be a string or null")
    if isinstance(ability_card, str):
        ability_card = ability_card.strip() or None
    return ReplayEvent(
        tick=tick,
        side=side,
        event_type="ability_activation",
        ability_card=ability_card,
    )


def _metadata_value(raw: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = raw.get(key, default)
    return default if value is None else value


def replay_from_mapping(raw: Mapping[str, Any], *, source_path: str | Path | None = None) -> ReplayBattle:
    """Parse one strict JSON object into a :class:`ReplayBattle`."""

    if not isinstance(raw, Mapping):
        raise ReplayParseError("replay JSON root must be an object")
    _check_keys(raw, _TOP_LEVEL_KEYS, "replay")

    schema_version = _metadata_value(raw, "schema_version", 1)
    _integer(schema_version, "schema_version")
    if schema_version != 1:
        raise ReplayParseError("unsupported replay schema version")
    source = Path(source_path).resolve() if source_path is not None else None
    battle_id = raw.get("battle_id")
    if battle_id is None:
        battle_id = source.stem if source is not None else "replay"
    battle_id = _non_empty_string(battle_id, "battle_id")
    ticks_per_second = _metadata_value(raw, "ticks_per_second", DEFAULT_TICKS_PER_SECOND)
    _integer(ticks_per_second, "ticks_per_second")
    if ticks_per_second <= 0:
        raise ReplayParseError("ticks_per_second must be positive")

    mode = _metadata_value(raw, "mode", "placements")
    if type(mode) is not str or mode not in {"placements", "match"}:
        raise ReplayParseError("mode must be 'placements' or 'match'")
    coordinate_system = _metadata_value(raw, "coordinate_system", "world_cells")
    # ``mtile`` was used in a few early hand-authored files; keep it as an
    # explicit alias while storing only the canonical name in ReplayBattle.
    if coordinate_system == "mtile":
        coordinate_system = "world_mtile"
    if type(coordinate_system) is not str or coordinate_system not in {"world_cells", "player_cells", "world_mtile"}:
        raise ReplayParseError("unsupported coordinate_system")
    level = _metadata_value(raw, "level", 11)
    _integer(level, "level")
    if level != 11:
        raise ReplayParseError("only level 11 replays are supported")
    seed = _metadata_value(raw, "seed", 0)
    _integer(seed, "seed")
    if seed < 0:
        raise ReplayParseError("seed must be >= 0")

    events_raw = _metadata_value(raw, "events", [])
    if not isinstance(events_raw, list):
        raise ReplayParseError("events must be an array")
    events: list[ReplayEvent] = []
    for index, event_raw in enumerate(events_raw):
        if not isinstance(event_raw, Mapping):
            raise ReplayParseError(f"events[{index}] must be an object")
        events.append(
            _parse_event(
                event_raw,
                ticks_per_second=ticks_per_second,
                coordinate_system=coordinate_system,
                context=f"events[{index}]",
            )
        )
    # Sorting makes CSV and JSON input deterministic while preserving source
    # order for simultaneous actions (Python sort is stable).
    events.sort(key=lambda event: event.tick)
    seen_actions: set[tuple[int, str]] = set()
    for event in events:
        key = (event.tick, event.side)
        if key in seen_actions:
            raise ReplayParseError(
                f"multiple actions for side {event.side!r} at tick {event.tick}"
            )
        seen_actions.add(key)

    team_deck = _sequence(raw["team_deck"], "team_deck") if "team_deck" in raw and raw["team_deck"] is not None else ()
    opponent_deck = _sequence(raw["opponent_deck"], "opponent_deck") if "opponent_deck" in raw and raw["opponent_deck"] is not None else ()
    team_queue = _sequence(raw["team_initial_queue"], "team_initial_queue") if "team_initial_queue" in raw and raw["team_initial_queue"] is not None else None
    opponent_queue = _sequence(raw["opponent_initial_queue"], "opponent_initial_queue") if "opponent_initial_queue" in raw and raw["opponent_initial_queue"] is not None else None

    end_tick: int | None
    if "end_tick" in raw and raw["end_tick"] is not None:
        end_tick = _integer(raw["end_tick"], "end_tick")
    elif "duration_s" in raw and raw["duration_s"] is not None:
        end_tick = seconds_to_tick(raw["duration_s"], ticks_per_second)
    else:
        end_tick = DEFAULT_END_TICK if ticks_per_second == DEFAULT_TICKS_PER_SECOND else ticks_per_second * DEFAULT_DURATION_SECONDS
    if end_tick < 0:
        raise ReplayParseError("end_tick must be >= 0")
    if events:
        last_tick = events[-1].tick
        if end_tick < last_tick:
            raise ReplayParseError("duration/end_tick cannot end before the last event")
        if end_tick == last_tick:
            end_tick += 1

    initial_state = raw.get("initial_state")
    if initial_state is not None:
        initial_state = _non_empty_string(initial_state, "initial_state")
        if source is not None:
            initial_state = str((source.parent / initial_state).resolve()) if not Path(initial_state).is_absolute() else str(Path(initial_state).resolve())

    battle = ReplayBattle(
        battle_id=battle_id,
        ticks_per_second=ticks_per_second,
        patch_id=_optional_string(raw.get("patch_id"), "patch_id"),
        team_deck=team_deck,
        opponent_deck=opponent_deck,
        team_initial_queue=team_queue,
        opponent_initial_queue=opponent_queue,
        events=events,
        schema_version=schema_version,
        mode=mode,
        ruleset_id=_non_empty_string(_metadata_value(raw, "ruleset_id", DEFAULT_RULESET), "ruleset_id"),
        level=level,
        seed=seed,
        coordinate_system=coordinate_system,
        end_tick=end_tick,
        initial_state=initial_state,
        physics_profile=_optional_string(raw.get("physics_profile"), "physics_profile"),
        notes=_optional_string(raw.get("notes"), "notes"),
    )
    battle.validate()
    return battle


def load_replay_json(source: str | Path | TextIO) -> ReplayBattle:
    text, source_path = _read_text(source)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReplayParseError(f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
    return replay_from_mapping(raw, source_path=source_path)


parse_replay_json = load_replay_json


def _csv_metadata(rows: Sequence[Mapping[str, str]], field: str, *, row_offset: int = 2) -> str | None:
    values = [row.get(field, "").strip() for row in rows if row.get(field, "").strip()]
    if not values:
        return None
    first = values[0]
    if any(value != first for value in values[1:]):
        raise ReplayParseError(f"CSV metadata field {field!r} changes between rows")
    return first


def load_replay_csv(
    source: str | Path | TextIO,
    *,
    battle_id: str | None = None,
    ticks_per_second: int = DEFAULT_TICKS_PER_SECOND,
    mode: str = "placements",
    coordinate_system: str = "world_cells",
    ruleset_id: str = DEFAULT_RULESET,
    level: int = 11,
    seed: int = 0,
    end_tick: int | None = None,
    duration_s: int | float | Decimal | str | None = None,
    team_deck: Sequence[str] | None = None,
    opponent_deck: Sequence[str] | None = None,
    team_initial_queue: Sequence[str] | None = None,
    opponent_initial_queue: Sequence[str] | None = None,
    initial_state: str | Path | None = None,
    physics_profile: str | None = None,
    patch_id: str | None = None,
    notes: str | None = None,
) -> ReplayBattle:
    """Load a strict event CSV.

    The minimal header is ``time,side,card,x,y``.  Canonical ``tick`` and
    milli-tile columns are also accepted.  Metadata columns, when present,
    must have one identical value on every data row; function arguments are
    used as defaults and are overridden by those explicit columns.
    """

    text, source_path = _read_text(source)
    try:
        reader = csv.DictReader(text.splitlines())
        headers = reader.fieldnames
        if not headers:
            raise ReplayParseError("CSV must contain a header row")
        if any(header is None or not header.strip() for header in headers):
            raise ReplayParseError("CSV header contains an empty column")
        normalized_headers = [header.strip() for header in headers]
        if len(set(normalized_headers)) != len(normalized_headers):
            raise ReplayParseError("CSV header contains duplicate columns")
        unknown = sorted(set(normalized_headers) - _CSV_EVENT_KEYS - _CSV_METADATA_KEYS)
        if unknown:
            raise ReplayParseError(f"CSV has unknown column(s): {', '.join(unknown)}")
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ReplayParseError(f"CSV row {row_number} has more fields than the header")
            values = {str(key).strip(): (value or "") for key, value in row.items()}
            if not any(value.strip() for value in values.values()):
                continue
            rows.append(values)
    except csv.Error as exc:
        raise ReplayParseError(f"invalid CSV: {exc}") from exc

    def metadata(name: str, current: Any) -> Any:
        value = _csv_metadata(rows, name)
        return current if value is None else value

    battle_id_value = metadata("battle_id", battle_id)
    if battle_id_value is None:
        battle_id_value = source_path.stem if source_path is not None else "replay"
    battle_id_value = _non_empty_string(battle_id_value, "battle_id")

    tps_raw = metadata("ticks_per_second", ticks_per_second)
    if type(tps_raw) is str:
        tps_value = _csv_integer(tps_raw, "ticks_per_second", row=2)
    else:
        tps_value = tps_raw
    _integer(tps_value, "ticks_per_second")
    mode_value = metadata("mode", mode)
    coordinate_value = metadata("coordinate_system", coordinate_system)
    if coordinate_value == "mtile":
        coordinate_value = "world_mtile"
    ruleset_value = metadata("ruleset_id", ruleset_id)
    level_raw = metadata("level", level)
    level_value = _csv_integer(level_raw, "level", row=2) if isinstance(level_raw, str) else level_raw
    seed_raw = metadata("seed", seed)
    seed_value = _csv_integer(seed_raw, "seed", row=2) if isinstance(seed_raw, str) else seed_raw

    def sequence_metadata(name: str, fallback: Sequence[str] | None) -> tuple[str, ...] | None:
        value = _csv_metadata(rows, name)
        if value is None:
            return None if fallback is None else tuple(fallback)
        return _sequence_csv(value, name, row=2)

    team_deck_value = sequence_metadata("team_deck", team_deck)
    opponent_deck_value = sequence_metadata("opponent_deck", opponent_deck)
    team_queue_value = sequence_metadata("team_initial_queue", team_initial_queue)
    opponent_queue_value = sequence_metadata("opponent_initial_queue", opponent_initial_queue)

    events: list[ReplayEvent] = []
    for index, row in enumerate(rows, start=2):
        event_raw: dict[str, Any] = {}
        for key in _CSV_EVENT_KEYS & row.keys():
            value = row.get(key, "").strip()
            if not value:
                continue
            if key == "tick":
                event_raw[key] = _csv_integer(value, "tick", row=index)
            elif key in {"x", "y", "x_mtile", "y_mtile"}:
                event_raw[key] = _csv_integer(value, key, row=index)
            elif key in {"time", "time_s", "seconds"}:
                event_raw[key] = _csv_number(value, key, row=index)
            else:
                event_raw[key] = value
        try:
            events.append(
                _parse_event(
                    event_raw,
                    ticks_per_second=tps_value,
                    coordinate_system=coordinate_value,
                    context=f"CSV row {index}",
                )
            )
        except ReplayParseError:
            raise
        except (TypeError, ValueError) as exc:
            raise ReplayParseError(f"CSV row {index}: {exc}") from exc
    events.sort(key=lambda event: event.tick)

    duration_value = metadata("duration_s", duration_s)
    end_value = metadata("end_tick", end_tick)
    if end_value is not None:
        end_tick_value = _csv_integer(end_value, "end_tick", row=2) if isinstance(end_value, str) else end_value
    elif duration_value is not None:
        end_tick_value = seconds_to_tick(duration_value, tps_value)
    else:
        end_tick_value = tps_value * DEFAULT_DURATION_SECONDS

    initial_value = metadata("initial_state", initial_state)
    if initial_value is not None:
        initial_value = _non_empty_string(str(initial_value), "initial_state")
        if source_path is not None and not Path(initial_value).is_absolute():
            initial_value = str((source_path.resolve().parent / initial_value).resolve())
    physics_value = metadata("physics_profile", physics_profile)
    patch_value = metadata("patch_id", patch_id)
    notes_value = metadata("notes", notes)

    raw: dict[str, Any] = {
        "battle_id": battle_id_value,
        "ticks_per_second": tps_value,
        "mode": mode_value,
        "ruleset_id": ruleset_value,
        "level": level_value,
        "seed": seed_value,
        "coordinate_system": coordinate_value,
        "end_tick": end_tick_value,
        "events": [event.to_mapping() for event in events],
    }
    if team_deck_value is not None:
        raw["team_deck"] = list(team_deck_value)
    if opponent_deck_value is not None:
        raw["opponent_deck"] = list(opponent_deck_value)
    if team_queue_value is not None:
        raw["team_initial_queue"] = list(team_queue_value)
    if opponent_queue_value is not None:
        raw["opponent_initial_queue"] = list(opponent_queue_value)
    if initial_value is not None:
        raw["initial_state"] = initial_value
    if physics_value is not None:
        raw["physics_profile"] = physics_value
    if patch_value is not None:
        raw["patch_id"] = patch_value
    if notes_value is not None:
        raw["notes"] = notes_value
    return replay_from_mapping(raw, source_path=source_path)


parse_replay_csv = load_replay_csv


def load_replay(source: str | Path | TextIO, **csv_options: Any) -> ReplayBattle:
    """Dispatch a replay path by extension, or parse JSON text by default."""

    if hasattr(source, "read"):
        name = str(getattr(source, "name", ""))
        return load_replay_csv(source, **csv_options) if name.lower().endswith(".csv") else load_replay_json(source)
    if isinstance(source, Path):
        suffix = source.suffix.lower()
    elif isinstance(source, str) and not source.lstrip().startswith(("{", "[")):
        suffix = Path(source).suffix.lower()
    else:
        suffix = ".json"
    if suffix == ".csv":
        return load_replay_csv(source, **csv_options)
    if suffix in {".json", ""}:
        return load_replay_json(source)
    raise ReplayParseError(f"unsupported replay format {suffix!r}; use .json or .csv")


parse_replay = load_replay


def replay_to_mapping(battle: ReplayBattle) -> dict[str, Any]:
    return battle.to_mapping()


def dump_replay_json(battle: ReplayBattle, *, indent: int | None = 2) -> str:
    return json.dumps(battle.to_mapping(), ensure_ascii=False, indent=indent, sort_keys=True)


def write_replay_json(battle: ReplayBattle, destination: str | Path, *, indent: int | None = 2) -> Path:
    path = Path(destination)
    path.write_text(dump_replay_json(battle, indent=indent) + "\n", encoding="utf-8")
    return path


def dump_replay_csv(battle: ReplayBattle) -> str:
    battle.validate()
    from io import StringIO

    stream = StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=("tick", "side", "event_type", "card", "x_mtile", "y_mtile", "ability_card"),
        lineterminator="\n",
    )
    writer.writeheader()
    for event in battle.events:
        writer.writerow(event.to_mapping())
    return stream.getvalue()


def write_replay_csv(battle: ReplayBattle, destination: str | Path) -> Path:
    path = Path(destination)
    path.write_text(dump_replay_csv(battle), encoding="utf-8")
    return path
