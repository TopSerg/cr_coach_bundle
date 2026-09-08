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


combat = ROOT / "combat.rs"

# ---------------------------------------------------------------------------
# One combat geometry primitive for troops, buildings and crown towers.
#
# Public CR ranges describe the gap between physical bodies, while Rudy stores
# entity positions at their centres.  Every normal attack-range check should use
# the same conversion instead of reimplementing centre-distance comparisons in
# each entity subsystem.
# ---------------------------------------------------------------------------
marker = """// =========================================================================
// Snapshot types for borrow-safe targeting
// =========================================================================
"""
helper = """// =========================================================================
// Shared combat geometry
// =========================================================================

/// Convert a centre-to-centre squared base range into the corresponding
/// edge-to-edge attack envelope by adding the physical radii of both bodies.
/// This is the single normal-range primitive used by troops, buildings and
/// crown towers.  Card-specific mechanics may still layer special rules on top.
#[inline]
fn effective_edge_range_sq(
    base_range_sq: i64,
    attacker_collision_radius: i64,
    target_collision_radius: i64,
) -> i64 {
    let base_range = (base_range_sq.max(0) as f64).sqrt() as i64;
    let effective_range = base_range
        + attacker_collision_radius.max(0)
        + target_collision_radius.max(0);
    effective_range * effective_range
}

// =========================================================================
// Snapshot types for borrow-safe targeting
// =========================================================================
"""
replace_once(combat, marker, helper, "shared edge-to-edge combat range primitive")

# Reuse the primitive in troop movement instead of maintaining a second copy of
# the same formula.
replace_once(
    combat,
    """            let base_range = (range_sq as f64).sqrt() as i64;
            let effective_range = base_range
                + my_radius.max(0) as i64
                + target_radius.max(0) as i64;
            if dx * dx + dy * dy <= effective_range * effective_range {
                continue;
            }""",
    """            let effective_range_sq = effective_edge_range_sq(
                range_sq,
                my_radius.max(0) as i64,
                target_radius.max(0) as i64,
            );
            if dx * dx + dy * dy <= effective_range_sq {
                continue;
            }""",
    "troop movement shared range primitive",
)

# Reuse the same primitive in troop combat.
replace_once(
    combat,
    """                let base_attack_range = (troop.range_sq as f64).sqrt() as i64;
                let effective_attack_range = base_attack_range
                    + attacker_collision_radius
                    + target_snap.collision_radius.max(0) as i64;
                let effective_attack_range_sq = effective_attack_range * effective_attack_range;""",
    """                let effective_attack_range_sq = effective_edge_range_sq(
                    troop.range_sq,
                    attacker_collision_radius,
                    target_snap.collision_radius.max(0) as i64,
                );""",
    "troop combat shared range primitive",
)

# Buildings previously used raw centre-to-centre range while troops used the
# patched edge geometry.  Compute the same envelope once for the building branch
# and use it for normal fire + inferno beam continuity.
replace_once(
    combat,
    """                let dx = (entity.x - target_snap.x) as i64;
                let dy = (entity.y - target_snap.y) as i64;
                let dist_sq = dx * dx + dy * dy;

                // Always tick down cooldown (scaled by hitspeed buff)""",
    """                let dx = (entity.x - target_snap.x) as i64;
                let dy = (entity.y - target_snap.y) as i64;
                let dist_sq = dx * dx + dy * dy;
                let effective_building_range_sq = effective_edge_range_sq(
                    bld.range_sq,
                    attacker_collision_radius,
                    target_snap.collision_radius.max(0) as i64,
                );

                // Always tick down cooldown (scaled by hitspeed buff)""",
    "building shared range envelope",
)
replace_once(
    combat,
    """                    if dist_sq <= bld.range_sq {
                        bld.ramp_ticks += 1;
                    } else {
                        // Beam broken — target out of range, reset ramp
                        bld.ramp_ticks = 0;
                    }
                }

                if dist_sq <= bld.range_sq && dist_sq >= bld.min_range_sq && bld.attack_cooldown <= 0 {""",
    """                    if dist_sq <= effective_building_range_sq {
                        bld.ramp_ticks += 1;
                    } else {
                        // Beam broken — target out of range, reset ramp
                        bld.ramp_ticks = 0;
                    }
                }

                if dist_sq <= effective_building_range_sq && dist_sq >= bld.min_range_sq && bld.attack_cooldown <= 0 {""",
    "building attack uses shared edge range",
)

