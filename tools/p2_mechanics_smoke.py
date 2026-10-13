#!/usr/bin/env python3
"""P2 M13/M19/M20 deterministic *synthetic* fidelity gates on patched Rudy.

Controlled between-tick repositioning isolates a mechanic from pathfinding
and incidental aggro. Combat, collision, projectile and damage execution stay
in the production Rust engine. No physical reference is claimed here.
"""
from __future__ import annotations

import json
from math import hypot
from pathlib import Path

import cr_engine  # type: ignore

DATA = Path(__file__).resolve().parents[1] / "outputs" / "rudy_tournament11_data"
DECK = [
    "fireball", "valkyrie", "giant", "knight",
    "musketeer", "cannon", "hog-rider", "wizard",
]


def new_match():
    return cr_engine.new_match(cr_engine.load_data(str(DATA)), DECK, DECK)


def step(match):
    result = dict(match.step_trace())
    result["entities"] = [dict(row) for row in result["entities"]]
    result["events"] = [dict(event) for event in result["events"]]
    return result


def entity(frame, uid):
    return next((e for e in frame["entities"] if e["uid"] == uid), None)


def relocate(match, locations):
    for uid, (x, y) in locations.items():
        assert match.debug_relocate_entity(uid, x, y), f"Could not relocate UID {uid}"


def assert_m13_collision_and_mass():
    """Same-layer overlap separates; heavier troop moves less in a pair."""
    match = new_match()
    heavy = match.spawn_troop(1, "giant", -1000, -5000, 11, False)
    light = match.spawn_troop(1, "knight", 1000, -5000, 11, False)
    for _ in range(26):  # Both troops complete deployment.
        step(match)

    # Fresh geometry for exactly one engine tick, away from enemy towers.
    relocate(match, {heavy: (0, -5000), light: (300, -5000)})
    frame = step(match)
    a, b = entity(frame, heavy), entity(frame, light)
    assert a and b
    assert a["mass"] > b["mass"] > 0, (a["mass"], b["mass"])
    assert a["collision_radius"] > 0 and b["collision_radius"] > 0
    assert not a["is_flying"] and not b["is_flying"]
    separation = hypot(a["x"] - b["x"], a["y"] - b["y"])
    assert separation > 300, f"M13: overlapping ground units did not separate: {separation}"

    # Compare *radial* displacement to remove shared march direction bias.
    heavy_push = abs(a["x"])
    light_push = abs(b["x"] - 300)
    assert light_push > heavy_push, (
        f"M13: inverse-mass separation violated, heavy={heavy_push} light={light_push}"
    )

    # Ground/air pairs must not be resolved as same-plane collisions.
    separate = new_match()
    knight = separate.spawn_troop(1, "knight", 0, -5000, 11, False)
    balloon = separate.spawn_troop(1, "balloon", 0, -5000, 11, False)
    for _ in range(26):
        step(separate)
    relocate(separate, {knight: (0, -5000), balloon: (0, -5000)})
    one_tick = step(separate)
    g, air = entity(one_tick, knight), entity(one_tick, balloon)
    assert g and air and not g["is_flying"] and air["is_flying"]
    spacing = hypot(g["x"] - air["x"], g["y"] - air["y"])
    assert spacing < 250, (
        f"M13: ground and air units were pushed apart as solid bodies: {spacing}"
    )
    return {
        "M13_mass": "synthetic_pass",
        "M13_collision_layers": "synthetic_pass",
    }


def assert_m19_projectile_splash():
    """Fireball cast must have flight, then hit near targets but not far target."""
    match = new_match()
    match.set_elixir(1, 10)
    center = match.spawn_troop(2, "giant", 0, 2200, 11, False)
    near = match.spawn_troop(2, "giant", 1400, 2200, 11, False)
    far = match.spawn_troop(2, "giant", 4800, 2200, 11, False)
    for _ in range(26):
        step(match)
    positions = {center: (0, 2200), near: (1400, 2200), far: (4800, 2200)}
    relocate(match, positions)
    before = step(match)
    baseline = {uid: entity(before, uid)["hp"] for uid in positions}

    hand = match.p1_hand()
    assert "fireball" in hand, f"Fireball not present in test hand: {hand}"
    match.play_card(1, hand.index("fireball"), 0, 2200, 11)
    first_damage_tick = {}
    projectile_seen = False
    for _ in range(125):
        relocate(match, positions)
        frame = step(match)
        projectile_seen |= any(
            e.get("kind") == "projectile" and "fireball" in str(e.get("card_id", "")).lower()
            for e in frame["entities"]
        )
        for uid in positions:
            e = entity(frame, uid)
            if e is None or e["hp"] < baseline[uid]:
                first_damage_tick.setdefault(uid, frame["tick"])
        if center in first_damage_tick and near in first_damage_tick:
            break

    assert center in first_damage_tick and near in first_damage_tick, (
        f"M19: near splash victims not damaged: {first_damage_tick}"
    )
    assert far not in first_damage_tick, f"M19: far victim damaged: {first_damage_tick}"
    assert first_damage_tick[center] == first_damage_tick[near], (
        f"M19: AoE victim set resolved on different ticks: {first_damage_tick}"
    )
    assert first_damage_tick[center] > before["tick"] + 1, (
        "M19: projectile damage was applied on cast instead of delayed impact"
    )
    return {"M19_fireball_victim_set": "synthetic_pass"}


def assert_m20_melee_splash():
    """Valkyrie attack must damage two enemies in one impact, not a distant one."""
    match = new_match()
    valk = match.spawn_troop(1, "valkyrie", 0, -2000, 11, False)
    left = match.spawn_troop(2, "giant", -750, -2000, 11, False)
    right = match.spawn_troop(2, "giant", 750, -2000, 11, False)
    far = match.spawn_troop(2, "giant", 4200, -2000, 11, False)
    for _ in range(26):
        step(match)
    # The probe is placed outside Princess Tower ranges. Otherwise a far
    # control can lose HP to a tower and look like an AoE false positive.
    positions = {
        valk: (0, -2000),
        left: (-750, -2000),
        right: (750, -2000),
        far: (4200, -2000),
    }
    relocate(match, positions)
    before = step(match)
    baseline = {uid: entity(before, uid)["hp"] for uid in (left, right, far)}

    first_damage_tick = {}
    attack_tick = None
    for _ in range(100):
        relocate(match, positions)
        frame = step(match)
        for e in frame["events"]:
            if e["type"] == "MELEE_HIT" and e["uid"] == valk:
                attack_tick = frame["tick"] if attack_tick is None else attack_tick
        for uid in (left, right, far):
            e = entity(frame, uid)
            if e is None or e["hp"] < baseline[uid]:
                first_damage_tick.setdefault(uid, frame["tick"])
        if left in first_damage_tick and right in first_damage_tick:
            break

    assert attack_tick is not None, "M20: no authoritative melee impact"
    assert left in first_damage_tick and right in first_damage_tick, (
        f"M20: missing shared splash damage: {first_damage_tick}"
    )
    assert far not in first_damage_tick, "M20: distant enemy hit by melee AoE"
    assert first_damage_tick[left] == first_damage_tick[right], (
        f"M20: splash victims did not share an impact tick: {first_damage_tick}"
    )
    return {"M20_melee_victim_set": "synthetic_pass"}


def main():
    outcomes = {}
    for test in (
        assert_m13_collision_and_mass,
        assert_m19_projectile_splash,
        assert_m20_melee_splash,
    ):
        outcomes.update(test())
    print(json.dumps({"p2": outcomes, "physical_verified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
