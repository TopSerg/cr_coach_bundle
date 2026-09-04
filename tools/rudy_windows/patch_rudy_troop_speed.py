#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
ENTITIES = ROOT / "entities.rs"


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


# After patch_rudy_arena_18x32.py Rudy uses 1000 internal units per tile and
# runs at 20 ticks/s. Clash Royale troop movement speed categories are raw
# values where one speed unit is 0.02 tiles/s:
#   45 = 0.9 tiles/s, 60 = 1.2, 90 = 1.8, 120 = 2.4.
# Therefore units/tick = raw_speed * 0.02 * 1000 / 20 = raw_speed.
#
# Keep the existing fallback for >120 because the same helper is also (improperly)
# reused by Rudy for projectile/special speeds, which have different source units.
# This patch deliberately corrects the standard troop movement categories only.
old_speed = """        s if s <= 45 => 30,   // Slow:     ~0.6 tiles/s @ 1000 units/tile
        s if s <= 60 => 50,   // Medium:   ~1.0 tiles/s @ 1000 units/tile
        s if s <= 90 => 75,   // Fast:     ~1.5 tiles/s @ 1000 units/tile
        s if s <= 120 => 100, // VeryFast: ~2.0 tiles/s @ 1000 units/tile
        s => (s * 50) / 100,  // Fallback scaled from the old 600-unit tile system"""

new_speed = """        s if s <= 45 => 45,   // Slow:     0.9 tiles/s = 45 units/tick
        s if s <= 60 => 60,   // Medium:   1.2 tiles/s = 60 units/tick
        s if s <= 90 => 90,   // Fast:     1.8 tiles/s = 90 units/tick
        s if s <= 120 => 120, // VeryFast: 2.4 tiles/s = 120 units/tick
        s => (s * 50) / 100,  // Preserve legacy fallback for non-troop/high raw speeds"""

replace_once(ENTITIES, old_speed, new_speed, "Clash Royale troop movement speed categories")

print("Rudy troop speed patched: 45/60/90/120 -> 0.9/1.2/1.8/2.4 tiles/s.")
