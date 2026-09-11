#!/usr/bin/env python3
"""Verify the user-facing Rudy JSON runner against one video reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "starter"))

from cr_coach.replay.io import load_replay
from cr_coach.runtime.rudy_runner import run_rudy_replay
from cr_coach.validation.event_times import compare_event_times, hog_cannon_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    report = run_rudy_replay(load_replay(args.input), args.out, data_dir=args.data_dir, sample_ticks=1)
    events = [json.loads(line) for line in (args.out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    actual = hog_cannon_metrics(events)
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    expected = {
        key: reference["events_relative_to_hog_play_s"][key]
        for key in ("hog_hits_cannon", "cannon_death", "hog_death")
    }
    comparison = compare_event_times(expected, actual, float(reference["comparison_tolerance_s"]))
    result = {
        "reference_id": reference["id"],
        "runtime_status": report["status"],
        "actual": actual,
        **comparison,
    }
    (args.out / "video_comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "failed" and comparison["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
