#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import cr_engine
import run_primary_pathing as common
import run_postfix_regressions as regress


def score(result: dict) -> float:
    rows = result.get("comparison", [])
    total = 0.0
    for row in rows:
        if row.get("event", "").startswith("hog_hit_cannon_"):
            d = row.get("delta_s")
            total += 100.0 if d is None else abs(float(d))
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--references", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = cr_engine.load_data(args.data_dir)
    payload = {"cases": []}

    for ref_path in args.references:
        ref = common.load_json(ref_path)
        base_h = list(ref["manually_mapped_cells"]["hog"])
        base_c = list(ref["manually_mapped_cells"]["cannon"])
        rows = []
        for hdx in (-1, 0, 1):
            for hdy in (-1, 0, 1):
                for cdx in (-1, 0, 1):
                    for cdy in (-1, 0, 1):
                        test_ref = copy.deepcopy(ref)
                        test_ref["manually_mapped_cells"]["hog"] = [base_h[0] + hdx, base_h[1] + hdy]
                        test_ref["manually_mapped_cells"]["cannon"] = [base_c[0] + cdx, base_c[1] + cdy]
                        result = regress.replay_case(data, test_ref)
                        hits = result["sim_events"].get("hog_hits_cannon_s", [])
                        expected = result["real_events"].get("hog_hits_cannon", [])
                        first_delta = None
                        if hits and expected:
                            first_delta = round(float(hits[0]) - float(expected[0]), 3)
                        rows.append({
                            "hog_cell": test_ref["manually_mapped_cells"]["hog"],
                            "cannon_cell": test_ref["manually_mapped_cells"]["cannon"],
                            "hog_offset": [hdx, hdy],
                            "cannon_offset": [cdx, cdy],
                            "hits": hits,
                            "first_hit_delta_s": first_delta,
                            "cannon_death_s": result["sim_events"].get("cannon_death_s"),
                            "hog_death_s": result["sim_events"].get("hog_death_s"),
                            "score": score(result),
                        })
        rows.sort(key=lambda r: (r["score"], abs(r["first_hit_delta_s"]) if r["first_hit_delta_s"] is not None else 999))
        baseline = next(r for r in rows if r["hog_offset"] == [0, 0] and r["cannon_offset"] == [0, 0])
        payload["cases"].append({
            "scenario": ref["id"],
            "baseline": baseline,
            "top10": rows[:10],
        })

        print(f"\n=== {ref['id']} ===")
        print("baseline:", json.dumps(baseline, ensure_ascii=False))
        for i, row in enumerate(rows[:10], 1):
            print(f"{i:02d}. hog={row['hog_cell']} cannon={row['cannon_cell']} first_delta={row['first_hit_delta_s']} hits={row['hits']} score={row['score']}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
