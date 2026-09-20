#!/usr/bin/env python3
"""Acceptance gate for every card visible in the supplied full Golem replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cr_engine


TEAM_DECK = [
    "golem", "baby-dragon", "skeleton-dragons", "fireball",
    "the-log", "night-witch", "valkyrie", "skeletons",
]
OPPONENT_DECK = [
    "dart-goblin", "goblin-curse", "giant", "goblins",
    "goblin-demolisher", "goblin-drill", "suspicious-bush", "clone",
]


def entities(match: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in match.get_entities()]


def smoke_cards(data: Any) -> list[dict[str, Any]]:
    rows = []
    for player, deck in ((1, TEAM_DECK), (2, OPPONENT_DECK)):
        for card in deck:
            match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
            before = {int(item["id"]) for item in entities(match)}
            y = -5_000 if player == 1 else 5_000
            accepted = int(match.play_observed_card(player, card, 5_500, y, 11))
            match.step()
            created = [item for item in entities(match) if int(item["id"]) not in before]
            if not created:
                raise AssertionError(f"{card}: accepted play created no entity")
            rows.append({
                "player": player,
                "card": card,
                "accepted_id": accepted,
                "created": sorted({str(item["card_key"]) for item in created}),
            })
    return rows


def night_witch_bats(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    match.spawn_troop(1, "night-witch", 0, -4_000, 11)
    for _ in range(45):
        match.step()
    bats = [e for e in entities(match) if e["card_key"].lower() == "bat" and e["team"] == 1]
    if len(bats) < 2:
        raise AssertionError(f"Night Witch spawned {len(bats)} bats, expected at least 2")
    return {"bats": len(bats)}


def golem_split(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    golem_id = int(match.seed_troop_state(1, "golem", 0, -1_000, 11, 1, True))
    match.spawn_troop(2, "valkyrie", 0, -1_000, 11)
    for _ in range(50):
        match.step()
    golem = next((e for e in entities(match) if int(e["id"]) == golem_id), None)
    golemites = [e for e in entities(match) if "golemite" in e["card_key"].lower() and e["team"] == 1]
    if golem is not None and golem.get("alive", True):
        raise AssertionError("low-HP Golem did not die in split probe")
    if len(golemites) < 2:
        raise AssertionError(f"Golem spawned {len(golemites)} Golemites, expected 2")
    return {"golem_id": golem_id, "golemites": len(golemites)}


def clone_probe(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    source_id = int(match.seed_troop_state(1, "skeletons", 0, -2_000, 11, 100, True))
    match.play_observed_card(1, "clone", 0, -2_000, 11)
    for _ in range(8):
        match.step()
    copies = [e for e in entities(match) if e["team"] == 1 and e["card_key"] == "skeletons"]
    if len(copies) < 2:
        raise AssertionError("Clone did not create a second Skeletons entity")
    if not any(int(e["max_hp"]) == 1 for e in copies):
        raise AssertionError("Clone copy is not capped at one HP")
    return {"source_id": source_id, "skeleton_entities": len(copies)}


def goblin_drill_probe(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    match.play_observed_card(2, "goblin-drill", 0, -1_000, 11)
    for _ in range(90):
        match.step()
    all_entities = entities(match)
    drill = [e for e in all_entities if e["card_key"] == "goblin-drill" and e["kind"] == "building"]
    spawned = [e for e in all_entities if e["team"] == 2 and e["card_key"].lower() == "goblin"]
    if not drill:
        raise AssertionError("Goblin Drill did not morph into its building")
    if not spawned:
        raise AssertionError("Goblin Drill did not spawn a Goblin")
    return {"drills": len(drill), "spawned_goblins": len(spawned)}


def curse_probe(data: Any) -> dict[str, Any]:
    match = cr_engine.new_match(data, TEAM_DECK, OPPONENT_DECK)
    target_id = int(match.seed_troop_state(2, "giant", 0, 2_000, 11, 100, True))
    before = next(e for e in entities(match) if int(e["id"]) == target_id)
    match.play_observed_card(1, "goblin-curse", 0, 2_000, 11)
    for _ in range(60):
        match.step()
    target = next((e for e in entities(match) if int(e["id"]) == target_id), None)
    if target is None or int(target["hp"]) >= int(before["hp"]):
        raise AssertionError("Goblin Curse did not damage the cursed troop")
    if target.get("num_buffs", 0) == 0:
        raise AssertionError("Goblin Curse did not apply its slow/DOT buff")
    return {"target_id": target_id, "target_hp_before": before["hp"], "target_hp_after": target["hp"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    data = cr_engine.load_data(args.data_dir)
    result = {
        "status": "PASS",
        "decks": {"team": TEAM_DECK, "opponent": OPPONENT_DECK},
        "card_smoke": smoke_cards(data),
        "night_witch": night_witch_bats(data),
        "golem": golem_split(data),
        "clone": clone_probe(data),
        "goblin_drill": goblin_drill_probe(data),
        "goblin_curse": curse_probe(data),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
