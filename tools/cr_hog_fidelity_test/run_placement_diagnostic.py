#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cr_engine
import placement
import run_primary_pathing as common


def deck_with(card: str) -> list[str]:
    # common.P1_DECK already contains eight known-good cards.  Replacing/prepending
    # one card must still leave an 8-card deck even when `card` is itself in the base.
    filler = [x for x in common.P1_DECK if x != card]
    return [card] + filler[:7]


def one_probe(data: Any, card: str, kind: str, selected_cell: list[int]) -> dict[str, Any]:
    center_grid2 = placement.cell_center_to_grid2(selected_cell)
    legal_center = placement.grid2_to_rudy(center_grid2)
    # Deliberately request an impossible fractional position.  A player-action API
    # should resolve this according to the card's placement lattice.
    request = (legal_center[0] + 230, legal_center[1] - 170)

    p1 = deck_with(card)
    p2 = deck_with("knight")
    match = cr_engine.new_match(data, p1, p2)
    common.idle(match, 220)
    common.play(match, 1, card, request)
    fr = common.frame(match, int(match.tick))
    ent = common.find_card(fr, card, 1)
    if ent is None:
        raise RuntimeError(f"{card} entity not found after play")
    actual = (int(ent["x"]), int(ent["y"]))

    # Convert actual Rudy units back into grid2 when it lands on the 500-unit
    # half-tile lattice.  Otherwise leave it as non-lattice.
    actual_grid2 = None
    if actual[0] % placement.HALF_TILE == 0 and actual[1] % placement.HALF_TILE == 0:
        actual_grid2 = [
            actual[0] // placement.HALF_TILE + placement.ARENA_COLS,
            placement.ARENA_ROWS - actual[1] // placement.HALF_TILE,
        ]

    profile = placement.profile_for(card, kind)
    phase = None if actual_grid2 is None else placement.phase_of(actual_grid2)
    phase_valid = False if actual_grid2 is None else placement.validate_center_phase(card, actual_grid2, kind)

    return {
        "card": card,
        "kind": kind,
        "profile": {
            "footprint_tiles": list(profile.footprint_tiles),
            "expected_center_phase": profile.center_phase,
            "selected_anchor": profile.selected_anchor,
        },
        "selected_cell": selected_cell,
        "selected_cell_center_grid2": list(center_grid2),
        "selected_cell_center_rudy": list(legal_center),
        "requested_off_grid_rudy": list(request),
        "actual_entity_center_rudy": list(actual),
        "actual_entity_center_grid2": actual_grid2,
        "actual_phase": phase,
        "phase_valid_for_profile": phase_valid,
        "snapped_to_selected_tile_center": actual == legal_center,
        "notes": (
            "For 2x2 buildings the selected tile is not the geometric center; "
            "True Red/True Blue corner resolution must be modeled separately."
            if profile.center_phase == "tile_intersection"
            else ""
        ),
    }


def render_md(rows: list[dict[str, Any]]) -> str:
    out = [
        "# Placement lattice diagnostic",
        "",
        "| Card | Footprint | Requested Rudy | Actual center | Actual phase | Expected phase | Valid |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for r in rows:
        p = r["profile"]
        out.append(
            f"| {r['card']} | {p['footprint_tiles'][0]}x{p['footprint_tiles'][1]} | "
            f"{r['requested_off_grid_rudy']} | {r['actual_entity_center_rudy']} | "
            f"{r['actual_phase'] or 'off half-tile lattice'} | {p['expected_center_phase']} | "
            f"{'✅' if r['phase_valid_for_profile'] else '❌'} |"
        )
    out += [
        "",
        "`Valid` checks only the lattice phase of the entity center. It does not yet validate deploy zones or True Red/True Blue corner choice.",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown-out")
    ap.add_argument("--github-step-summary", action="store_true")
    args = ap.parse_args()

    data = cr_engine.load_data(args.data_dir)
    probes = [
        one_probe(data, "hog-rider", "troop", [9, 18]),
        one_probe(data, "cannon", "building", [9, 10]),
        one_probe(data, "tesla", "building", [9, 10]),
    ]

    payload = {"coordinate_model": "grid2 half-tile units", "probes": probes}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md = render_md(probes)
    print(md)
    if args.markdown_out:
        p = Path(args.markdown_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md + "\n", encoding="utf-8")
    if args.github_step_summary:
        import os
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with Path(target).open("a", encoding="utf-8") as f:
                f.write(md + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
