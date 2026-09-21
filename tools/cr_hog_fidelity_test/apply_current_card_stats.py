#!/usr/bin/env python3
"""Apply the current public Level-11 card stat catalog to a generated Rudy data tree.

This is deliberately a *data* overlay, not a physics rewrite.  It updates the
public/UI-facing facts that are safe to transfer directly (HP, damage, hit
speed, range, deploy time, target class, elixir, spell radius, etc.) while the
video regression suite remains authoritative for hidden timings and geometry.

The pinned Rudy snapshot predates several current cards.  For missing cards we
create a conservative Level-11 runtime stub so the card is accepted and its
basic public stats exist in the simulator.  Unique mechanics are explicitly
reported as pending instead of being silently invented.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def ids(record: dict[str, Any]) -> set[str]:
    return {norm(record.get(k)) for k in ("key", "name", "name_en", "sc_key") if record.get(k)}


def find_one(records: list[dict[str, Any]], *selectors: str) -> dict[str, Any] | None:
    wanted = {norm(s) for s in selectors if s}
    matches = [r for r in records if ids(r) & wanted]
    if not matches:
        return None
    # Prefer an exact key match, then the first normalized identity match.
    for record in matches:
        if norm(record.get("key")) in wanted:
            return record
    return matches[0]


def upsert_by_key(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    key = norm(record.get("key"))
    for i, old in enumerate(records):
        if norm(old.get("key")) == key:
            records[i] = record
            return
    records.append(record)


def level11(record: dict[str, Any], array_field: str, scalar_field: str, value: int) -> None:
    arr = record.get(array_field)
    if isinstance(arr, list) and arr:
        if len(arr) < 11:
            arr.extend([arr[-1]] * (11 - len(arr)))
        arr[10] = int(value)
    else:
        # Current overlay is Tournament-11.  A repeated fallback keeps loaders
        # deterministic for generated stubs without pretending lower levels were researched.
        record[array_field] = [int(value)] * 11
    if scalar_field in record and not isinstance(record.get(scalar_field), list):
        # Preserve base-level scalar semantics on old records; generated stubs
        # explicitly set their scalar separately.
        pass


def raw_speed(speed_tiles: float | int | None) -> int:
    if speed_tiles is None:
        return 60
    pairs = ((0.75, 45), (1.0, 60), (1.5, 90), (2.0, 120))
    return min(pairs, key=lambda p: abs(float(speed_tiles) - p[0]))[1]


def sc_key(display: str) -> str:
    return "".join(part for part in re.split(r"[^A-Za-z0-9]+", display) if part)


def card_key(catalog_key: str) -> str:
    return catalog_key.replace("_", "-")


def patch_registry(cards: list[dict[str, Any]], key: str, stat: dict[str, Any], synthetic_id: int) -> tuple[dict[str, Any], bool]:
    ck = card_key(key)
    record = find_one(cards, ck, stat.get("display", ""))
    created = record is None
    if record is None:
        template_name = "knight" if stat.get("kind") == "troop" else ("cannon" if stat.get("kind") == "building" else "fireball")
        template = find_one(cards, template_name)
        if template is None:
            raise RuntimeError(f"registry template {template_name!r} not found")
        record = copy.deepcopy(template)
        record["id"] = int(stat.get("official_id") or synthetic_id)
        record["sc_key"] = str(stat.get("sc_key") or sc_key(stat.get("display", key)))
        if stat.get("kind") in {"troop", "building"}:
            record["summon_character"] = record["sc_key"]
        cards.append(record)
    elif not record.get("sc_key"):
        # Existing Rudy cards already carry the real internal Supercell key
        # (Magic Archer -> EliteArcher, Bandit -> Assassin, etc.). Never replace
        # that identity with a display-name-derived guess.
        record["sc_key"] = str(stat.get("sc_key") or sc_key(stat.get("display", key)))
    record["key"] = ck
    record["name"] = stat.get("display", key)
    record["elixir"] = int(stat.get("elixir") or record.get("elixir") or 0)
    record["rarity"] = str(stat.get("rarity") or record.get("rarity") or "").title()
    record["type"] = str(stat.get("kind") or record.get("type") or "").title()
    return record, created


def patch_character(record: dict[str, Any], stat: dict[str, Any], *, generated: bool) -> list[str]:
    fields: list[str] = []
    if stat.get("hitpoints") is not None:
        level11(record, "hitpoints_per_level", "hitpoints", int(stat["hitpoints"]))
        if generated:
            record["hitpoints"] = int(stat["hitpoints"])
        fields.append("hitpoints")
    if stat.get("damage") is not None:
        level11(record, "damage_per_level", "damage", int(stat["damage"]))
        if generated:
            record["damage"] = int(stat["damage"])
        fields.append("damage")
    if stat.get("hit_speed") is not None:
        record["hit_speed"] = int(round(float(stat["hit_speed"]) * 1000))
        fields.append("hit_speed")
    if stat.get("first_hit_s") is not None:
        record["load_time"] = int(round(float(stat["first_hit_s"]) * 1000))
        fields.append("first_hit")
    if stat.get("range_tiles") is not None:
        record["range"] = int(round(float(stat["range_tiles"]) * 1000))
        fields.append("range")
    if stat.get("deploy_time") is not None:
        record["deploy_time"] = int(round(float(stat["deploy_time"]) * 1000))
        fields.append("deploy_time")
    if stat.get("sight_range_tiles") is not None:
        record["sight_range"] = int(round(float(stat["sight_range_tiles"]) * 1000))
        fields.append("sight_range")
    if stat.get("splash_radius") is not None:
        record["area_damage_radius"] = int(round(float(stat["splash_radius"]) * 1000))
        fields.append("splash_radius")
    if stat.get("collision_radius_tiles") is not None:
        record["collision_radius"] = int(round(float(stat["collision_radius_tiles"]) * 1000))
        fields.append("collision_radius")
    if stat.get("mass") is not None:
        record["mass"] = int(stat["mass"])
        fields.append("mass")

    attacks = set(stat.get("attacks") or [])
    if attacks:
        only_buildings = attacks == {"buildings"}
        record["target_only_buildings"] = only_buildings
        record["attacks_ground"] = bool("ground" in attacks or "buildings" in attacks)
        record["attacks_air"] = bool("air" in attacks)
        fields.append("targets")

    if generated:
        record["speed"] = int(stat.get("raw_speed") or raw_speed(stat.get("speed_tiles")))
        if stat.get("movement") == "air":
            record["flying_height"] = int(record.get("flying_height") or 1500)
        else:
            record["flying_height"] = 0
        fields.append("movement_speed")
    return fields


def patch_spell(record: dict[str, Any], stat: dict[str, Any], *, generated: bool) -> list[str]:
    fields: list[str] = []
    if stat.get("damage") is not None:
        level11(record, "damage_per_level", "damage", int(stat["damage"]))
        if generated:
            record["damage"] = int(stat["damage"])
        fields.append("damage")
    if stat.get("radius_tiles") is not None:
        record["radius"] = int(round(float(stat["radius_tiles"]) * 1000))
        fields.append("radius")
    if stat.get("deploy_time") is not None:
        record["deploy_time"] = int(round(float(stat["deploy_time"]) * 1000))
        fields.append("deploy_time")
    if stat.get("hit_frequency_s") is not None:
        record["hit_speed"] = int(round(float(stat["hit_frequency_s"]) * 1000))
        fields.append("hit_frequency")
    if stat.get("freeze_duration_s") is not None:
        record["buff_time"] = int(round(float(stat["freeze_duration_s"]) * 1000))
        fields.append("freeze_duration")
    attacks = set(stat.get("attacks") or [])
    if attacks:
        record["hits_ground"] = bool("ground" in attacks)
        record["hits_air"] = bool("air" in attacks)
        fields.append("targets")
    if stat.get("damage") and stat.get("crown_tower_damage") is not None:
        ratio = float(stat["crown_tower_damage"]) / float(stat["damage"])
        record["crown_tower_damage_percent"] = int(round((ratio - 1.0) * 100))
        fields.append("crown_tower_damage")
    return fields


def clone_template(
    records: list[dict[str, Any]],
    candidates: list[str],
    predicate=None,
) -> dict[str, Any]:
    for candidate in candidates:
        found = find_one(records, candidate)
        if found is not None:
            return copy.deepcopy(found)
    if predicate is not None:
        for record in records:
            try:
                if predicate(record):
                    return copy.deepcopy(record)
            except Exception:
                continue
    raise RuntimeError(f"no template found: {candidates}")


def find_spell_projectile(
    projectiles: list[dict[str, Any]],
    registry: dict[str, Any],
) -> dict[str, Any] | None:
    """Mirror Rudy's spell-projectile lookup for Fireball/Log/Arrows/etc.

    Some spells have a zero-damage wrapper plus a separate payload record.
    The runtime loader selects the highest-scoring candidate (for example,
    ``LogProjectileRolling`` for The Log), so the overlay must patch that same
    record or the replay keeps stale level/tower-damage values.
    """
    sk = str(registry.get("sc_key") or "")
    if not sk:
        return None
    candidates = (f"{sk}Spell", f"{sk}Projectile", f"{sk}ProjectileRolling", sk)
    found_candidates = [
        found for candidate in candidates
        if (found := find_one(projectiles, candidate)) is not None
    ]
    if found_candidates:
        return max(
            found_candidates,
            key=lambda record: int(record.get("damage") or 0)
            + int(record.get("spawn_character_count") or 0) * 100,
        )

    wanted = norm(sk)
    candidates = [
        p for p in projectiles
        if wanted and wanted in norm(p.get("name"))
        and (int(p.get("damage") or 0) > 0 or int(p.get("spawn_character_count") or 0) > 0)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p: int(p.get("damage") or 0) + int(p.get("spawn_character_count") or 0) * 100,
    )


def patch_projectile_spell(record: dict[str, Any], stat: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    if stat.get("damage") is not None:
        level11(record, "damage_per_level", "damage", int(stat["damage"]))
        fields.append("damage")
    if stat.get("radius_tiles") is not None:
        record["radius"] = int(round(float(stat["radius_tiles"]) * 1000))
        fields.append("radius")
    if stat.get("projectile_speed") is not None:
        record["speed"] = int(stat["projectile_speed"])
        fields.append("speed")
    attacks = set(stat.get("attacks") or [])
    if attacks:
        record["aoe_to_ground"] = bool("ground" in attacks)
        record["aoe_to_air"] = bool("air" in attacks)
        fields.append("targets")
    if stat.get("damage") and stat.get("crown_tower_damage") is not None:
        ratio = float(stat["crown_tower_damage"]) / float(stat["damage"])
        record["crown_tower_damage_percent"] = int(round((ratio - 1.0) * 100))
        fields.append("crown_tower_damage")
    return fields


def add_runtime_stub(
    key: str,
    stat: dict[str, Any],
    characters: list[dict[str, Any]],
    buildings: list[dict[str, Any]],
    spells: list[dict[str, Any]],
    synthetic_id: int,
) -> tuple[dict[str, Any], str]:
    ck = card_key(key)
    display = stat.get("display", key)
    sk = str(stat.get("sc_key") or sc_key(display))
    kind = stat.get("kind")

    if kind == "spell":
        # Missing current zone spells (e.g. Vines/Void) get a neutral timed-zone
        # schema template. Projectile spells are detected before this function.
        record = clone_template(
            spells,
            ["poison", "Poison", "zap", "Zap"],
            predicate=lambda r: int(r.get("radius") or 0) > 0,
        )
        record.update(key=ck, name=sk, name_en=display, sc_key=sk, id=int(stat.get("official_id") or synthetic_id), elixir=int(stat.get("elixir") or 0))
        patch_spell(record, stat, generated=True)
        upsert_by_key(spells, record)
        return record, "spell"

    if kind == "building":
        record = clone_template(
            buildings,
            ["cannon", "Cannon"],
            predicate=lambda r: int(r.get("hitpoints") or 0) > 0,
        )
        record.update(key=ck, name=sk, name_en=display, sc_key=sk, id=int(stat.get("official_id") or synthetic_id), elixir=int(stat.get("elixir") or 0))
        patch_character(record, stat, generated=True)
        upsert_by_key(buildings, record)
        return record, "building"

    # Troop template is chosen to preserve the broad movement/targeting family.
    attacks = set(stat.get("attacks") or [])
    if stat.get("movement") == "air":
        candidates = ["MegaMinion", "megaminion", "BabyDragon", "Minion", "FlyingMachine"]
        predicate = lambda r: int(r.get("flying_height") or 0) > 0 and int(r.get("hitpoints") or 0) > 0
    elif attacks == {"buildings"}:
        candidates = ["Giant", "giant", "HogRider"]
        predicate = lambda r: bool(r.get("target_only_buildings")) and int(r.get("hitpoints") or 0) > 0
    elif float(stat.get("range_tiles") or 0) >= 2.5:
        candidates = ["BlowdartGoblin", "Musketeer", "Archer"]
        predicate = lambda r: int(r.get("range") or 0) >= 2500 and int(r.get("hitpoints") or 0) > 0
    else:
        candidates = ["Knight", "Barbarian", "Goblins"]
        predicate = lambda r: int(r.get("hitpoints") or 0) > 0 and int(r.get("range") or 0) <= 2000
    record = clone_template(characters, candidates, predicate=predicate)
    record.update(key=ck, name=sk, name_en=display, sc_key=sk, id=int(stat.get("official_id") or synthetic_id), elixir=int(stat.get("elixir") or 0))
    # Do not inherit another card's unique mechanics into a generic stub.
    for special in (
        "starting_buff", "spawn_area_object", "death_spawn_character", "morph_character",
        "ability", "dash_damage", "dash_range", "charge_range", "kamikaze",
    ):
        if special in record:
            if isinstance(record[special], bool):
                record[special] = False
            elif isinstance(record[special], (int, float)):
                record[special] = 0
            else:
                record[special] = None
    patch_character(record, stat, generated=True)
    upsert_by_key(characters, record)
    return record, "character"


# Public values that describe a component/ability rather than the direct base
# entity should stay in the catalog until their dedicated runtime mechanic
# patch consumes them.
SPECIAL_DAMAGE_KEYS = {
    "goblin_curse", "suspicious_bush", "goblinstein", "little_prince",
    "spirit_empress", "void", "vines",
}

# Homogeneous multi-unit cards.  The pinned Rudy loader has fallback counts,
# but a direct card-key row in characters.json can bypass those fallbacks.
# Keep the public card count authoritative in the generated Tournament-11 data.
HOMOGENEOUS_MULTI_UNITS = {
    "archers": "archer",
    "barbarians": "barbarian",
    "bats": "bat",
    "elite_barbarians": "angrybarbarian",
    "goblins": "goblin",
    "guards": "skeletonwarrior",
    "minion_horde": "minion",
    "minions": "minion",
    "royal_hogs": "royalhog",
    "royal_recruits": "recruit",
    "skeleton_army": "skeleton",
    "skeleton_dragons": "skeletondragon",
    "skeletons": "skeleton",
    "spear_goblins": "speargoblin",
    "three_musketeers": "musketeer",
    "wall_breakers": "wallbreaker",
    "zappies": "minizapmachine",
}

MIXED_MULTI_UNITS = {
    # Current Goblin Gang: 3 melee Goblins + 3 Spear Goblins.
    "goblin_gang": ("goblin", 3, "speargoblin", 3),
    # Rascals: one Boy + two Girls.
    "rascals": ("rascalboy", 1, "rascalgirl", 2),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--catalog", default=str(Path(__file__).with_name("current_card_stats_2026_09.json")))
    args = ap.parse_args()

    data_dir = Path(args.data_dir).resolve()
    root = data_dir / "royaleapi"
    catalog = load(Path(args.catalog).resolve())
    if int(catalog["meta"]["level"]) != 11:
        raise SystemExit("current stat overlay expects a level-11 catalog")

    cards = load(root / "cards.json")
    characters = load(root / "cards_stats_characters.json")
    buildings = load(root / "cards_stats_building.json")
    spells = load(root / "cards_stats_spell.json")
    projectiles = load(root / "cards_stats_projectile.json")

    base = [(k, v) for k, v in catalog["cards"].items() if not v.get("evolution") and not v.get("hero")]
    manifest: dict[str, Any] = {
        "catalog_snapshot": catalog["meta"]["snapshot_date"],
        "catalog_entries": len(catalog["cards"]),
        "base_cards": len(base),
        "registry_created": [],
        "runtime_stubs_created": [],
        "runtime_records_patched": [],
        "catalog_only_special_fields": sorted(SPECIAL_DAMAGE_KEYS),
        "projectiles_patched": [],
        "unmatched": [],
    }

    for ordinal, (key, stat) in enumerate(base):
        synthetic_id = 99000000 + ordinal
        registry, registry_created = patch_registry(cards, key, stat, synthetic_id)
        if registry_created:
            manifest["registry_created"].append(key)

        selectors = (card_key(key), stat.get("display", ""), registry.get("sc_key", ""))
        kind = stat.get("kind")
        pools: list[tuple[str, list[dict[str, Any]]]]
        if kind == "building":
            pools = [("building", buildings), ("character", characters)]
        elif kind == "spell":
            pools = [("spell", spells)]
        else:
            pools = [("character", characters), ("building", buildings)]

        record = None
        pool_name = None
        for candidate_name, pool in pools:
            record = find_one(pool, *selectors)
            if record is not None:
                pool_name = candidate_name
                break

        # Rudy stores direct projectile spells (Fireball, Log, Arrows, Rocket,
        # etc.) in cards_stats_projectile.json rather than cards_stats_spell.json.
        if record is None and kind == "spell":
            projectile_spell = find_spell_projectile(projectiles, registry)
            if projectile_spell is not None:
                record = projectile_spell
                pool_name = "projectile_spell"

        generated = False
        if record is None:
            record, pool_name = add_runtime_stub(key, stat, characters, buildings, spells, synthetic_id)
            generated = True
            manifest["runtime_stubs_created"].append(key)

        # Existing special mechanics keep their direct damage semantics; all
        # other public fields are still synchronized.
        stat_for_runtime = dict(stat)
        if key in SPECIAL_DAMAGE_KEYS and not generated:
            stat_for_runtime.pop("damage", None)

        if pool_name == "spell":
            changed = patch_spell(record, stat_for_runtime, generated=generated)
        elif pool_name == "projectile_spell":
            changed = patch_projectile_spell(record, stat_for_runtime)
        else:
            changed = patch_character(record, stat_for_runtime, generated=generated)

        if pool_name == "character" and key in HOMOGENEOUS_MULTI_UNITS:
            public_count = int(stat.get("count") or 1)
            if public_count > 1:
                record["summon_number"] = public_count
                record["summon_character"] = HOMOGENEOUS_MULTI_UNITS[key]
                changed.extend(["summon_number", "summon_character"])

        if pool_name == "character" and key in MIXED_MULTI_UNITS:
            first_unit, first_count, second_unit, second_count = MIXED_MULTI_UNITS[key]
            record["summon_number"] = first_count
            record["summon_character"] = first_unit
            record["summon_character_second"] = second_unit
            record["summon_character_second_count"] = second_count
            changed.extend([
                "summon_number", "summon_character",
                "summon_character_second", "summon_character_second_count",
            ])

        # Synchronize a simple ranged attack projectile when the record exposes
        # one. This is safe for ordinary one-projectile attackers and is skipped
        # for known special mechanics.
        projectile_name = record.get("projectile")
        if projectile_name:
            projectile = find_one(projectiles, str(projectile_name))
            if projectile is not None:
                projectile_changes: list[str] = []
                if key not in SPECIAL_DAMAGE_KEYS and stat.get("damage") is not None:
                    level11(projectile, "damage_per_level", "damage", int(stat["damage"]))
                    projectile_changes.append("damage")
                if stat.get("projectile_speed") is not None:
                    projectile["speed"] = int(stat["projectile_speed"])
                    projectile_changes.append("speed")
                if stat.get("chain_range_tiles") is not None:
                    projectile["chained_hit_radius"] = int(round(float(stat["chain_range_tiles"]) * 1000))
                    projectile_changes.append("chain_range")
                if stat.get("chain_count") is not None:
                    projectile["chained_hit_count"] = int(stat["chain_count"])
                    projectile_changes.append("chain_count")
                if projectile_changes:
                    manifest["projectiles_patched"].append({
                        "card": key,
                        "projectile": projectile_name,
                        "fields": projectile_changes,
                    })

        manifest["runtime_records_patched"].append({
            "card": key,
            "pool": pool_name,
            "generated_stub": generated,
            "fields": changed,
        })

    save(root / "cards.json", cards)
    save(root / "cards_stats_characters.json", characters)
    save(root / "cards_stats_building.json", buildings)
    save(root / "cards_stats_spell.json", spells)
    save(root / "cards_stats_projectile.json", projectiles)
    save(data_dir / "CURRENT_CARD_STATS_MANIFEST.json", manifest)

    print(json.dumps({
        "status": "PASS",
        "snapshot": manifest["catalog_snapshot"],
        "base_cards": manifest["base_cards"],
        "registry_created": len(manifest["registry_created"]),
        "runtime_stubs_created": len(manifest["runtime_stubs_created"]),
        "runtime_records_patched": len(manifest["runtime_records_patched"]),
        "projectiles_patched": len(manifest["projectiles_patched"]),
        "stub_cards": manifest["runtime_stubs_created"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
