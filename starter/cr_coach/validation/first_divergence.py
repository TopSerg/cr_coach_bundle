"""Small, deterministic first-divergence helpers for real/sim traces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from collections.abc import Iterable, Mapping
from typing import Any


@dataclass(frozen=True, slots=True)
class Divergence:
    tick: int
    subsystem: str
    real: Any
    simulated: Any
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


_MISSING = object()


def _tower_hp(snapshot: Mapping[str, Any]) -> Any:
    """Extract the raw tower representation from a public snapshot.

    Older traces call this field ``tower_hp`` while cr-bot state snapshots use
    ``towers`` or expose towers as ordinary entities. Preserve the raw value
    for useful diagnostics; comparison uses ``_canonical_tower_hp`` below.
    """

    if "towers" in snapshot:
        return snapshot["towers"]
    if "tower_hp" in snapshot:
        return snapshot["tower_hp"]
    entities = snapshot.get("entities")
    if isinstance(entities, list):
        towers = [
            entity
            for entity in entities
            if isinstance(entity, Mapping)
            and (entity.get("kind") == "tower" or entity.get("card_id") in {"king-tower", "princess-tower"})
        ]
        if towers:
            return towers
    return None

def _entity_key(entity: Mapping[str, Any], index: int) -> tuple[Any, ...]:
    # UID is the strongest identity when available. Role/card/owner make
    # observations from different implementations comparable when UIDs are
    # allocated differently.
    if entity.get("uid") is not None:
        return ("uid", entity.get("uid"))
    return (
        "tower",
        entity.get("owner"),
        entity.get("role"),
        entity.get("card_id"),
        index,
    )


def _canonical_tower_hp(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _canonical_tower_hp(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, Mapping) for item in value):
            pairs = []
            for index, item in enumerate(value):
                hp = item.get("hp", item.get("hitpoints", item.get("tower_hp", _MISSING)))
                if hp is _MISSING:
                    # A list of tower records without an HP field carries no
                    # evidence for this comparator.
                    continue
                pairs.append((_entity_key(item, index), hp))
            return tuple(sorted(pairs, key=repr))
        return tuple(value)
    return value


def _trace_by_tick(trace: Iterable[dict[str, Any]], label: str) -> tuple[dict[int, dict[str, Any]], list[int]]:
    indexed: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for index, snapshot in enumerate(trace):
        if not isinstance(snapshot, Mapping):
            raise ValueError(f"{label}[{index}] must be a mapping")
        raw_tick = snapshot.get("tick", _MISSING)
        if raw_tick is _MISSING or type(raw_tick) is not int or raw_tick < 0:
            raise ValueError(f"{label}[{index}].tick must be a non-negative integer")
        tick = raw_tick
        # A duplicate tick is generally produced by a post-action flush. Keep
        # the last snapshot because it is the most authoritative state at that
        # cursor, while retaining deterministic first-seen ordering metadata.
        if tick not in indexed:
            order.append(tick)
        indexed[tick] = dict(snapshot)
    return indexed, order


def _coverage_divergence(
    real_by_tick: Mapping[int, Mapping[str, Any]],
    sim_by_tick: Mapping[int, Mapping[str, Any]],
) -> Divergence | None:
    if not real_by_tick and not sim_by_tick:
        return None
    if not real_by_tick:
        tick = min(sim_by_tick)
        return Divergence(
            tick=tick,
            subsystem="trace_coverage",
            real=None,
            simulated=dict(sim_by_tick[tick]),
            detail="real trace is empty",
        )
    if not sim_by_tick:
        tick = min(real_by_tick)
        return Divergence(
            tick=tick,
            subsystem="trace_coverage",
            real=dict(real_by_tick[tick]),
            simulated=None,
            detail="simulated trace is empty",
        )

    common = set(real_by_tick) & set(sim_by_tick)
    if not common:
        tick = min(min(real_by_tick), min(sim_by_tick))
        return Divergence(
            tick=tick,
            subsystem="trace_coverage",
            real=dict(real_by_tick.get(tick)) if tick in real_by_tick else None,
            simulated=dict(sim_by_tick.get(tick)) if tick in sim_by_tick else None,
            detail="real and simulated traces have no common tick",
        )

    real_min, real_max = min(real_by_tick), max(real_by_tick)
    sim_min, sim_max = min(sim_by_tick), max(sim_by_tick)
    if real_min != sim_min:
        tick = min(real_min, sim_min)
        return Divergence(
            tick=tick,
            subsystem="trace_coverage",
            real=dict(real_by_tick[tick]) if tick in real_by_tick else None,
            simulated=dict(sim_by_tick[tick]) if tick in sim_by_tick else None,
            detail=f"trace start differs: real={real_min}, simulated={sim_min}",
        )
    if real_max != sim_max:
        tick = max(real_max, sim_max)
        return Divergence(
            tick=tick,
            subsystem="trace_coverage",
            real=dict(real_by_tick[tick]) if tick in real_by_tick else None,
            simulated=dict(sim_by_tick[tick]) if tick in sim_by_tick else None,
            detail=f"trace end differs: real={real_max}, simulated={sim_max}",
        )
    return None


def first_tower_hp_divergence(
    real_trace: Iterable[dict[str, Any]],
    sim_trace: Iterable[dict[str, Any]],
) -> Divergence | None:
    """Return the earliest tower HP mismatch, aligned by absolute tick.

    Trace cadence may differ, so samples are matched by tick instead of list
    position. Missing intermediate samples are allowed; missing coverage at
    either edge is reported after all comparable ticks have been checked.
    """

    real_by_tick, _ = _trace_by_tick(real_trace, "real_trace")
    sim_by_tick, _ = _trace_by_tick(sim_trace, "sim_trace")
    common = sorted(set(real_by_tick) & set(sim_by_tick))
    mismatches: list[Divergence] = []
    for tick in common:
        real_raw = _tower_hp(real_by_tick[tick])
        sim_raw = _tower_hp(sim_by_tick[tick])
        if real_raw is None and sim_raw is None:
            continue
        if _canonical_tower_hp(real_raw) != _canonical_tower_hp(sim_raw):
            mismatches.append(
                Divergence(
                    tick=tick,
                    subsystem="tower_hp_or_combat",
                    real=real_raw,
                    simulated=sim_raw,
                    detail="first observed tower HP mismatch",
                )
            )

    coverage = _coverage_divergence(real_by_tick, sim_by_tick)
    if mismatches and coverage is not None:
        return min(mismatches + [coverage], key=lambda item: item.tick)
    if mismatches:
        return mismatches[0]
    # If both traces contain no tower observations, there is nothing to
    # compare. Coverage still matters because a truncated trace is a distinct
    # failure from a matching HP series.
    if any(_tower_hp(snapshot) is not None for snapshot in real_by_tick.values()) or any(
        _tower_hp(snapshot) is not None for snapshot in sim_by_tick.values()
    ):
        return coverage
    return None
