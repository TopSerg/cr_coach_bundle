"""Promote repeated, confident visual measurements into a *sparse* reference.

The result never claims internal engine states (targets/windup) from pixels.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from .session import NS_PER_TICK, read_json, atomic_json


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def build_reference(detections: list[dict], start_ns: int, min_confidence: float = 0.85,
                    repeat_window_ticks: int = 20) -> dict[str, Any]:
    if not 0 <= min_confidence <= 1 or repeat_window_ticks < 1:
        raise ValueError("invalid confidence or repeat window")
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    rejected = defaultdict(int)
    for row in detections:
        if row.get("kind") != "tower_hp":
            rejected["unsupported_or_unverified_kind"] += 1
            continue
        if row.get("confidence", 0) < min_confidence:
            rejected["low_confidence"] += 1
            continue
        if row.get("owner") not in (0, 1) or row.get("role") not in ("king", "left", "right") or type(row.get("hp")) is not int:
            rejected["invalid_measurement"] += 1
            continue
        tick = round((int(row["timestamp_ns"]) - start_ns) / NS_PER_TICK)
        if tick < 0:
            rejected["before_match_start"] += 1
            continue
        item = {**row, "tick": tick}
        grouped[(row["owner"], row["role"])].append(item)
    output = []
    for (owner, role), series in grouped.items():
        series.sort(key=lambda item: (item["tick"], item["side"]))
        for idx, item in enumerate(series):
            neighbors = [other for other in series if other["hp"] == item["hp"] and abs(other["tick"] - item["tick"]) <= repeat_window_ticks and (other["frame"], other["side"]) != (item["frame"], item["side"])]
            rivals = [other for other in series if other["hp"] != item["hp"] and abs(other["tick"] - item["tick"]) <= 2 and other.get("side") != item.get("side")]
            if rivals:
                rejected["conflicting_two_device_ocr"] += 1
                continue
            if not neighbors:
                rejected["not_repeated"] += 1
                continue
            if idx and series[idx-1]["tick"] == item["tick"] and series[idx-1]["hp"] == item["hp"]:
                continue
            output.append({"tick": item["tick"], "tick_uncertainty": max(2, (int(item.get("time_uncertainty_ns", 0)) + NS_PER_TICK - 1) // NS_PER_TICK),
                           "kind": "tower_hp", "owner": owner, "role": role, "hp": item["hp"],
                           "confidence": round(min([item["confidence"]] + [v["confidence"] for v in neighbors]), 3),
                           "source": "repeated_ocr", "evidence": [item["frame"], neighbors[0]["frame"]]})
    output.sort(key=lambda v: (v["tick"], v["owner"], v["role"]))
    # Optional compatibility view for the P-1 unified validator. It is exact-tick,
    # hence conservative visual comparison should use observations instead.
    snapshots_by_tick: dict[int, list[dict]] = defaultdict(list)
    for item in output:
        card = "king-tower" if item["role"] == "king" else "princess-tower"
        snapshots_by_tick[item["tick"]].append({"owner": item["owner"], "role": item["role"], "card_id": card, "hp": item["hp"]})
    return {"schema_version": 1, "source": "two_android_emulators_ocr", "ticks_per_second": 20,
            "observations": output, "snapshots": [{"tick": t, "entities": entities} for t, entities in sorted(snapshots_by_tick.items())],
            "events": [], "rejected": dict(rejected), "limitations": ["OCR gives tower HP only, not projectile source or target UID", "start marker and ADB latency bound event timing", "high-confidence repeated samples are still not ground truth without review"]}


def reference_from_session(directory: Path, detections_path: Path, out: Path, min_confidence: float = 0.85) -> dict:
    start_ns = read_json(directory / "match_start.json")["start_utc_ns"]
    result = build_reference(load_jsonl(detections_path), start_ns, min_confidence=min_confidence)
    atomic_json(out, result)
    return result