# Crown towers used a completely separate centre-distance implementation.  Keep
# their physical size as data of the tower body (Princess=1.0 tile, King=1.4),
# but route the actual range test through the same primitive as every entity.
replace_once(
    combat,
    """    let targets: Vec<(EntityId, Team, i32, i32, bool, bool, usize)> = state
        .entities
        .iter()
        .enumerate()
        .filter(|(_, e)| e.is_targetable() && (e.is_troop() || e.is_building()))
        .map(|(idx, e)| (e.id, e.team, e.x, e.y, e.is_flying(), e.alive, idx))
        .collect();""",
    """    let targets: Vec<(EntityId, Team, i32, i32, i64, bool, bool, usize)> = state
        .entities
        .iter()
        .enumerate()
        .filter(|(_, e)| e.is_targetable() && (e.is_troop() || e.is_building()))
        .map(|(idx, e)| (
            e.id,
            e.team,
            e.x,
            e.y,
            e.collision_radius.max(0) as i64,
            e.is_flying(),
            e.alive,
            idx,
        ))
        .collect();""",
    "tower target snapshots carry collision radius",
)

replace_once(
    combat,
    """        // Extract tower info: (x, y, range, damage, ready, tower_id)
        let tower_infos: Vec<(i32, i32, i32, i32, bool, u8)> = {
            let player = state.player(player_team);
            let mut infos = Vec::new();

            if player.princess_left.alive {
                infos.push((
                    player.princess_left.pos.0,
                    player.princess_left.pos.1,
                    PRINCESS_TOWER_RANGE,
                    PRINCESS_TOWER_DMG,
                    player.princess_left.attack_cooldown <= 0,
                    0u8, // princess_left
                ));
            }
            if player.princess_right.alive {
                infos.push((
                    player.princess_right.pos.0,
                    player.princess_right.pos.1,
                    PRINCESS_TOWER_RANGE,
                    PRINCESS_TOWER_DMG,
                    player.princess_right.attack_cooldown <= 0,
                    1u8, // princess_right
                ));
            }
            if player.king.alive && player.king.activated {
                infos.push((
                    player.king.pos.0,
                    player.king.pos.1,
                    KING_TOWER_RANGE,
                    KING_TOWER_DMG,
                    player.king.attack_cooldown <= 0,
                    2u8, // king
                ));
            }
            infos
        };

        for (tx, ty, range, damage, ready, tower_id) in &tower_infos {""",
    """        // Extract tower info: (x, y, range, damage, collision_radius, ready, tower_id)
        let tower_infos: Vec<(i32, i32, i32, i32, i64, bool, u8)> = {
            let player = state.player(player_team);
            let mut infos = Vec::new();

            if player.princess_left.alive {
                infos.push((
                    player.princess_left.pos.0,
                    player.princess_left.pos.1,
                    PRINCESS_TOWER_RANGE,
                    PRINCESS_TOWER_DMG,
                    1_000i64,
                    player.princess_left.attack_cooldown <= 0,
                    0u8, // princess_left
                ));
            }
            if player.princess_right.alive {
                infos.push((
                    player.princess_right.pos.0,
                    player.princess_right.pos.1,
                    PRINCESS_TOWER_RANGE,
                    PRINCESS_TOWER_DMG,
                    1_000i64,
                    player.princess_right.attack_cooldown <= 0,
                    1u8, // princess_right
                ));
            }
            if player.king.alive && player.king.activated {
                infos.push((
                    player.king.pos.0,
                    player.king.pos.1,
                    KING_TOWER_RANGE,
                    KING_TOWER_DMG,
                    1_400i64,
                    player.king.attack_cooldown <= 0,
                    2u8, // king
                ));
            }
            infos
        };

        for (tx, ty, range, damage, tower_radius, ready, tower_id) in &tower_infos {""",
    "tower physical radius in common range model",
)

