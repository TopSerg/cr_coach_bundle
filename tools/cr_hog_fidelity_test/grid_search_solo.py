#!/usr/bin/env python3
"""Grid-search only the uncertain Hog placement for the solo video probe."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from compare import compare


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--real", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--data-dir", default="data/")
    args = ap.parse_args()

    cfg = load(args.config)["scenarios"]["hog_solo"]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    script = Path(__file__).with_name("run_rudy.py")
    for x in cfg["hog_position_grid"]["x_values"]:
        for y in cfg["hog_position_grid"]["y_values"]:
            trace = out / f"solo_x{x}_y{y}.json"
            cmd = [
                sys.executable, str(script),
                "--scenario", "solo",
                "--config", args.config,
                "--data-dir", args.data_dir,
                "--out-dir", str(out),
                "--solo-x", str(x),
                "--solo-y", str(y),
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            produced = out / "hog_solo_trace.json"
            produced.replace(trace)
            res = compare(args.real, trace)
            rows.append({"x": x, "y": y, "score": res["score"], "pass": res["pass"], "report": res})

    rows.sort(key=lambda r: r["score"])
    best = rows[0]
    result = {"best": best, "candidates": rows}
    (out / "solo_grid_search.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"best": {"x": best["x"], "y": best["y"], "score": best["score"], "pass": best["pass"]}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
