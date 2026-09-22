#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "starter"))

from cr_coach.validation.unified import validate_files


def main() -> int:
    parser = argparse.ArgumentParser(description="CR Coach unified mechanics validator")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--snapshots", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()

    report = validate_files(args.reference, args.snapshots, args.events)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