replace_once(
    combat,
    """            let range_sq = range_squared(*range);
            let mut best_idx: Option<usize> = None;
            let mut best_dist = i64::MAX;

            for (_, team, ex, ey, _, alive, entity_idx) in &targets {
                if !alive || *team != enemy_team {
                    continue;
                }
                let dx = (*tx - ex) as i64;
                let dy = (*ty - ey) as i64;
                let dist = dx * dx + dy * dy;
                if dist <= range_sq && dist < best_dist {
                    best_dist = dist;
                    best_idx = Some(*entity_idx);
                }
            }""",
    """            let base_range_sq = range_squared(*range);
            let mut best_idx: Option<usize> = None;
            let mut best_dist = i64::MAX;

            for (_, team, ex, ey, target_radius, _, alive, entity_idx) in &targets {
                if !alive || *team != enemy_team {
                    continue;
                }
                let dx = (*tx - ex) as i64;
                let dy = (*ty - ey) as i64;
                let dist = dx * dx + dy * dy;
                let effective_range_sq = effective_edge_range_sq(
                    base_range_sq,
                    *tower_radius,
                    *target_radius,
                );
                if dist <= effective_range_sq && dist < best_dist {
                    best_dist = dist;
                    best_idx = Some(*entity_idx);
                }
            }""",
    "crown tower attack uses shared edge range",
)

# Tower cooldowns were checked for readiness and only then decremented, so a
# nominal 16-tick/0.80s period actually fired every 17 ticks/0.85s.  Make the
# update order the same as attacking buildings: decrement reload first, then
# evaluate whether an attack may start this tick.
replace_once(
    combat,
    """    for player_team in [Team::Player1, Team::Player2] {
        let enemy_team = player_team.opponent();

        // Extract tower info: (x, y, range, damage, collision_radius, ready, tower_id)""",
    """    for player_team in [Team::Player1, Team::Player2] {
        // Advance reload before readiness is sampled.  This makes a configured
        // N-tick Hit Speed produce an exact N-tick release-to-release period.
        {
            let player = state.player_mut(player_team);
            if player.princess_left.alive && player.princess_left.attack_cooldown > 0 {
                player.princess_left.attack_cooldown -= 1;
            }
            if player.princess_right.alive && player.princess_right.attack_cooldown > 0 {
                player.princess_right.attack_cooldown -= 1;
            }
            if player.king.alive && player.king.activated && player.king.attack_cooldown > 0 {
                player.king.attack_cooldown -= 1;
            }
        }

        let enemy_team = player_team.opponent();

        // Extract tower info: (x, y, range, damage, collision_radius, ready, tower_id)""",
    "tower exact attack-cycle update order",
)

replace_once(
    combat,
    """        // Tick all tower cooldowns (independent of whether they fired)
        let player = state.player_mut(player_team);
        if player.princess_left.alive {
            if player.princess_left.attack_cooldown > 0 {
                player.princess_left.attack_cooldown -= 1;
            }
        }
        if player.princess_right.alive {
            if player.princess_right.attack_cooldown > 0 {
                player.princess_right.attack_cooldown -= 1;
            }
        }
        if player.king.alive && player.king.activated {
            if player.king.attack_cooldown > 0 {
                player.king.attack_cooldown -= 1;
            }
        }
""",
    "",
    "remove post-readiness tower cooldown tick",
)

# The tower target tuple gained a collision-radius field; update the King
# activation scan destructuring.  King activation itself is a separate gameplay
# radius, not a normal attack-range check, so it intentionally remains distinct.
replace_once(
    combat,
    "for (_, team, ex, ey, _, alive, _) in &targets {",
    "for (_, team, ex, ey, _, _, alive, _) in &targets {",
    "king activation tuple with target radius",
)

print("Rudy patched: unified edge-to-edge combat range for troops/buildings/towers and exact tower attack cadence.")
