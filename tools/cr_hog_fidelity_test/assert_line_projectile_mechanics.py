#!/usr/bin/env python3
"""Strict synthetic guards for Firecracker and Magic Archer line mechanics.

Both probes use a stationary Cannon as the acquired target and the enemy right
Princess Tower exactly five tiles behind it.  This keeps the assertion about
projectile behaviour rather than troop movement or video coordinate recovery:

* Magic Archer must damage the Cannon and continue through it to the tower.
* Firecracker must emit five FirecrackerExplosion children at the Cannon and
  the centre of that fan must damage the tower behind it.

The unpatched engine fails both tower assertions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cr_engine


P1_DECK = [
    "magic-archer",
    "firecracker",
    "hog-rider",
    "hunter",
    "earthquake",
    "skeletons",
    "electro-spirit",
    "barbarian-barrel",
]
P2_DECK = [
    "cannon",
    "knight",
    "archers",
    "fireball",
    "giant",
    "valkyrie",
    "musketeer",
    "zap",
]

X = 5_500
SHOOTER_Y = -500
TARGET_Y = 4_500
P2_RIGHT_TOWER_Y = 9_500
MAX_TICKS = 160


def entities(match: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in match.get_entities()]


def entity_by_id(match: Any, entity_id: int) -> dict[str, Any] | None:
    return next((item for item in entities(match) if int(item["id"]) == entity_id), None)


def projectile_count(match: Any, key: str) -> int:
    return sum(
        1
        for item in entities(match)
        if item.get("kind") == "projectile"
        and item.get("card_key") == key
        and bool(item.get("alive", True))
    )


def run_probe(data: Any, shooter_key: str) -> dict[str, Any]:
    match = cr_engine.new_match(data, P1_DECK, P2_DECK)
    target_id = int(match.spawn_building(2, "cannon", X, TARGET_Y, 11))
    shooter_id = int(match.spawn_troop(1, shooter_key, X, SHOOTER_Y, 11))
    target_start = entity_by_id(match, target_id)
    if target_start is None:
        raise AssertionError("Cannon target was not spawned")

    target_initial_hp = int(target_start["hp"])
    tower_initial_hp = int(match.p2_tower_hp()[2])
    target_first_damage_tick: int | None = None
    tower_first_damage_tick: int | None = None
    max_firecracker_children = 0
    saw_magic_arrow = False

    for tick in range(1, MAX_TICKS + 1):
        match.step()
        target = entity_by_id(match, target_id)
        if target is not None and int(target["hp"]) < target_initial_hp:
            target_first_damage_tick = target_first_damage_tick or tick
        if int(match.p2_tower_hp()[2]) < tower_initial_hp:
            tower_first_damage_tick = tower_first_damage_tick or tick
        max_firecracker_children = max(
            max_firecracker_children,
            projectile_count(match, "FirecrackerExplosion"),
        )
        saw_magic_arrow = saw_magic_arrow or projectile_count(match, "EliteArcherArrow") > 0
        if target_first_damage_tick is not None and tower_first_damage_tick is not None:
            break

    target_end = entity_by_id(match, target_id)
    return {
        "shooter": shooter_key,
        "shooter_id": shooter_id,
        "target_id": target_id,
        "target_initial_hp": target_initial_hp,
        "target_final_hp": None if target_end is None else int(target_end["hp"]),
        "tower_initial_hp": tower_initial_hp,
        "tower_final_hp": int(match.p2_tower_hp()[2]),
        "target_first_damage_tick": target_first_damage_tick,
        "tower_first_damage_tick": tower_first_damage_tick,
        "max_firecracker_children": max_firecracker_children,
        "saw_magic_arrow": saw_magic_arrow,
        "ticks_run": int(match.tick),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = cr_engine.load_data(args.data_dir)
    magic = run_probe(data, "magic-archer")
    firecracker = run_probe(data, "firecracker")

    failures: list[str] = []
    if magic["target_first_damage_tick"] is None:
        failures.append("Magic Archer never damaged the acquired Cannon")
    if not magic["saw_magic_arrow"]:
        failures.append("Magic Archer never released EliteArcherArrow")
    if magic["tower_first_damage_tick"] is None:
        failures.append("Magic Archer arrow stopped at the Cannon instead of piercing to the tower")

    if firecracker["target_first_damage_tick"] is None:
        failures.append("Firecracker never damaged the acquired Cannon")
    if firecracker["max_firecracker_children"] != 5:
        failures.append(
            "Firecracker emitted "
            f"{firecracker['max_firecracker_children']} visible child projectiles instead of 5"
        )
    if firecracker["tower_first_damage_tick"] is None:
        failures.append("Firecracker did not damage the tower with the secondary fan")

    result = {
        "status": "FAIL" if failures else "PASS",
        "geometry": {
            "x": X,
            "shooter_y": SHOOTER_Y,
            "target_y": TARGET_Y,
            "tower_y": P2_RIGHT_TOWER_Y,
        },
        "magic_archer": magic,
        "firecracker": firecracker,
        "failures": failures,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
