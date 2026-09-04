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
combat = ROOT / "combat.rs"

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

# Rudy's attack cycle has an implicit one-tick transition from Backswing -> Idle
# before a new Windup can begin. Without compensating for it, every troop attacks
# exactly 50 ms slower than the data hit_speed (Hog: 1.65 s instead of 1.60 s).
# Store one fewer recovery tick so the full hit-to-hit period stays equal to the
# source hit_speed at 20 TPS. The transition tick itself supplies the missing tick.
old_backswing = """                backswing_ticks: {
                    let bs = stats.hit_speed - stats.load_time;
                    if bs > 0 { ms_to_ticks(bs) } else { 0 }
                },"""
new_backswing = """                backswing_ticks: {
                    let bs = stats.hit_speed - stats.load_time;
                    if bs > 0 { ms_to_ticks(bs).saturating_sub(1) } else { 0 }
                },"""
replace_once(entities, old_backswing, new_backswing, "troop attack-cycle 1-tick correction")

# ---------------------------------------------------------------------------
# Attack/sight geometry: Clash Royale ranges are edge-to-edge, not center-to-center.
# Rudy previously compared distance between entity centers against range alone.
# Keep collision radius on target snapshots so movement and combat can use:
#   effective_range = card_range + attacker_radius + target_radius
# This is especially important for a Hog attacking a Princess Tower.
# ---------------------------------------------------------------------------
replace_once(
    combat,
    """    pub targetable: bool,
    pub is_invisible: bool,
}""",
    """    pub targetable: bool,
    pub is_invisible: bool,
    /// Physical radius used for edge-to-edge range checks.
    pub collision_radius: i32,
}""",
    "target snapshot collision radius field",
)

replace_once(
    combat,
    """            targetable: e.is_targetable(),
            is_invisible: e.is_invisible(),
        })""",
    """            targetable: e.is_targetable(),
            is_invisible: e.is_invisible(),
            collision_radius: e.collision_radius.max(0),
        })""",
    "entity target collision radius",
)

replace_once(
    combat,
    """            targetable: !king_blocked,
            is_invisible: false,
        });""",
    """            targetable: !king_blocked,
            is_invisible: false,
            // Hidden CR collision radii: Princess Tower=1.0 tile, King=1.4 tiles.
            collision_radius: if *tid == P1_KING_TOWER_ID || *tid == P2_KING_TOWER_ID {
                1_400
            } else {
                1_000
            },
        });""",
    "tower target collision radius",
)

# Movement needs the target radius to stop at edge-to-edge attack distance.
old_target_pos = """        let (target_x, target_y) = if let Some(tid) = entity_target {
            if let Some(snap) = snapshots.iter().find(|s| s.id == tid) {
                (snap.x, snap.y)
            } else {
                default_target_for_troop(state, team, troop_x)
            }
        } else {
            default_target_for_troop(state, team, troop_x)
        };"""
new_target_pos = """        let (target_x, target_y, target_radius) = if let Some(tid) = entity_target {
            if let Some(snap) = snapshots.iter().find(|s| s.id == tid) {
                (snap.x, snap.y, snap.collision_radius)
            } else {
                let (x, y) = default_target_for_troop(state, team, troop_x);
                (x, y, 1_000) // Default target is normally a Princess Tower.
            }
        } else {
            let (x, y) = default_target_for_troop(state, team, troop_x);
            (x, y, 1_000)
        };"""
replace_once(combat, old_target_pos, new_target_pos, "movement target radius")

old_move_range = """        // Already in attack range of ultimate target? Don't move.
        {
            let dx = (target_x - my_x) as i64;
            let dy = (target_y - my_y) as i64;
            if dx * dx + dy * dy <= range_sq {
                continue;
            }
        }"""
new_move_range = """        // Already in attack range of ultimate target? Don't move.
        // CR ranges are measured edge-to-edge, so include both collision radii.
        {
            let dx = (target_x - my_x) as i64;
            let dy = (target_y - my_y) as i64;
            let base_range = (range_sq as f64).sqrt() as i64;
            let effective_range = base_range
                + my_radius.max(0) as i64
                + target_radius.max(0) as i64;
            if dx * dx + dy * dy <= effective_range * effective_range {
                continue;
            }
        }"""
replace_once(combat, old_move_range, new_move_range, "edge-to-edge movement stop range")

# Combat needs the same edge-to-edge distance. Capture attacker radius before the
# mutable borrow of entity.kind, then derive one effective range for the target.
replace_once(
    combat,
    """        let entity = &mut state.entities[ei];
        match &mut entity.kind {""",
    """        let entity = &mut state.entities[ei];
        let attacker_collision_radius = entity.collision_radius.max(0) as i64;
        match &mut entity.kind {""",
    "combat attacker collision radius",
)

replace_once(
    combat,
    """                let dx = (entity.x - target_snap.x) as i64;
                let dy = (entity.y - target_snap.y) as i64;
                let dist_sq = dx * dx + dy * dy;

                // Inferno Dragon ramp:""",
    """                let dx = (entity.x - target_snap.x) as i64;
                let dy = (entity.y - target_snap.y) as i64;
                let dist_sq = dx * dx + dy * dy;
                let base_attack_range = (troop.range_sq as f64).sqrt() as i64;
                let effective_attack_range = base_attack_range
                    + attacker_collision_radius
                    + target_snap.collision_radius.max(0) as i64;
                let effective_attack_range_sq = effective_attack_range * effective_attack_range;

                // Inferno Dragon ramp:""",
    "effective troop attack range",
)

# These are the normal troop range checks in the attack state machine.
replace_once(
    combat,
    """                    if dist_sq <= troop.range_sq {
                        troop.ramp_ticks += 1;""",
    """                    if dist_sq <= effective_attack_range_sq {
                        troop.ramp_ticks += 1;""",
    "edge range inferno ramp",
)
replace_once(
    combat,
    "if troop.kamikaze && dist_sq <= troop.range_sq && troop.attack_cooldown <= 0 {",
    "if troop.kamikaze && dist_sq <= effective_attack_range_sq && troop.attack_cooldown <= 0 {",
    "edge range kamikaze",
)
replace_once(
    combat,
    "if dist_sq <= troop.range_sq && troop.attack_cooldown <= 0 {",
    "if dist_sq <= effective_attack_range_sq && troop.attack_cooldown <= 0 {",
    "edge range normal troop attack",
)
replace_once(
    combat,
    "let too_far = dist_sq > troop.range_sq * 4; // 2x range distance",
    "let too_far = dist_sq > effective_attack_range_sq * 4; // 2x effective edge range",
    "edge range windup leash",
)

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

print("Rudy patched: 18x32 arena, 1000 units/tile, edge-to-edge combat range, exact troop attack cadence.")
