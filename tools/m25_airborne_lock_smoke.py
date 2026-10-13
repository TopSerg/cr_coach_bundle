#!/usr/bin/env python3
"""M12/M25: same-tick ground-only retarget vs Inferno beam retention on Hog jump.

Synthetic fidelity gate on actual patched Rust cr_engine. Both defenses have
the *same* original Hog target before takeoff and a valid new ground target.
The second, transition-only shared targeting pass must drop Cannon's old
lock immediately, but must not interrupt Inferno Tower's air-capable beam/ramp.

Current-patch physical verification remains separate.
"""
from __future__ import annotations

import json
from pathlib import Path
import cr_engine  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "rudy_tournament11_data"
DECK = [
    "hog-rider", "cannon", "inferno-tower", "knight",
    "musketeer", "giant", "archers", "fireball",
]


def step(match):
    value = dict(match.step_trace())
    value["entities"] = [dict(row) for row in value["entities"]]
    value["events"] = [dict(event) for event in value["events"]]
    return value


def row(frame, uid):
    return next((e for e in frame["entities"] if e["uid"] == uid), None)


def run_case(building_card: str):
    match = cr_engine.new_match(cr_engine.load_data(str(DATA)), DECK, DECK)
    hog = match.spawn_troop(1, "hog-rider", 0, -2300, 11, False)
    defender = match.spawn_building(2, building_card, 0, 3000, 11)
    replacement = match.spawn_troop(1, "knight", 8000, -14000, 11, False)
    assert all(isinstance(x, int) for x in (hog, defender, replacement))

    saw_prejump_lock = False
    inserted_replacement = False
    ramp_prejump = None
    jump_start = None
    airborne = []
    transition_events = []
    last_prejump = None

    for _ in range(105):
        frame = step(match)
        h, tower = row(frame, hog), row(frame, defender)
        if h is None or tower is None:
            break
        state = h.get("jump_state")
        if state in ("none", "approaching_jump"):
            last_prejump = frame
            if tower["target_uid"] == hog:
                saw_prejump_lock = True
            # An already-deployed enemy appears in range, after the
            # existing sticky lock has been established but before takeoff.
            # Hog ignores this troop because it targets buildings only.
            if (saw_prejump_lock and not inserted_replacement
                    and -1500 <= h["y"] < -1000):
                assert match.debug_relocate_entity(replacement, 2000, -1500)
                inserted_replacement = True
                ramp_prejump = tower.get("ramp_ticks", 0)
        elif state == "airborne":
            airborne.append(frame)
            if jump_start is None:
                jump_start = frame["tick"]
                transition_events = [
                    e for e in frame["events"]
                    if e.get("uid") == defender and e.get("type") in
                    ("TARGET_ACQUIRED", "TARGET_CHANGED", "TARGET_DROPPED")
                ]
            # Enough midair ticks to verify ramp persistence.
            if len(airborne) >= 4:
                break

    assert saw_prejump_lock, f"{building_card}: never locked Hog before jump"
    assert inserted_replacement, f"{building_card}: could not stage alternative ground target"
    assert jump_start is not None, f"{building_card}: no airborne jump transition"
    assert last_prejump is not None
    assert airborne and airborne[0]["tick"] > last_prejump["tick"]
    return {
        "hog": hog, "defender": defender, "replacement": replacement,
        "last_prejump": last_prejump, "airborne": airborne,
        "ramp_prejump": ramp_prejump, "jump_start": jump_start,
        "transition_events": transition_events,
    }


def assert_cannon_drops_and_retargets():
    case = run_case("cannon")
    h, defender, replacement = case["hog"], case["defender"], case["replacement"]
    first = case["airborne"][0]
    assert row(first, h)["jump_state"] == "airborne"
    assert row(first, defender)["target_uid"] == replacement, (
        "M12: ground-only Cannon must drop airborne Hog AND immediately acquire "
        "the available ground Knight on the jump-start tick"
    )
    assert any(
        e["type"] == "TARGET_CHANGED"
        and e.get("old_target_uid") == h
        and e.get("target_uid") == replacement
        for e in case["transition_events"]
    ), f"M12: missing authoritative target switch event: {case['transition_events']}"
    assert all(row(f, defender)["target_uid"] != h for f in case["airborne"]), (
        "M12: Cannon reacquired Hog before landing"
    )
    return {"M12_cannon_airborne_retarget": "synthetic_pass"}


def assert_inferno_retains_ramp():
    case = run_case("inferno-tower")
    h, defender, replacement = case["hog"], case["defender"], case["replacement"]
    assert case["ramp_prejump"] is not None and case["ramp_prejump"] > 0, (
        f"M25: Inferno did not establish ramp before Hog jump: {case['ramp_prejump']}"
    )
    previous = case["ramp_prejump"]
    for f in case["airborne"]:
        b = row(f, defender)
        assert b is not None
        assert b["target_uid"] == h, (
            f"M25: air-capable Inferno switched away from jumping Hog to {replacement}"
        )
        assert b["ramp_target_uid"] == h, "M25: Inferno ramp lost original UID lock"
        assert b["ramp_ticks"] >= previous, (
            f"M25: Inferno ramp reset during airborne interval: {previous} -> {b['ramp_ticks']}"
        )
        previous = b["ramp_ticks"]
    assert previous > case["ramp_prejump"], (
        "M25: Inferno ramp did not continue counting during the jump"
    )
    assert not case["transition_events"], (
        "M25: Inferno must not emit a TARGET_CHANGED/DROPPED on takeoff"
    )
    return {"M25_inferno_airborne_lock_continuity": "synthetic_pass"}


def main():
    gates = {}
    gates.update(assert_cannon_drops_and_retargets())
    gates.update(assert_inferno_retains_ramp())
    print(json.dumps({"gates": gates, "physical_verified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
