"""Compare visual facts with Rudy's authoritative snapshots.

Never invent unobservable game events or equate missing evidence with PASS.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .reference import load_jsonl
from .session import atomic_json


def _match_entity(entities: list[dict], obs: dict) -> dict | None:
    card = "king-tower" if obs["role"] == "king" else "princess-tower"
    found = [e for e in entities if e.get("owner") == obs["owner"] and e.get("role") == obs["role"] and e.get("card_id") == card]
    return found[0] if len(found) == 1 else None


def compare_visual(reference: dict, snapshots: list[dict], *, extra_tolerance_ticks: int = 2,
                   confirm_mismatches: int = 2) -> dict[str, Any]:
    if extra_tolerance_ticks < 0 or confirm_mismatches < 2:
        raise ValueError("invalid tolerance / mismatch confirmation count")
    by_tick = {s["tick"]: s for s in snapshots if type(s.get("tick")) is int}
    obs = reference.get("observations", [])
    checked = []
    missing = 0
    streaks: dict[tuple, list[dict]] = {}
    first = None
    for row in sorted(obs, key=lambda x: (x["tick"], x["owner"], x["role"])):
        if row.get("kind") != "tower_hp":
            continue
        tick = row["tick"]
        tolerance = max(extra_tolerance_ticks, int(row.get("tick_uncertainty", 0)))
        candidates = [t for t in by_tick if abs(t - tick) <= tolerance]
        if not candidates:
            missing += 1
            continue
        compared = [(t, _match_entity(by_tick[t].get("entities", []), row)) for t in candidates]
        present = [(t, ent) for t, ent in compared if ent is not None and type(ent.get("hp")) is int]
        if not present:
            missing += 1
            continue
        # Observation timing is an interval. Do not flag a divergence if the
        # true HP appears at ANY simulator tick inside that interval.
        matching = [(t, ent) for t, ent in present if ent["hp"] == row["hp"]]
        nearest_tick, entity = min(matching or present, key=lambda pair: (abs(pair[0] - tick), pair[0]))
        key = (row["owner"], row["role"])
        matched = entity["hp"] == row["hp"]
        result = {"tick": tick, "sim_tick": nearest_tick, "owner": key[0], "role": key[1],
                  "real_hp": row["hp"], "sim_hp": entity["hp"], "matched": matched,
                  "confidence": row["confidence"], "evidence": row.get("evidence", [])}
        checked.append(result)
        if matched:
            streaks[key] = []
        else:
            # Treat only repeated disagreements of the SAME observed HP as a
            # confirmed problem, never a brief one-frame OCR transition.
            previous = streaks.get(key, [])
            if previous and previous[-1]["real_hp"] != result["real_hp"]:
                previous = []
            streaks[key] = previous + [result]
            if first is None and len(streaks[key]) >= confirm_mismatches:
                start = streaks[key][0]
                first = {"tick": start["tick"], "subsystem": "tower_hp_or_combat_timing",
                         "expected": start["real_hp"], "actual": start["sim_hp"],
                         "detail": "Repeated tower HP discrepancy; damage vs timing is NOT identified by OCR alone",
                         "owner": start["owner"], "role": start["role"],
                         "evidence": start["evidence"],
                         "last_exact_tick": max((r["tick"] for r in checked if r["matched"] and r["tick"] < start["tick"]), default=None)}
    if not checked:
        status = "INCONCLUSIVE"
    elif first:
        status = "FIRST_DIVERGENCE"
    elif missing or any(not r["matched"] for r in checked):
        status = "INCONCLUSIVE"
    else:
        status = "PASS_OBSERVED"
    return {"schema_version": 1, "status": status, "passed": status == "PASS_OBSERVED",
            "first_divergence": first, "checked_observations": len(checked),
            "matching_observations": sum(v["matched"] for v in checked),
            "unmatched_observations": sum(not v["matched"] for v in checked),
            "missing_simulation_coverage": missing, "reference_observations": len(obs),
            "caveat": "PASS_OBSERVED checks only visible reference values; not full Rudy mechanics verification",
            "comparisons": checked}


def compare_files(reference_path: Path, snapshots_path: Path, output: Path) -> dict:
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    report = compare_visual(reference, load_jsonl(snapshots_path))
    atomic_json(output, report)
    return report


def diagnose(report: dict) -> dict:
    first = report.get("first_divergence")
    if not first:
        return {"ready_to_patch": False, "reason": "No confirmed first divergence"}
    if first["subsystem"] == "tower_hp_or_combat_timing":
        return {"ready_to_patch": False, "first_tick": first["tick"],
                "possible_causes": ["action accepted later than logged", "tower firing or projectile impact cadence", "incorrect attack damage / patch / card level", "OCR, tower mapping or game-start offset"],
                "next_experiment": "Isolate one attacker and record repeated HP staircase with manual HUD clock alignment",
                "reason": "HP mismatch alone cannot justify selecting or editing a physics constant"}
    return {"ready_to_patch": False, "reason": "Unclassified observation: inspect manually"}
