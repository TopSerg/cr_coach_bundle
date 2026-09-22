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
    for _ in range(160):
        last = dict(match.step_trace())
        entities = [dict(row) for row in last["entities"]]
        all_events.extend(dict(row) for row in last["events"])
        hog_rows = [row for row in entities if row["uid"] == hog]
        if hog_rows:
            missing = REQUIRED_FIELDS - set(hog_rows[0])
            if missing:
                raise SystemExit(f"P-1 FAIL: missing trace fields: {sorted(missing)}")
        kinds = {event.get("type") for event in all_events}
        if {"TARGET_ACQUIRED", "JUMP_STARTED", "JUMP_LANDED"}.issubset(kinds):
            break

    if last is None:
        raise SystemExit("P-1 FAIL: no trace produced")
    event_types = {event.get("type") for event in all_events}
    if "TARGET_ACQUIRED" not in event_types:
        raise SystemExit("P-1 FAIL: no Rust-side TARGET_ACQUIRED observed")
    if "JUMP_STARTED" not in event_types or "JUMP_LANDED" not in event_types:
        raise SystemExit(f"P-1 FAIL: Hog river jump boundary events missing: {sorted(event_types)}")

    # Knockback is authoritative through Rudy's knockback_stun runtime buff.
    # Fireball a live Knight and require both start and expiry transitions.
    kb_deck = ["fireball","hog-rider","cannon","knight","archers","giant","valkyrie","musketeer"]
    kb_match = cr_engine.new_match(data, kb_deck, kb_deck)
    kb_match.set_elixir(1, 10)
    victim = kb_match.spawn_troop(2, "knight", 0, 0, 11, False)
    kb_match.play_card(1, 0, 0, 0, 11)

    knockback_events = []
    for _ in range(180):
        trace = dict(kb_match.step_trace())
        knockback_events.extend(
            dict(event)
            for event in trace["events"]
            if dict(event).get("uid") == victim
        )
        kb_types = {event.get("type") for event in knockback_events}
        if {"KNOCKBACK_STARTED", "KNOCKBACK_ENDED"}.issubset(kb_types):
            break

    kb_types = {event.get("type") for event in knockback_events}
    if "KNOCKBACK_STARTED" not in kb_types or "KNOCKBACK_ENDED" not in kb_types:
        raise SystemExit(f"P-1 FAIL: knockback lifecycle events missing: {sorted(kb_types)}")
    all_events.extend(knockback_events)

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
