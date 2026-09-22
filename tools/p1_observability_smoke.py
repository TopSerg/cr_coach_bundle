#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter"))

import cr_engine  # type: ignore
from cr_coach.validation.unified import compare_reference

REQUIRED_FIELDS = {
    "tick","uid","card_id","team","x","y","vx","vy","hp","shield_hp",
    "movement_state","target_uid","target_locked","combat_phase",
    "windup_remaining","cooldown_remaining","load_progress",
    "active_statuses","charge_state","path_target","current_waypoint",
    "active_projectiles",
}

def main() -> int:
    data_dir = ROOT / "outputs" / "rudy_tournament11_data"
    data = cr_engine.load_data(str(data_dir))
    deck = ["hog-rider","cannon","knight","archers","fireball","giant","valkyrie","musketeer"]
    match = cr_engine.new_match(data, deck, deck)
    if not hasattr(match, "step_trace"):
        raise SystemExit("P-1 FAIL: patched cr_engine has no step_trace()")

    hog = match.spawn_troop(1, "hog-rider", 5500, -1500, 11, False)
    match.spawn_building(2, "cannon", 1500, 5000, 11)

    all_events = []
    last = None
    for _ in range(80):
        last = dict(match.step_trace())
        entities = [dict(row) for row in last["entities"]]
        all_events.extend(dict(row) for row in last["events"])
        hog_rows = [row for row in entities if row["uid"] == hog]
        if hog_rows:
            missing = REQUIRED_FIELDS - set(hog_rows[0])
            if missing:
                raise SystemExit(f"P-1 FAIL: missing trace fields: {sorted(missing)}")
        if any(event.get("type") in {"TARGET_ACQUIRED","ATTACK_WINDUP_STARTED","MELEE_HIT"} for event in all_events):
            break

    if last is None:
        raise SystemExit("P-1 FAIL: no trace produced")
    if not any(event.get("type") == "TARGET_ACQUIRED" for event in all_events):
        raise SystemExit("P-1 FAIL: no Rust-side TARGET_ACQUIRED observed")

    # Verify FIRST_DIVERGENCE + last_exact_tick independently of game fidelity.
    snapshots = [
        {"tick": 1, "entities": [{"uid": 1, "card_id": "hog-rider", "team": 0, "hp": 100}]},
        {"tick": 2, "entities": [{"uid": 1, "card_id": "hog-rider", "team": 0, "hp": 90}]},
    ]
    reference = {
        "snapshots": [
            {"tick": 1, "entities": [{"uid": 1, "hp": 100}]},
            {"tick": 2, "entities": [{"uid": 1, "hp": 80}]},
        ]
    }
    report = compare_reference(reference, snapshots, [])
    div = report["first_divergence"]
    if report["passed"] or div is None or div["tick"] != 2 or div["last_exact_tick"] != 1:
        raise SystemExit(f"P-1 FAIL: FIRST_DIVERGENCE semantics broken: {json.dumps(report)}")

    out = ROOT / "outputs" / "p1_observability"
    out.mkdir(parents=True, exist_ok=True)
    (out / "rust_events.json").write_text(json.dumps(all_events, indent=2), encoding="utf-8")
    (out / "smoke_report.json").write_text(json.dumps({
        "passed": True,
        "required_fields": sorted(REQUIRED_FIELDS),
        "event_types_seen": sorted({event.get("type") for event in all_events}),
        "first_divergence_self_test": report,
    }, indent=2), encoding="utf-8")
    print("P-1 PASS: Rust trace fields, Rust transition events, FIRST_DIVERGENCE")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
