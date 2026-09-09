#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

PURE_VIDEO_SCENARIOS = {
    "d03_hog_cannon_01_SECONDARY",
    "d02_hog_cannon_01_CROSSDEMO",
}


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description="Strict fidelity gate for the Hog+Cannon+Princess-Tower core milestone.")
    ap.add_argument("--postfix-summary", required=True)
    ap.add_argument("--solo-report", required=True)
    ap.add_argument("--out")
    ap.add_argument("--github-step-summary", action="store_true")
    args = ap.parse_args()

    postfix = load(args.postfix_summary)
    solo = load(args.solo_report)
    cases = {c["scenario"]: c for c in postfix.get("cases", [])}

    missing = sorted(PURE_VIDEO_SCENARIOS - set(cases))
    rows: list[tuple[str, bool, str]] = []

    rows.append(("Solo Hog → Princess Tower", bool(solo.get("pass")), "all solo metrics"))

    for scenario in sorted(PURE_VIDEO_SCENARIOS):
        c = cases.get(scenario)
        if c is None:
            rows.append((scenario, False, "missing result"))
            continue
        div = c.get("first_divergence")
        detail = "all video events within tolerance" if c.get("pass") else (
            f"first divergence: {div.get('event')} Δ={fmt(div.get('delta_s'))} s" if div else "fidelity mismatch"
        )
        rows.append((scenario, bool(c.get("pass")), detail))

    passed = not missing and all(ok for _, ok, _ in rows)

    md = [
        "# Hog + Cannon + Princess core gate",
        "",
        f"**Status:** {'✅ PASS' if passed else '❌ FAIL'}",
        "",
        "This strict milestone intentionally includes only source scenarios whose active combat set is Hog Rider, Cannon and Crown/Princess Towers. PRIMARY is excluded from the strict death-time gate because its source clip also contains Ice Golem + Hunter context.",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for name, ok, detail in rows:
        md.append(f"| {name} | {'✅ PASS' if ok else '❌ FAIL'} | {detail} |")
    md.append("")
    text = "\n".join(md)
    print(text)

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")

    if args.github_step_summary:
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with Path(target).open("a", encoding="utf-8") as f:
                f.write(text + "\n")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
