#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


gs = ROOT / "game_state.rs"
entities = ROOT / "entities.rs"
lib = ROOT / "lib.rs"

# CR arena geometry: 18 x 32 tiles, represented as 1000 internal units per tile.
replace_once(gs, "pub const ARENA_HALF_W: i32 = 8_400;", "pub const ARENA_HALF_W: i32 = 9_000;", "arena width 18 tiles")
replace_once(gs, "pub const ARENA_HALF_H: i32 = 15_400;", "pub const ARENA_HALF_H: i32 = 16_000;", "arena height 32 tiles")
replace_once(gs, "pub const RIVER_Y_MIN: i32 = -1_200;", "pub const RIVER_Y_MIN: i32 = -1_000;", "river lower edge")
replace_once(gs, "pub const RIVER_Y_MAX: i32 = 1_200;", "pub const RIVER_Y_MAX: i32 = 1_000;", "river upper edge")
replace_once(gs, "pub const TILE_SIZE: i32 = 600;", "pub const TILE_SIZE: i32 = 1_000;", "1000 units per tile")
replace_once(gs, "pub const BRIDGE_LEFT_X: i32 = -5_100;", "pub const BRIDGE_LEFT_X: i32 = -5_500;", "left bridge center")
replace_once(gs, "pub const BRIDGE_RIGHT_X: i32 = 5_100;", "pub const BRIDGE_RIGHT_X: i32 = 5_500;", "right bridge center")
replace_once(gs, "pub const BRIDGE_HALF_W: i32 = 1_200;", "pub const BRIDGE_HALF_W: i32 = 1_500;", "3-tile bridge width")
replace_once(gs, "pub const P1_PRINCESS_LEFT_POS: (i32, i32) = (-5_100, -10_200);", "pub const P1_PRINCESS_LEFT_POS: (i32, i32) = (-5_500, -9_500);", "P1 left princess center")
replace_once(gs, "pub const P1_PRINCESS_RIGHT_POS: (i32, i32) = (5_100, -10_200);", "pub const P1_PRINCESS_RIGHT_POS: (i32, i32) = (5_500, -9_500);", "P1 right princess center")
replace_once(gs, "pub const P2_PRINCESS_LEFT_POS: (i32, i32) = (-5_100, 10_200);", "pub const P2_PRINCESS_LEFT_POS: (i32, i32) = (-5_500, 9_500);", "P2 left princess center")
replace_once(gs, "pub const P2_PRINCESS_RIGHT_POS: (i32, i32) = (5_100, 10_200);", "pub const P2_PRINCESS_RIGHT_POS: (i32, i32) = (5_500, 9_500);", "P2 right princess center")

# The old movement table was calibrated to TILE_SIZE=600. Keep the same physical
# speed categories (0.6 / 1.0 / 1.5 / 2.0 tiles/s) in the new 1000-unit tile scale.
old_speed = """        s if s <= 45 => 18,   // Slow:     ~0.6 tiles/s
        s if s <= 60 => 30,   // Medium:   ~1.0 tiles/s
        s if s <= 90 => 45,   // Fast:     ~1.5 tiles/s
        s if s <= 120 => 60,  // VeryFast: ~2.0 tiles/s
        s => (s * 30) / 100,  // Fallback linear interpolation"""
new_speed = """        s if s <= 45 => 30,   // Slow:     ~0.6 tiles/s @ 1000 units/tile
        s if s <= 60 => 50,   // Medium:   ~1.0 tiles/s @ 1000 units/tile
        s if s <= 90 => 75,   // Fast:     ~1.5 tiles/s @ 1000 units/tile
        s if s <= 120 => 100, // VeryFast: ~2.0 tiles/s @ 1000 units/tile
        s => (s * 50) / 100,  // Fallback scaled from the old 600-unit tile system"""
replace_once(entities, old_speed, new_speed, "movement speed scale")

# Placement validation in lib.rs has a duplicate hard-coded tower table.
old_towers = """                (0, -13000, 1600),      // P1 King
                (-5100, -10200, 1300),   // P1 Princess Left
                (5100, -10200, 1300),    // P1 Princess Right
                (0, 13000, 1600),        // P2 King
                (-5100, 10200, 1300),    // P2 Princess Left
                (5100, 10200, 1300),     // P2 Princess Right"""
new_towers = """                (0, -13000, 1600),      // P1 King
                (-5500, -9500, 1300),    // P1 Princess Left
                (5500, -9500, 1300),     // P1 Princess Right
                (0, 13000, 1600),        // P2 King
                (-5500, 9500, 1300),     // P2 Princess Left
                (5500, 9500, 1300),      // P2 Princess Right"""
replace_once(lib, old_towers, new_towers, "placement tower geometry")

print("Rudy arena geometry patched to 18x32 tiles, 1000 internal units per tile.")
