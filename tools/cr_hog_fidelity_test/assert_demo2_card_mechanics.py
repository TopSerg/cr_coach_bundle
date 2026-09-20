#!/usr/bin/env python3
"""Demo2 deck gate beyond Firecracker and Magic Archer.

This is intentionally split into two layers:

1. every remaining card from both visible decks must be accepted by the normal
   observed-card path and create an entity;
2. the two additional cross-card mechanics exposed by the full replay get
   strict interaction probes: rolling spells over bridge ground / Barbarian at
   the break point, and Electro Spirit's sequential chain.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cr_engine


TEAM_DECK = [
    "tesla",
    "barbarian-barrel",
    "hunter",
    "earthquake",
    "skeletons",
    "hog-rider",
    "electro-spirit",
    "firecracker",
]
OPPONENT_DECK = [
    "hog-rider",
    "bats",
    "guards",
    "firecracker",
    "fire-spirit",
    "the-log",
    "ice-spirit",
    "magic-archer",
]
EXCLUDED_FIRST_PASS = {"firecracker", "magic-archer"}


def snapshot(match: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in match.get_entities()]


def by_id(match: Any, entity_id: int) -> dict[str, Any] | None:
    return next((item for item in snapshot(match) if int(item["id"]) == entity_id), None)


def smoke_remaining_cards(data: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player, deck in ((1, TEAM_DECK), (2, OPPONENT_DECK)):
        for card in deck:
            if card in EXCLUDED_FIRST_PASS:
                continue
            match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
            before_ids = {int(item["id"]) for item in snapshot(match)}
            y = -5_000 if player == 1 else 5_000
            accepted_id = int(match.play_observed_card(player, card, 5_500, y, 11))
            match.step()
            created = [
                item for item in snapshot(match)
                if int(item["id"]) not in before_ids
            ]
            if not created:
                raise AssertionError(f"{card}: accepted play created no entity")
            rows.append({
                "player": player,
                "card": card,
                "accepted_id": accepted_id,
                "created_kinds": sorted({str(item["kind"]) for item in created}),
                "created_count": len(created),
            })
    return rows


def rolling_bridge_probe(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    match.play_observed_card(2, "the-log", 5_500, 3_000, 11)

    # P2 rolls toward negative Y: from +3000 over the right bridge to the P1
    # side. Put the stationary target at -3000 so open-water blocking bugs fail.
    target_id = int(match.spawn_building(1, "cannon", 5_500, -3_000, 11))
    target0 = by_id(match, target_id)
    if target0 is None:
        raise AssertionError("rolling bridge target missing")
    target_hp0 = int(target0["hp"])
    first_large_drop: int | None = None
    previous_hp = target_hp0
    for tick in range(1, 70):
        match.step()
        target = by_id(match, target_id)
        if target is None:
            first_large_drop = tick
            break
        hp = int(target["hp"])
        if previous_hp - hp >= 100:
            first_large_drop = tick
            break
        previous_hp = hp

    if first_large_drop is None:
        raise AssertionError("The Log stopped at the river instead of crossing the right bridge")
    return {
        "cast": [5_500, 3_000],
        "target": [5_500, -3_000],
        "first_large_damage_tick": first_large_drop,
    }


def barbarian_barrel_probe(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    match.play_observed_card(1, "barbarian-barrel", 5_500, -3_000, 11)
    barbarian: dict[str, Any] | None = None
    found_tick: int | None = None
    for tick in range(1, 70):
        match.step()
        troops = [
            item for item in snapshot(match)
            if int(item["team"]) == 1 and item["kind"] == "troop"
        ]
        if troops:
            barbarian = troops[0]
            found_tick = tick
            break
    if barbarian is None:
        raise AssertionError("Barbarian Barrel never emitted its Barbarian")
    if int(barbarian["y"]) < 1_000:
        raise AssertionError(
            "Barbarian appeared at cast origin/river edge instead of the barrel break point: "
            f"y={barbarian['y']}"
        )
    return {
        "cast": [5_500, -3_000],
        "expected_break": [5_500, 1_500],
        "spawn_tick": found_tick,
        "spawn_position": [int(barbarian["x"]), int(barbarian["y"])],
        "card_key": barbarian["card_key"],
    }


def electro_spirit_chain_probe(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    # Current Aug-26-2026 Electro Spirit chain radius is 3.0 tiles.
    # Keep synthetic targets comfortably inside that limit so normal troop
    # movement/collision before impact cannot turn an exact-boundary check into
    # a false negative.
    target_positions = [(0, 2_500), (2_500, 2_500), (5_000, 2_500)]
    target_ids = [
        int(match.seed_troop_state(2, "knight", x, y, 11, 100, True))
        for x, y in target_positions
    ]
    initial_hp = {target_id: int(by_id(match, target_id)["hp"]) for target_id in target_ids}
    match.seed_troop_state(1, "electro-spirit", 0, 0, 11, 100, False)

    minimum_hp = dict(initial_hp)
    stunned_ids: set[int] = set()
    for _ in range(80):
        match.step()
        for target_id in target_ids:
            target = by_id(match, target_id)
            if target is None:
                minimum_hp[target_id] = 0
                continue
            minimum_hp[target_id] = min(minimum_hp[target_id], int(target["hp"]))
            if bool(target.get("is_stunned")):
                stunned_ids.add(target_id)

    missed_damage = [target_id for target_id in target_ids if minimum_hp[target_id] >= initial_hp[target_id]]
    if missed_damage:
        raise AssertionError(f"Electro Spirit chain missed damage targets: {missed_damage}")
    if len(stunned_ids) != len(target_ids):
        raise AssertionError(
            "Electro Spirit chain did not carry ZapFreeze to every target: "
            f"stunned={sorted(stunned_ids)}"
        )
    return {
        "target_ids": target_ids,
        "target_positions": target_positions,
        "initial_hp": initial_hp,
        "minimum_hp": minimum_hp,
        "stunned_ids": sorted(stunned_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = cr_engine.load_data(args.data_dir)
    result = {
        "status": "PASS",
        "remaining_card_smoke": smoke_remaining_cards(data),
        "rolling_bridge": rolling_bridge_probe(data),
        "barbarian_barrel": barbarian_barrel_probe(data),
        "electro_spirit_chain": electro_spirit_chain_probe(data),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
