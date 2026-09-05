#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def load_optional(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def fmt_num(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return f"{float(v):.{digits}f}"
    return str(v)


def fmt_delta(real: Any, sim: Any) -> str:
    if real is None or sim is None:
        return "—"
    delta = float(sim) - float(real)
    return f"{delta:+.2f}"


def fmt_list(values: list[Any] | None) -> str:
    if not values:
        return "—"
    return " / ".join(fmt_num(v) for v in values)


def case_row(case: dict[str, Any]) -> str:
    real = case.get("real_events", {})
    sim = case.get("sim_events", {})
    real_hits = list(real.get("hog_hits_cannon", []) or [])
    sim_hits = list(sim.get("hog_hits_cannon_s", []) or [])
    hit_deltas = []
    for i in range(max(len(real_hits), len(sim_hits))):
        r = real_hits[i] if i < len(real_hits) else None
        s = sim_hits[i] if i < len(sim_hits) else None
        hit_deltas.append(fmt_delta(r, s))

    div = case.get("first_divergence")
    if div:
        div_text = f"{div.get('event', '?')} ({fmt_delta(div.get('real_s'), div.get('sim_s'))} s)"
    else:
        div_text = "—"

    status = "✅ PASS" if case.get("pass") else "⚠️ DIFF"
    return "| {scenario} | {status} | {real_hits} | {sim_hits} | {hit_deltas} | {cannon} | {hog} | {div} |".format(
        scenario=case.get("scenario", "?"),
        status=status,
        real_hits=fmt_list(real_hits),
        sim_hits=fmt_list(sim_hits),
        hit_deltas=" / ".join(hit_deltas) if hit_deltas else "—",
        cannon=f"{fmt_num(real.get('cannon_death'))} → {fmt_num(sim.get('cannon_death_s'))} ({fmt_delta(real.get('cannon_death'), sim.get('cannon_death_s'))})",
        hog=f"{fmt_num(real.get('hog_death'))} → {fmt_num(sim.get('hog_death_s'))} ({fmt_delta(real.get('hog_death'), sim.get('hog_death_s'))})",
        div=div_text,
    )


def render(postfix: dict[str, Any] | None, solo: dict[str, Any] | None, bridge: dict[str, Any] | None) -> str:
    lines: list[str] = []
    lines += [
        "# Rudy fidelity regression summary",
        "",
        "> `⚠️ DIFF` means a fidelity mismatch against the video reference, not a CI/harness crash.",
        "",
    ]

    if postfix and postfix.get("cases"):
        cases = list(postfix["cases"])
        passed = sum(1 for c in cases if c.get("pass"))
        lines += [
            f"**Video regressions:** {passed}/{len(cases)} within reference tolerance.",
            "",
            "| Scenario | Status | Real Hog hits, s | Sim Hog hits, s | Hit deltas, s | Cannon death real→sim (Δ) | Hog death real→sim (Δ) | First divergence |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
        lines.extend(case_row(c) for c in cases)
        lines.append("")
    else:
        lines += ["## Video regressions", "", "Regression summary is not available (an earlier build/test step may have failed).", ""]

    lines += ["## Solo Hog guard", ""]
    if solo:
        lines.append(f"**Status:** {'✅ PASS' if solo.get('pass') else '❌ FAIL'}")
        lines += [
            "",
            "| Metric | Real | Sim | Error | Status |",
            "|---|---:|---:|---:|---|",
        ]
        for m in solo.get("metrics", []):
            real = m.get("real")
            sim = m.get("sim")
            err = m.get("abs_error")
            if isinstance(real, list) or isinstance(sim, list):
                real_text = str(real)
                sim_text = str(sim)
            else:
                real_text = fmt_num(real, 3)
                sim_text = fmt_num(sim, 3)
            lines.append(
                f"| {m.get('metric', '?')} | {real_text} | {sim_text} | {fmt_num(err, 3)} | {'✅' if m.get('pass') else '❌'} |"
            )
        lines.append("")
    else:
        lines += ["Solo report is not available.", ""]

    lines += ["## Bridge routing guard", ""]
    if bridge:
        on_bridge = bool(bridge.get("entered_river_on_bridge"))
        off_water = not bool(bridge.get("off_bridge_river_samples"))
        no_bounce = not bool(bridge.get("river_bounce_detected"))
        crossing = bridge.get("crossing", {}) or {}
        bridge_pass = on_bridge and off_water and no_bounce and crossing.get("exit") is not None
        lines += [
            f"**Status:** {'✅ PASS' if bridge_pass else '❌ FAIL'}",
            "",
            "| Check | Result |",
            "|---|---|",
            f"| Entered river on bridge | {'✅' if on_bridge else '❌'} |",
            f"| No open-water samples | {'✅' if off_water else '❌'} |",
            f"| No river-edge bounce | {'✅' if no_bounce else '❌'} |",
            f"| Crossing duration | {fmt_num(crossing.get('duration_s'))} s |",
            f"| Max bridge-zone turn | {fmt_num(bridge.get('max_bridge_zone_turn_deg'))}° |",
            "",
        ]
    else:
        lines += ["Bridge report is not available.", ""]

    lines += [
        "## Raw diagnostics",
        "",
        "The artifact still contains full JSON traces with per-tick entities, HP, positions, attack phases, cooldowns and river/path data.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--postfix-summary")
    ap.add_argument("--solo-report")
    ap.add_argument("--bridge-report")
    ap.add_argument("--out")
    ap.add_argument("--github-step-summary", nargs="?", const="ENV")
    args = ap.parse_args()

    md = render(
        load_optional(args.postfix_summary),
        load_optional(args.solo_report),
        load_optional(args.bridge_report),
    )
    print(md)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md + "\n", encoding="utf-8")
        print(f"saved {out}")

    if args.github_step_summary is not None:
        target = os.environ.get("GITHUB_STEP_SUMMARY") if args.github_step_summary == "ENV" else args.github_step_summary
        if target:
            with Path(target).open("a", encoding="utf-8") as f:
                f.write(md + "\n")
            print(f"appended GitHub step summary: {target}")
        else:
            print("GITHUB_STEP_SUMMARY is not set; skipped Actions summary append")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
