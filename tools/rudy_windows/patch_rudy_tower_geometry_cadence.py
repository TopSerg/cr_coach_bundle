#!/usr/bin/env python3
"""Complete Crown Tower attack semantics after projectile unification.

This patch is tower-class-wide, not card-specific. It fixes three shared
mechanics together:
  * body-gap attack geometry for Crown Towers;
  * first-hit load starts when a tower ACQUIRES a target, not at match start;
  * regular reload uses exactly TOWER_HIT_SPEED ticks between releases.

It is applied after patch_rudy_tower_projectiles.py, so a completed attack
releases a normal Projectile entity and all flight/impact physics stay in the
shared ranged-attack pipeline.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
combat = ROOT / "combat.rs"
game_state = ROOT / "game_state.rs"


def replace_exact(path: Path, old: str, new: str, label: str, expected: int = 1):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{label}: expected {expected} match(es) in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched {label}")


# ---------------------------------------------------------------------------
# TowerState: remember the currently acquired target.
# ---------------------------------------------------------------------------
replace_exact(
    game_state,
    """    pub attack_cooldown: i32, // Ticks until next attack
    /// Hitspeed multiplier from active spell zones (Rage on tower).""",
    """    pub attack_cooldown: i32, // Ticks until next projectile release
    /// Target currently tracked by this tower. None means idle/no target.
    /// First-hit load is armed when this changes from None/another entity.
    pub attack_target: Option<EntityId>,
    /// Hitspeed multiplier from active spell zones (Rage on tower).""",
    "TowerState attack_target",
)

replace_exact(
    game_state,
    """            attack_cooldown: TOWER_LOAD_FIRST_HIT,
            rage_hitspeed: 100, // No buff active — normal speed""",
    """            attack_cooldown: TOWER_LOAD_FIRST_HIT,
            attack_target: None,
            rage_hitspeed: 100, // No buff active — normal speed""",
    "TowerState constructors initialise attack_target",
    expected=2,
)

# Keep tower physical size separate from attack range. These are global tower
# geometry constants, not per-opponent/card adjustments.
replace_exact(
    game_state,
    """/// Princess tower sight range.
pub const PRINCESS_TOWER_RANGE: i32 = 7_500;
/// King tower attack range.
pub const KING_TOWER_RANGE: i32 = 7_000;""",
    """/// Princess tower sight/attack range from the Crown Tower centre/body model.
pub const PRINCESS_TOWER_RANGE: i32 = 7_500;
/// King tower attack range.
pub const KING_TOWER_RANGE: i32 = 7_000;
/// Physical collision/body radius used only for edge-to-edge combat geometry.
pub const PRINCESS_TOWER_COLLISION_RADIUS: i32 = 1_000;
pub const KING_TOWER_COLLISION_RADIUS: i32 = 1_400;""",
    "Crown Tower physical radii",
)

# ---------------------------------------------------------------------------
# tick_towers: add target body radius to the snapshot.
# ---------------------------------------------------------------------------
replace_exact(
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
    "tower target snapshots carry body radius",
)

# Tower info no longer snapshots a stale "ready" boolean. Readiness is part of
# the per-tower attack state and is advanced only while a target is tracked.
replace_exact(
    combat,
    """        // Keep accepted range/reload semantics for this step. Only damage delivery
        // changes from instant HP subtraction to release -> projectile -> impact.
        let tower_infos: Vec<(i32, i32, i32, i32, bool, u8)> = {""",
    """        // (x, y, attack_range, damage, physical_radius, tower_id)
        // Cooldown/first-hit state stays in TowerState and is NOT advanced while idle.
        let tower_infos: Vec<(i32, i32, i32, i32, i64, u8)> = {""",
    "tower info uses attack state instead of stale ready flag",
)

replace_exact(
    combat,
    """                    PRINCESS_TOWER_DMG,
                    player.princess_left.attack_cooldown <= 0,
                    0u8,""",
    """                    PRINCESS_TOWER_DMG,
                    PRINCESS_TOWER_COLLISION_RADIUS as i64,
                    0u8,""",
    "left Princess Tower physical radius",
)
replace_exact(
    combat,
    """                    PRINCESS_TOWER_DMG,
                    player.princess_right.attack_cooldown <= 0,
                    1u8,""",
    """                    PRINCESS_TOWER_DMG,
                    PRINCESS_TOWER_COLLISION_RADIUS as i64,
                    1u8,""",
    "right Princess Tower physical radius",
)
replace_exact(
    combat,
    """                    KING_TOWER_DMG,
                    player.king.attack_cooldown <= 0,
                    2u8,""",
    """                    KING_TOWER_DMG,
                    KING_TOWER_COLLISION_RADIUS as i64,
                    2u8,""",
    "King Tower physical radius",
)

