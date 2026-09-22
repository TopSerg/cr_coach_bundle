"""Unified P-1 comparator for synthetic and physical fidelity references."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
import json


@dataclass(frozen=True, slots=True)
class FirstDivergence:
    tick: int
    subsystem: str
    expected: Any
    actual: Any
    detail: str
    last_exact_tick: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _index(trace: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in trace:
        tick = row.get("tick")
        if type(tick) is not int:
            raise ValueError("every trace row must contain integer tick")
        out[tick] = dict(row)
    return out


def _match_entity(expected: Mapping[str, Any], entities: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if type(expected.get("uid")) is int:
        return next((x for x in entities if x.get("uid") == expected["uid"]), None)
    keys = [k for k in ("card_id", "team", "owner", "role", "kind") if k in expected]
    candidates = [x for x in entities if all(x.get(k) == expected.get(k) for k in keys)]
    return candidates[0] if len(candidates) == 1 else None


def _partial_diff(expected: Any, actual: Any, path: str = "") -> tuple[str, Any, Any] | None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return path or "$", expected, actual
        for key, value in expected.items():
            if key not in actual:
                return f"{path}.{key}".lstrip("."), value, None
            found = _partial_diff(value, actual[key], f"{path}.{key}".lstrip("."))
            if found:
                return found
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) > len(actual):
            return path or "$", expected, actual
        for i, value in enumerate(expected):
            found = _partial_diff(value, actual[i], f"{path}[{i}]")
            if found:
                return found
        return None
    if expected != actual:
        return path or "$", expected, actual
    return None


def compare_reference(
    reference: Mapping[str, Any],
    snapshots: Iterable[Mapping[str, Any]],
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    sim_by_tick = _index(snapshots)
    sim_events = [dict(e) for e in events]
    checked_ticks: list[int] = []
    divergences: list[FirstDivergence] = []

    for expected_snapshot in reference.get("snapshots", []):
        tick = expected_snapshot.get("tick")
        if type(tick) is not int:
            raise ValueError("reference snapshot requires integer tick")
        actual = sim_by_tick.get(tick)
        if actual is None:
            divergences.append(FirstDivergence(tick, "trace_coverage", expected_snapshot, None, "missing simulated snapshot", max(checked_ticks) if checked_ticks else None))
            continue

        top_expected = {k: v for k, v in expected_snapshot.items() if k != "entities"}
        found = _partial_diff(top_expected, actual)
        if found:
            path, exp, got = found
            divergences.append(FirstDivergence(tick, "state", exp, got, f"snapshot mismatch at {path}", max(checked_ticks) if checked_ticks else None))
            continue

        entity_failed = False
        for expected_entity in expected_snapshot.get("entities", []):
            match = _match_entity(expected_entity, list(actual.get("entities", [])))
            if match is None:
                divergences.append(FirstDivergence(tick, "entity_identity", expected_entity, None, "reference entity not uniquely found", max(checked_ticks) if checked_ticks else None))
                entity_failed = True
                break
            found = _partial_diff(expected_entity, match)
            if found:
                path, exp, got = found
                subsystem = "targeting" if "target" in path else "combat" if any(k in path for k in ("hp", "combat", "windup", "cooldown")) else "movement" if any(k in path for k in ("x", "y", "vx", "vy", "movement", "waypoint")) else "entity_state"
                divergences.append(FirstDivergence(tick, subsystem, exp, got, f"entity mismatch at {path}", max(checked_ticks) if checked_ticks else None))
                entity_failed = True
                break
        if not entity_failed:
            checked_ticks.append(tick)

    for expected_event in reference.get("events", []):
        tick = expected_event.get("tick")
        event_type = expected_event.get("type")
        tolerance = int(expected_event.get("tolerance_ticks", 0))
        candidates = [
            event for event in sim_events
            if event.get("type") == event_type
            and type(event.get("tick")) is int
            and type(tick) is int
            and abs(event["tick"] - tick) <= tolerance
        ]
        expected_payload = {k: v for k, v in expected_event.items() if k != "tolerance_ticks"}
        match = next((event for event in candidates if _partial_diff(expected_payload, event) is None), None)
        if match is None:
            divergences.append(FirstDivergence(int(tick or 0), "events", expected_payload, candidates, f"missing/mismatched {event_type}", max(checked_ticks) if checked_ticks else None))

    first = min(divergences, key=lambda d: d.tick) if divergences else None
    last_exact = max([t for t in checked_ticks if first is None or t < first.tick], default=None)
    return {
        "schema_version": 2,
        "passed": first is None,
        "first_divergence": None if first is None else {**first.to_dict(), "last_exact_tick": last_exact},
        "last_exact_tick": last_exact,
        "checked_snapshot_ticks": sorted(checked_ticks),
        "reference_snapshot_count": len(reference.get("snapshots", [])),
        "reference_event_count": len(reference.get("events", [])),
    }


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def validate_files(reference_path: str | Path, snapshots_path: str | Path, events_path: str | Path) -> dict[str, Any]:
    reference = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    return compare_reference(reference, load_jsonl(snapshots_path), load_jsonl(events_path))
