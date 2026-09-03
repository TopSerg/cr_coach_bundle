from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Iterable
import json

@dataclass(frozen=True, slots=True)
class Divergence:
    tick: int
    subsystem: str
    real: Any
    simulated: Any
    detail: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _tower_hp(snapshot: dict[str, Any]) -> Any:
    return snapshot.get("towers") or snapshot.get("tower_hp")


def first_tower_hp_divergence(
    real_trace: Iterable[dict[str, Any]],
    sim_trace: Iterable[dict[str, Any]],
) -> Divergence | None:
    for real, sim in zip(real_trace, sim_trace):
        tick = int(real.get("tick", sim.get("tick", -1)))
        r = _tower_hp(real)
        s = _tower_hp(sim)
        if r is not None and s is not None and r != s:
            return Divergence(
                tick=tick,
                subsystem="tower_hp_or_combat",
                real=r,
                simulated=s,
                detail="first observed tower HP mismatch",
            )
    return None
