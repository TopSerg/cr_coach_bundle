#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cr_engine
import run_primary_pathing as common


def run_case(data: Any, ref: dict[str, Any]) -> dict[str, Any]:
    mapped = ref["manually_mapped_cells"]
    hog_pos = common.cell_to_rudy(mapped["hog"])
    cannon_pos = common.cell_to_rudy(mapped["cannon"])
    real = ref["events_relative_to_hog_play_s"]
    cannon_rel = float(real["cannon_play"])

    match = cr_engine.new_match(data, common.P1_DECK, common.P2_DECK)
    common.idle(match, 220)

    # Replay only the Hog/Cannon actions from the reference. Negative cannon time
    # means Cannon was already on the field before Hog was played.
    if cannon_rel < 0:
        common.play(match, 2, "cannon", cannon_pos)
        common.idle(match, int(round(-cannon_rel * common.TPS)))
        t0 = int(match.tick)
        common.play(match, 1, "hog-rider", hog_pos)
    else:
        t0 = int(match.tick)
        common.play(match, 1, "hog-rider", hog_pos)

    frames: list[dict[str, Any]] = [common.frame(match, t0)]
    cannon_played = cannon_rel < 0
    cannon_tick = int(round(cannon_rel * common.TPS)) if cannon_rel >= 0 else None

    for _ in range(260):
        rel_ticks = int(match.tick) - t0
        if not cannon_played and cannon_tick is not None and rel_ticks >= cannon_tick:
            common.play(match, 2, "cannon", cannon_pos)
            cannon_played = True
        match.step()
        frames.append(common.frame(match, t0))

    cannon_hp_drops = common.hp_drop_events(frames, "cannon", team=2)
    sim_hit_times = [float(e["t"]) for e in cannon_hp_drops]
    cannon_death = common.first_absence_after_seen(frames, "cannon", team=2)
    hog_death = common.first_absence_after_seen(frames, "hog-rider", team=1)
    expected_hits = [float(x) for x in real["hog_hits_cannon"]]
    tol = float(ref.get("comparison_tolerance_s", 0.10))

    comparisons: list[dict[str, Any]] = []
    for i in range(max(len(expected_hits), len(sim_hit_times))):
        expected = expected_hits[i] if i < len(expected_hits) else None
        sim = sim_hit_times[i] if i < len(sim_hit_times) else None
        delta = None if expected is None or sim is None else round(sim - expected, 3)
        comparisons.append({
            "event": f"hog_hit_cannon_{i + 1}",
            "real_s": expected,
            "sim_s": sim,
            "delta_s": delta,
            "pass": expected is not None and sim is not None and abs(delta) <= tol,
        })

    for name, expected, sim in (
        ("cannon_death", float(real["cannon_death"]), cannon_death),
        ("hog_death", float(real["hog_death"]), hog_death),
    ):
        delta = None if sim is None else round(float(sim) - expected, 3)
        comparisons.append({
            "event": name,
            "real_s": expected,
            "sim_s": sim,
            "delta_s": delta,
            "pass": sim is not None and abs(delta) <= tol,
        })

    # First divergence is deliberately mechanical: earliest event in real-time
    # order whose result falls outside tolerance or has a count mismatch.
    ordered = sorted(
        comparisons,
        key=lambda r: float("inf") if r["real_s"] is None else float(r["real_s"]),
    )
    first_div = next((r for r in ordered if not r["pass"]), None)

    return {
        "scenario": ref["id"],
        "coordinate_mapping": {
            "hog_cell": mapped["hog"],
            "cannon_cell": mapped["cannon"],
            "hog_rudy": list(hog_pos),
            "cannon_rudy": list(cannon_pos),
        },
        "real_events": real,
        "sim_events": {
            "hog_first_movement_s": common.first_movement_time(frames, "hog-rider", 1),
            "hog_hits_cannon_s": sim_hit_times,
            "cannon_hp_drop_events": cannon_hp_drops,
            "cannon_death_s": cannon_death,
            "hog_death_s": hog_death,
            "hog_river_crossing": common.river_crossing(frames, "hog-rider", 1),
        },
        "comparison": comparisons,
        "first_divergence": first_div,
        "pass": first_div is None,
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--references", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    data = cr_engine.load_data(args.data_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary = []
    for ref_path in args.references:
        ref = common.load_json(ref_path)
        result = run_case(data, ref)
        path = out / f"{ref['id'].lower()}.json"
        common.save_json(path, result)
        summary.append({
            "scenario": result["scenario"],
            "pass": result["pass"],
            "first_divergence": result["first_divergence"],
            "real": result["real_events"],
            "sim": result["sim_events"],
        })

        print(f"\n=== {result['scenario']} ===")
        for row in result["comparison"]:
            print(
                f"{row['event']:20s} real={row['real_s']} sim={row['sim_s']} "
                f"delta={row['delta_s']} pass={row['pass']}"
            )
        print(f"FIRST DIVERGENCE: {result['first_divergence']}")

    common.save_json(out / "summary.json", {"cases": summary})
    # A mismatch is diagnostic evidence, not a harness failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
