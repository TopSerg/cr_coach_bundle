#!/usr/bin/env python3
"""Complete Crown Tower release semantics after projectile unification.

This patch is intentionally tower-class-wide, not card-specific:
  * attack range is evaluated body-gap (range + tower radius + target radius),
  * reload is advanced before readiness is sampled so N ticks means N ticks.

It is applied only after patch_rudy_tower_projectiles.py, so the extra reach and
exact cadence produce travelling projectiles rather than instant HP subtraction.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
combat = ROOT / "combat.rs"


def replace_once(old: str, new: str, label: str):
    text = combat.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    combat.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


replace_once(
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
    "tower target snapshots carry body radius",
)

replace_once(
    """    for player_team in [Team::Player1, Team::Player2] {
        let enemy_team = player_team.opponent();

        // Keep accepted range/reload semantics for this step. Only damage delivery
        // changes from instant HP subtraction to release -> projectile -> impact.
        let tower_infos: Vec<(i32, i32, i32, i32, bool, u8)> = {""",
    """    for player_team in [Team::Player1, Team::Player2] {
        // Reload first, then sample readiness. This matches the generic combat
        // convention and removes the historical extra 50 ms transition tick.
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

        // (x, y, range, damage, physical_radius, ready, tower_id)
        let tower_infos: Vec<(i32, i32, i32, i32, i64, bool, u8)> = {""",
    "tower exact reload update order",
)

replace_once(
    """                    PRINCESS_TOWER_DMG,
                    player.princess_left.attack_cooldown <= 0,
                    0u8,""",
    """                    PRINCESS_TOWER_DMG,
                    1_000i64,
                    player.princess_left.attack_cooldown <= 0,
                    0u8,""",
    "left Princess Tower body radius",
)
replace_once(
    """                    PRINCESS_TOWER_DMG,
                    player.princess_right.attack_cooldown <= 0,
                    1u8,""",
    """                    PRINCESS_TOWER_DMG,
                    1_000i64,
                    player.princess_right.attack_cooldown <= 0,
                    1u8,""",
    "right Princess Tower body radius",
)
replace_once(
    """                    KING_TOWER_DMG,
                    player.king.attack_cooldown <= 0,
                    2u8,""",
    """                    KING_TOWER_DMG,
                    1_400i64,
                    player.king.attack_cooldown <= 0,
                    2u8,""",
    "King Tower body radius",
)

replace_once(
    """        for (tx, ty, range, damage, ready, tower_id) in &tower_infos {
            if !ready {
                continue;
            }
            let range_sq = range_squared(*range);
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
    """        for (tx, ty, range, damage, tower_radius, ready, tower_id) in &tower_infos {
            if !ready {
                continue;
            }
            let mut best_idx: Option<usize> = None;
            let mut best_dist = i64::MAX;

            for (_, team, ex, ey, target_radius, _, alive, entity_idx) in &targets {
                if !alive || *team != enemy_team {
                    continue;
                }
                let dx = (*tx - ex) as i64;
                let dy = (*ty - ey) as i64;
                let dist = dx * dx + dy * dy;
                let effective_range = *range as i64 + *tower_radius + *target_radius;
                if dist <= effective_range * effective_range && dist < best_dist {
                    best_dist = dist;
                    best_idx = Some(*entity_idx);
                }
            }""",
    "Crown Tower body-gap attack range",
)

replace_once(
    """        // Preserve baseline cooldown update order for now.
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
""",
    "",
    "remove post-readiness tower cooldown decrement",
)

# King activation scans the same widened target tuple, but activation radius is
# a separate gameplay rule and intentionally remains center-distance based.
replace_once(
    "for (_, team, ex, ey, _, alive, _) in &targets {",
    "for (_, team, ex, ey, _, _, alive, _) in &targets {",
    "King activation tuple after radius snapshot",
)

print("Rudy patched: Crown Towers use body-gap range + exact release cadence on shared projectiles.")
