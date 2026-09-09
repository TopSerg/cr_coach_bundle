#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def one(records: list[dict], field: str, value: str) -> dict:
    matches = [r for r in records if str(r.get(field) or "") == value]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {field}={value!r}, found {len(matches)}")
    return matches[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--level", type=int, default=11)
    ap.add_argument("--damage", type=int, required=True)
    ap.add_argument("--building-name", default="Cannon")
    ap.add_argument("--projectile-name", default="TowerCannonball")
    args = ap.parse_args()

    data = Path(args.data_dir)
    bpath = data / "royaleapi" / "cards_stats_building.json"
    ppath = data / "royaleapi" / "cards_stats_projectile.json"

    buildings = load(bpath)
    projectiles = load(ppath)

    building = one(buildings, "name", args.building_name)
    projectile = one(projectiles, "name", args.projectile_name)

    # Rudy's loader uses building.damage == 0 as the data-driven signal that the
    # building's primary attack damage belongs to its projectile. Leaving damage
    # non-zero makes CharacterStats::is_ranged() false even if projectile is set.
    before_building_damage = building.get("damage")
    building["damage"] = 0

    before_projectile_damage = projectile.get("damage")
    projectile["damage"] = args.damage

    idx = args.level - 1
    arr = projectile.get("damage_per_level")
    if not isinstance(arr, list):
        raise RuntimeError(f"{args.projectile_name}.damage_per_level is not a list")
    if idx >= len(arr):
        raise RuntimeError(
            f"{args.projectile_name}.damage_per_level has {len(arr)} levels, requested {args.level}"
        )
    before_level_damage = arr[idx]
    arr[idx] = args.damage

    save(bpath, buildings)
    save(ppath, projectiles)

    print(
        f"ranged projectile overlay: {args.building_name}.damage "
        f"{before_building_damage!r}->0; {args.projectile_name}.damage "
        f"{before_projectile_damage!r}->{args.damage}; level {args.level} "
        f"{before_level_damage!r}->{args.damage}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