# Replace target selection + attack release gating. Target acquisition always
# runs, even while the tower is loading/reloading. A new target arms the 0.4 s
# first-hit timer. A stable target counts down to release; regular reload is
# reset later by the existing projectile-release block.
replace_exact(
    combat,
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
            }

            if let Some(idx) = best_idx {
                let target = &state.entities[idx];
                tower_attacks.push(TowerAttack {
                    target_id: target.id,
                    target_x: target.x,
                    target_y: target.y,
                    from_x: *tx,
                    from_y: *ty,
                    damage: *damage,
                    team: player_team,
                    tower_id: *tower_id,
                });
            }
        }

        // Preserve baseline cooldown update order for now.
        let player = state.player_mut(player_team);
        if player.princess_left.alive && player.princess_left.attack_cooldown > 0 {
            player.princess_left.attack_cooldown -= 1;
        }
        if player.princess_right.alive && player.princess_right.attack_cooldown > 0 {
            player.princess_right.attack_cooldown -= 1;
        }
        if player.king.alive && player.king.activated && player.king.attack_cooldown > 0 {
            player.king.attack_cooldown -= 1;
        }""",
    """        for (tx, ty, range, damage, tower_radius, tower_id) in &tower_infos {
            let mut best_idx: Option<usize> = None;
            let mut best_dist = i64::MAX;

            for (_, team, ex, ey, target_radius, _, alive, entity_idx) in &targets {
                if !alive || *team != enemy_team {
                    continue;
                }
                let dx = (*tx - ex) as i64;
                let dy = (*ty - ey) as i64;
                let center_dist_sq = dx * dx + dy * dy;
                let effective_range = *range as i64 + *tower_radius + *target_radius;
                if center_dist_sq <= effective_range * effective_range && center_dist_sq < best_dist {
                    best_dist = center_dist_sq;
                    best_idx = Some(*entity_idx);
                }
            }

            // Snapshot target data before borrowing the tower mutably.
            let best_target = best_idx.map(|idx| {
                let target = &state.entities[idx];
                (target.id, target.x, target.y)
            });

            let mut release = false;
            {
                let player = state.player_mut(player_team);
                let tower = match *tower_id {
                    0 => &mut player.princess_left,
                    1 => &mut player.princess_right,
                    2 => &mut player.king,
                    _ => continue,
                };

                match best_target {
                    None => {
                        // Idle towers do not consume their future first-hit load.
                        tower.attack_target = None;
                        tower.attack_cooldown = TOWER_LOAD_FIRST_HIT;
                    }
                    Some((target_id, _, _)) if tower.attack_target != Some(target_id) => {
                        // New acquisition / retarget: start first-hit load NOW.
                        tower.attack_target = Some(target_id);
                        tower.attack_cooldown = TOWER_LOAD_FIRST_HIT;
                    }
                    Some(_) => {
                        // Same tracked target. Count down exactly one tick. Releasing
                        // on the tick that reaches zero makes 8 ticks = 0.4 s and
                        // 16 ticks = 0.8 s, with no extra transition frame.
                        if tower.attack_cooldown > 0 {
                            tower.attack_cooldown -= 1;
                        }
                        if tower.attack_cooldown <= 0 {
                            release = true;
                        }
                    }
                }
            }

            if release {
                if let Some((target_id, target_x, target_y)) = best_target {
                    tower_attacks.push(TowerAttack {
                        target_id,
                        target_x,
                        target_y,
                        from_x: *tx,
                        from_y: *ty,
                        damage: *damage,
                        team: player_team,
                        tower_id: *tower_id,
                    });
                }
            }
        }""",
    "Crown Tower target-acquisition/first-hit state machine",
)

# King activation uses the widened target tuple, but activation itself remains
# centre-distance based and independent from the attack-range body-gap rule.
replace_exact(
    combat,
    "for (_, team, ex, ey, _, alive, _) in &targets {",
    "for (_, team, ex, ey, _, _, alive, _) in &targets {",
    "King activation tuple after radius snapshot",
)

print(
    "Rudy patched: Crown Towers acquire target -> first-hit load -> shared projectile "
    "release -> exact regular cadence."
)
