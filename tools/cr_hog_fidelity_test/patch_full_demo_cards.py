#!/usr/bin/env python3
"""Add the three post-2025 cards used by the supplied full replay.

The pinned Rudy data snapshot predates Goblin Curse, Goblin Demolisher and
Suspicious Bush.  The replay is otherwise a normal level-11 match, so the
smallest safe integration point is the generated Tournament-11 data overlay:
copy the closest existing schema records and replace their card-specific
values.  This keeps the engine data-driven and makes the omission fail closed
at data-build time instead of silently treating a played card as invalid.

The overlay intentionally models the mechanics visible in this replay:
Demolisher's ranged splash/death bomb, Bush stealth + two Goblins on contact,
and Curse's six-second damage/slow/death-Goblin zone.  Charge threshold tuning
for Demolisher remains a later video-calibration item.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def one(records: list[dict], field: str, value: str) -> dict:
    matches = [record for record in records if str(record.get(field) or "") == value]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {field}={value!r}, found {len(matches)}")
    return copy.deepcopy(matches[0])


def levels(value: int, count: int = 11) -> list[int]:
    # The CI bundle is Tournament-11 only.  Keeping all entries populated also
    # avoids a loader fallback to level-one data when a probe asks for level 11.
    return [value] * count


def upsert(records: list[dict], field: str, value: str, record: dict) -> None:
    for index, existing in enumerate(records):
        if existing.get(field) == value:
            records[index] = record
            return
    records.append(record)


def patch(data_dir: Path) -> dict:
    root = data_dir / "royaleapi"
    cards = load(root / "cards.json")
    characters = load(root / "cards_stats_characters.json")
    projectiles = load(root / "cards_stats_projectile.json")
    spells = load(root / "cards_stats_spell.json")
    buffs = load(root / "cards_stats_character_buff.json")

    # Video calibration from XRecorder_20260920_02(2).mp4:
    # Night Witch is played at ~19.1s and the first Bat wave becomes visible
    # at ~22.0s.  The pinned data releases that first wave ~1s too early.
    # Keep the normal repeating cadence, but move the initial wave to 3.0s.
    for index, record in enumerate(characters):
        if record.get("key") == "night-witch" or record.get("name") == "DarkWitch":
            patched = copy.deepcopy(record)
            patched["spawn_start_time"] = 3000
            characters[index] = patched
            break
    else:
        raise RuntimeError("Night Witch character row not found for spawn timing calibration")

    # Card registry entries are used for hand/deck validation and elixir cost.
    dart_card = one(cards, "key", "dart-goblin")
    drill_card = one(cards, "key", "goblin-drill")
    poison_card = one(cards, "key", "poison")

    demolisher_card = copy.deepcopy(dart_card)
    demolisher_card.update(
        key="goblin-demolisher", name="Goblin Demolisher", sc_key="GoblinDemolisher",
        elixir=4, id=26000095, arena=14, summon_character="GoblinDemolisher",
        description="A charged goblin with a ranged bomb and a death blast.",
    )
    bush_card = copy.deepcopy(drill_card)
    bush_card.update(
        key="suspicious-bush", name="Suspicious Bush", sc_key="SuspiciousBush",
        elixir=2, id=26000097, arena=14, type="Troop", summon_character="SuspiciousBush",
        description="A stealthy bush that releases two Goblins on contact.",
    )
    curse_card = copy.deepcopy(poison_card)
    curse_card.update(
        key="goblin-curse", name="Goblin Curse", sc_key="GoblinCurse",
        elixir=2, id=28000024, arena=14,
        description="Damages and slows enemy troops, turning their deaths into Goblins.",
    )
    for card in (demolisher_card, bush_card, curse_card):
        upsert(cards, "key", card["key"], card)

    # Goblin Demolisher: ranged ground splash plus the observed death blast.
    dart = one(characters, "name", "BlowdartGoblin")
    demolisher = copy.deepcopy(dart)
    demolisher.update(
        name="GoblinDemolisher", name_en="Goblin Demolisher", key="goblin-demolisher",
        sc_key="GoblinDemolisher", elixir=4, type="Troop", id=26000095,
        summon_character="GoblinDemolisher", hitpoints=1300, damage=0,
        hit_speed=1100, load_time=500, range=5000, attacks_ground=True,
        attacks_air=False, area_damage_radius=1500, target_only_buildings=False,
        collision_radius=400, mass=1, speed=120, projectile="GoblinDemolisherProjectile",
        death_damage=404, death_damage_radius=2500, death_push_back=0,
        death_spawn_character=None, death_spawn_count=0,
        hitpoints_per_level=levels(1300), damage_per_level=levels(186),
    )
    upsert(characters, "key", "goblin-demolisher", demolisher)

    dart_projectile = one(projectiles, "name", "BlowdartGoblinProjectile")
    demolisher_projectile = copy.deepcopy(dart_projectile)
    demolisher_projectile.update(
        name="GoblinDemolisherProjectile", speed=8000, homing=True, damage=186,
        radius=1500, aoe_to_ground=True, aoe_to_air=False,
        damage_per_level=levels(186), dps=0, dps_per_level=levels(0),
    )
    upsert(projectiles, "name", "GoblinDemolisherProjectile", demolisher_projectile)

    # Suspicious Bush is an invisible building-targeting kamikaze troop.  The
    # engine already removes a remove_on_attack stealth buff on contact and
    # applies death spawns through CharacterStats.
    wallbreaker = one(characters, "name", "Wallbreaker")
    bush = copy.deepcopy(wallbreaker)
    bush.update(
        name="SuspiciousBush", name_en="Suspicious Bush", key="suspicious-bush",
        sc_key="SuspiciousBush", elixir=2, type="Troop", id=26000097,
        summon_character="SuspiciousBush", hitpoints=81, damage=0, hit_speed=1400,
        load_time=0, range=1600, target_only_buildings=True, attacks_ground=True,
        attacks_air=False, collision_radius=400, mass=1, speed=120, kamikaze=True,
        projectile=None, area_damage_radius=0, death_damage=0, death_damage_radius=0,
        death_spawn_character="Goblin", death_spawn_count=2,
        death_spawn_radius=1600, death_spawn_min_radius=1600,
        starting_buff="SuspiciousBushInvisible", starting_buff_time=60000,
        hitpoints_per_level=levels(81), damage_per_level=levels(0),
    )
    upsert(characters, "key", "suspicious-bush", bush)

    invisibility = one(buffs, "name", "InvisibilityRemoveOnAttack")
    bush_invisibility = copy.deepcopy(invisibility)
    bush_invisibility["name"] = "SuspiciousBushInvisible"
    upsert(buffs, "name", "SuspiciousBushInvisible", bush_invisibility)

    # Goblin Curse uses the existing timed spell-zone + buff pipeline.  The
    # buff carries the slow, DOT and one Goblin on death; the crown reduction
    # matches the level-11 source (10 crown damage vs 35 troop damage/tick).
    poison = one(spells, "key", "poison")
    curse = copy.deepcopy(poison)
    curse.update(
        name="GoblinCurse", key="goblin-curse", sc_key="GoblinCurse",
        elixir=2, id=28000024, life_duration=6000, radius=3000,
        hit_speed=1000, buff="GoblinCurseFoe", buff_time=1100,
        only_enemies=True, hits_ground=True, hits_air=True, damage=0,
        damage_per_level=levels(0), can_place_on_buildings=True,
        can_place_on_water=True, can_deploy_on_enemy_side=True,
    )
    curse_buff = copy.deepcopy(poison.get("buff_data") or one(buffs, "name", "Poison"))
    curse_buff.update(
        name="GoblinCurseFoe", rarity="Legendary", crown_tower_damage_percent=-71,
        damage_per_second=35, hit_frequency=1000, speed_multiplier=-15,
        enable_stacking=True, death_spawn="Goblin", death_spawn_is_enemy=True,
        death_spawn_count=1, ignore_buildings=True,
    )
    curse["buff_data"] = curse_buff
    upsert(spells, "key", "goblin-curse", curse)
    upsert(buffs, "name", "GoblinCurseFoe", curse_buff)

    save(root / "cards.json", cards)
    save(root / "cards_stats_characters.json", characters)
    save(root / "cards_stats_projectile.json", projectiles)
    save(root / "cards_stats_spell.json", spells)
    save(root / "cards_stats_character_buff.json", buffs)
    return {
        "cards": ["goblin-demolisher", "suspicious-bush", "goblin-curse"],
        "mechanics": {
            "night-witch": "first Bat wave calibrated to 3.0s from card placement in supplied full replay",
            "goblin-demolisher": "ranged ground splash + death blast; charge threshold pending calibration",
            "suspicious-bush": "stealth building-targeting kamikaze + two Goblins",
            "goblin-curse": "6s DOT/slow zone + Goblin on cursed-unit death",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    data_dir = Path(args.data_dir).resolve()
    result = patch(data_dir)
    manifest = data_dir / "FULL_DEMO_CARDS_MANIFEST.json"
    save(manifest, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
