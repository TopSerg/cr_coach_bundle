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
        cards.append(record)
    record["key"] = ck
    record["name"] = stat.get("display", key)
    record["sc_key"] = sc_key(stat.get("display", key))
    record["elixir"] = int(stat.get("elixir") or record.get("elixir") or 0)
    record["rarity"] = str(stat.get("rarity") or record.get("rarity") or "").title()
    record["type"] = str(stat.get("kind") or record.get("type") or "").title()
    if stat.get("kind") in {"troop", "building"}:
        record["summon_character"] = record["sc_key"]
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


def clone_template(records: list[dict[str, Any]], candidates: list[str]) -> dict[str, Any]:
    for candidate in candidates:
        found = find_one(records, candidate)
        if found is not None:
            return copy.deepcopy(found)
    raise RuntimeError(f"no template found: {candidates}")


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
    sk = sc_key(display)
    kind = stat.get("kind")

    if kind == "spell":
        record = clone_template(spells, ["fireball", "Fireball"])
        record.update(key=ck, name=sk, name_en=display, sc_key=sk, id=int(stat.get("official_id") or synthetic_id), elixir=int(stat.get("elixir") or 0))
        patch_spell(record, stat, generated=True)
        upsert_by_key(spells, record)
        return record, "spell"

    if kind == "building":
        record = clone_template(buildings, ["cannon", "Cannon"])
        record.update(key=ck, name=sk, name_en=display, sc_key=sk, id=int(stat.get("official_id") or synthetic_id), elixir=int(stat.get("elixir") or 0))
        patch_character(record, stat, generated=True)
        upsert_by_key(buildings, record)
        return record, "building"

    # Troop template is chosen to preserve the broad movement/targeting family.
    attacks = set(stat.get("attacks") or [])
    if stat.get("movement") == "air":
        candidates = ["FlyingMachine", "flying-machine", "Minions"]
    elif attacks == {"buildings"}:
        candidates = ["Giant", "giant"]
    elif float(stat.get("range_tiles") or 0) >= 2.5:
        candidates = ["BlowdartGoblin", "dart-goblin", "Musketeer"]
    else:
        candidates = ["Knight", "knight"]
    record = clone_template(characters, candidates)
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
        else:
            changed = patch_character(record, stat_for_runtime, generated=generated)

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
