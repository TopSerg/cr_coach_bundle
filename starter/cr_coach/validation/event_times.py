"""Event-based timing and damage comparison for replay fidelity probes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


DEFAULT_TICKS_PER_SECOND = 20


def _flat_event(event: Any) -> dict[str, Any]:
    """Flatten a cr-bot ``SimEvent`` JSON object for tolerant diagnostics."""

    if isinstance(event, Mapping):
        result = dict(event)
        data = result.get("data")
        if isinstance(data, Mapping):
            for key, value in data.items():
                result.setdefault(key, value)
        values = result.get("values")
        if isinstance(values, Mapping):
            for key, value in values.items():
                result.setdefault(key, value)
        return result
    data = getattr(event, "data", ())
    if isinstance(data, Mapping):
        result = dict(data)
    else:
        try:
            result = dict(data)
        except (TypeError, ValueError):
            result = {}
    for key in ("tick", "kind", "sequence"):
        if hasattr(event, key):
            result[key] = getattr(event, key)
    return result


def _event_tick(event: Mapping[str, Any], ticks_per_second: int) -> int | None:
    value = event.get("tick")
    if type(value) is int:
        return value
    # A few video-derived traces use seconds in place of simulator ticks.
    for key in ("time_s", "seconds", "time"):
        value = event.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(round(float(value) * ticks_per_second))
    return None


def _event_seconds(event: Mapping[str, Any], ticks_per_second: int) -> float | None:
    tick = event.get("tick")
    if type(tick) is int:
        return tick / ticks_per_second
    for key in ("time_s", "seconds", "time"):
        value = event.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _card_id(event: Mapping[str, Any]) -> str | None:
    for key in ("card_id", "source_card_id", "card", "unit_card_id"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return None


def _owner(event: Mapping[str, Any]) -> int | None:
    value = event.get("owner", event.get("player"))
    if type(value) is int:
        return value
    if value == "team" or value == "A":
        return 0
    if value == "opponent" or value == "B":
        return 1
    return None


def _target_card(event: Mapping[str, Any], entities: Mapping[int, tuple[str | None, int | None]]) -> str | None:
    for key in ("target_card_id", "target_card", "target_id"):
        value = event.get(key)
        if isinstance(value, str) and key != "target_id":
            return value
    uid = event.get("target_uid")
    if type(uid) is int and uid in entities:
        return entities[uid][0]
    return None


def _is_kind(event: Mapping[str, Any], *kinds: str) -> bool:
    return event.get("kind") in kinds or event.get("event_type") in kinds


def hog_cannon_metrics(
    events: Iterable[Mapping[str, Any]],
    *,
    ticks_per_second: int = DEFAULT_TICKS_PER_SECOND,
) -> dict[str, Any]:
    """Extract Hog↔Cannon milestones from a flat or nested event stream.

    ``damage_applied`` is the source of truth for hits. Attack counters and
    current target state are sampled after death resolution and can therefore
    lose a lethal third hit; event damage remains observable in that case.
    Returned times are relative to the first team Hog card play.
    """

    if type(ticks_per_second) is not int or ticks_per_second <= 0:
        raise ValueError("ticks_per_second must be positive")
    flat = [_flat_event(event) for event in events]
    indexed = list(enumerate(flat))
    indexed.sort(
        key=lambda pair: (
            _event_tick(pair[1], ticks_per_second)
            if _event_tick(pair[1], ticks_per_second) is not None
            else 10**18,
            pair[0],
        )
    )

    entities: dict[int, tuple[str | None, int | None]] = {}
    hog_play_tick: int | None = None
    hog_play_seconds: float | None = None
    hog_hits: list[float] = []
    cannon_fires: list[float] = []
    cannon_death: float | None = None
    hog_death: float | None = None
    hog_acquire_cannon: float | None = None
    target_by_uid: dict[int, int | None] = {}

    # Prefer simulator ticks for relative alignment. If a source has only
    # seconds, the same code still works after conversion to a synthetic tick.
    for _, event in indexed:
        tick = _event_tick(event, ticks_per_second)
        seconds = _event_seconds(event, ticks_per_second)
        kind = str(event.get("kind", event.get("event_type", "")))
        card = _card_id(event)
        owner = _owner(event)
        uid = event.get("uid")
        if type(uid) is int and kind in {"entity_spawned", "entity_created", "card_spawned", "spawn"}:
            entities[uid] = (card, owner)
        elif type(uid) is int and card is not None and uid not in entities:
            entities[uid] = (card, owner)

        if kind in {"card_played", "card_play", "own_card_play_observed"} and card == "hog-rider" and owner in (None, 0):
            if hog_play_tick is None and tick is not None:
                hog_play_tick = tick
                hog_play_seconds = seconds
            elif hog_play_tick is None and seconds is not None:
                hog_play_seconds = seconds

        if kind == "target_changed":
            source_uid = event.get("uid")
            if type(source_uid) is int:
                target = event.get("target_uid")
                target_by_uid[source_uid] = target if type(target) is int else None
                source_card = entities.get(source_uid, (card, owner))[0]
                target_card = _target_card(event, entities)
                if source_card == "hog-rider" and target_card == "cannon":
                    if seconds is not None:
                        hog_acquire_cannon = hog_acquire_cannon if hog_acquire_cannon is not None else seconds

        if kind == "damage_applied":
            source_card = event.get("source_card_id") or card
            target_card = _target_card(event, entities)
            if source_card == "hog-rider" and target_card == "cannon":
                if seconds is not None:
                    hog_hits.append(seconds)
            elif source_card == "cannon":
                if seconds is not None:
                    cannon_fires.append(seconds)

        if kind in {"entity_died", "unit_disappearance_observed"}:
            death_card = card
            if death_card is None and type(uid) is int:
                death_card = entities.get(uid, (None, None))[0]
            if death_card == "cannon" and cannon_death is None and seconds is not None:
                cannon_death = seconds
            if death_card == "hog-rider" and owner in (None, 0) and hog_death is None and seconds is not None:
                hog_death = seconds

    if hog_play_tick is not None:
        origin = hog_play_tick / ticks_per_second
    elif hog_play_seconds is not None:
        origin = hog_play_seconds
    else:
        origin = 0.0

    def relative(value: float | None) -> float | None:
        return None if value is None else round(value - origin, 3)

    return {
        "hog_hits_cannon": [relative(value) for value in hog_hits],
        "cannon_death": relative(cannon_death),
        "hog_death": relative(hog_death),
        "cannon_fires": [relative(value) for value in cannon_fires],
        "hog_acquire_cannon": relative(hog_acquire_cannon),
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def compare_event_times(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    tolerance_s: float = 0.10,
) -> dict[str, Any]:
    """Compare scalar milestones and complete damage-hit sequences.

    Missing and extra hits are explicit failures, even when all shared hit
    times are within tolerance. This makes a lost lethal ``damage_applied``
    event visible to the fidelity report.
    """

    if isinstance(tolerance_s, bool) or not isinstance(tolerance_s, (int, float)) or not math_is_finite(float(tolerance_s)) or tolerance_s < 0:
        raise ValueError("tolerance_s must be a finite number >= 0")
    tolerance = float(tolerance_s)
    comparisons: list[dict[str, Any]] = []

    def add(name: str, expected_value: Any, actual_value: Any) -> None:
        expected_number = _number(expected_value)
        actual_number = _number(actual_value)
        if expected_number is None and actual_number is None and expected_value is None and actual_value is None:
            comparisons.append({"metric": name, "expected": None, "actual": None, "error_s": 0.0, "within_tolerance": True})
            return
        if expected_number is None or actual_number is None:
            comparisons.append({"metric": name, "expected": expected_value, "actual": actual_value, "error_s": None, "within_tolerance": False})
            return
        error = round(actual_number - expected_number, 3)
        comparisons.append({"metric": name, "expected": expected_number, "actual": actual_number, "error_s": error, "within_tolerance": abs(error) <= tolerance})

    for name in ("cannon_death", "hog_death"):
        add(name, expected.get(name), actual.get(name))

    expected_hits = expected.get("hog_hits_cannon", [])
    actual_hits = actual.get("hog_hits_cannon", [])
    if not isinstance(expected_hits, Sequence) or isinstance(expected_hits, (str, bytes)):
        raise ValueError("expected hog_hits_cannon must be a sequence")
    if not isinstance(actual_hits, Sequence) or isinstance(actual_hits, (str, bytes)):
        raise ValueError("actual hog_hits_cannon must be a sequence")
    max_hits = max(len(expected_hits), len(actual_hits))
    for index in range(max_hits):
        expected_value = expected_hits[index] if index < len(expected_hits) else None
        actual_value = actual_hits[index] if index < len(actual_hits) else None
        if index >= len(expected_hits):
            comparisons.append({"metric": f"hog_hit_{index + 1}", "expected": None, "actual": actual_value, "error_s": None, "within_tolerance": False, "detail": "unexpected extra hit"})
        elif index >= len(actual_hits):
            comparisons.append({"metric": f"hog_hit_{index + 1}", "expected": expected_value, "actual": None, "error_s": None, "within_tolerance": False, "detail": "missing hit"})
        else:
            add(f"hog_hit_{index + 1}", expected_value, actual_value)

    first = next((item for item in comparisons if not item["within_tolerance"]), None)
    return {
        "passed": first is None,
        "tolerance_s": tolerance,
        "comparisons": comparisons,
        "first_divergence": first,
    }


def math_is_finite(value: float) -> bool:
    # Kept local to avoid importing the heavyweight numerical stack in this
    # lightweight validation module.
    return value == value and value not in (float("inf"), float("-inf"))


compare_damage_events = compare_event_times

