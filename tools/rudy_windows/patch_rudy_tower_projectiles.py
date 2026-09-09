#!/usr/bin/env python3
"""Route Crown Tower attacks through Rudy's normal projectile subsystem.

Crown Towers are stored as TowerState rather than Entity, so they still need a
small release adapter. After release, however, the shot is a normal
Entity::Projectile and is handled by tick_projectiles exactly like Cannon,
Musketeer, etc. This patch intentionally keeps the currently accepted tower
range and reload semantics unchanged; geometry/cadence are tested separately.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
combat = ROOT / "combat.rs"
engine = ROOT / "engine.rs"


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


old_fn = r'''pub fn tick_towers(state: &mut GameState) {
    let targets: Vec<(EntityId, Team, i32, i32, bool, bool, usize)> = state
        .entities
        .iter()
        .enumerate()
        .filter(|(_, e)| e.is_targetable() && (e.is_troop() || e.is_building()))
        .map(|(idx, e)| (e.id, e.team, e.x, e.y, e.is_flying(), e.alive, idx))
        .collect();

    // FIX 4: Track which specific tower fired, not just that "some tower fired".
    // Each event now carries (entity_index, damage, team, tower_id) where tower_id
    // is 0=princess_left, 1=princess_right, 2=king. This way we only reset the
    // cooldown for the exact tower that found a target and attacked.
    struct TowerAttack {
        entity_idx: usize,
        damage: i32,
        team: Team,
        tower_id: u8,  // 0=princess_left, 1=princess_right, 2=king
    }
    let mut tower_attacks: Vec<TowerAttack> = Vec::new();

    for player_team in [Team::Player1, Team::Player2] {
        let enemy_team = player_team.opponent();

        // Extract tower info: (x, y, range, damage, ready, tower_id)
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

        for (tx, ty, range, damage, ready, tower_id) in &tower_infos {
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
                tower_attacks.push(TowerAttack {
                    entity_idx: idx,
                    damage: *damage,
                    team: player_team,
                    tower_id: *tower_id,
                });
            }
        }

        // Tick all tower cooldowns (independent of whether they fired)
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
    }

    // Apply tower damage to entities
    for atk in &tower_attacks {
        if state.entities[atk.entity_idx].alive {
            apply_damage_to_entity(&mut state.entities[atk.entity_idx], atk.damage);
        }
    }

    // FIX 4: Reset cooldown ONLY for the specific tower that fired.
    // Rage on towers: scale cooldown by rage_hitspeed (135 = 35% faster).
    // TOWER_HIT_SPEED * 100 / 135 ≈ 12 ticks instead of 16. Data-driven
    // from BuffStats.hit_speed_multiplier via tick_tower_buffs().
    for atk in &tower_attacks {
        let player = state.player_mut(atk.team);
        let (tower, _) = match atk.tower_id {
            0 => (&mut player.princess_left, 0),
            1 => (&mut player.princess_right, 1),
            2 => (&mut player.king, 2),
            _ => continue,
        };
        let hs = tower.rage_hitspeed.max(10); // Min 10% to avoid division by zero
        tower.attack_cooldown = (TOWER_HIT_SPEED as i64 * 100 / hs as i64).max(1) as i32;
    }
'''

new_fn = r'''pub fn tick_towers(state: &mut GameState, data: &GameData) {
    let targets: Vec<(EntityId, Team, i32, i32, bool, bool, usize)> = state
        .entities
        .iter()
        .enumerate()
        .filter(|(_, e)| e.is_targetable() && (e.is_troop() || e.is_building()))
        .map(|(idx, e)| (e.id, e.team, e.x, e.y, e.is_flying(), e.alive, idx))
        .collect();

    // Crown Towers are pseudo-entities, but their released shots now enter the
    // same Projectile entity pipeline as every other ranged attacker.
    struct TowerAttack {
        target_id: EntityId,
        target_x: i32,
        target_y: i32,
        from_x: i32,
        from_y: i32,
        damage: i32,
        team: Team,
        tower_id: u8,  // 0=princess_left, 1=princess_right, 2=king
    }
    let mut tower_attacks: Vec<TowerAttack> = Vec::new();

    for player_team in [Team::Player1, Team::Player2] {
        let enemy_team = player_team.opponent();

        // Keep accepted range/reload semantics for this step. Only damage delivery
        // changes from instant HP subtraction to release -> projectile -> impact.
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
                    0u8,
                ));
            }
            if player.princess_right.alive {
                infos.push((
                    player.princess_right.pos.0,
                    player.princess_right.pos.1,
                    PRINCESS_TOWER_RANGE,
                    PRINCESS_TOWER_DMG,
                    player.princess_right.attack_cooldown <= 0,
                    1u8,
                ));
            }
            if player.king.alive && player.king.activated {
                infos.push((
                    player.king.pos.0,
                    player.king.pos.1,
                    KING_TOWER_RANGE,
                    KING_TOWER_DMG,
                    player.king.attack_cooldown <= 0,
                    2u8,
                ));
            }
            infos
        };

        for (tx, ty, range, damage, ready, tower_id) in &tower_infos {
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
        }
    }

    // Spawn real projectile entities. Projectile motion/impact is handled only by
    // tick_projectiles; damage is no longer applied here.
    for atk in &tower_attacks {
        let projectile_key = if atk.tower_id == 2 {
            "KingProjectile"
        } else {
            "TowerPrincessProjectile"
        };
        let pd = data.projectiles.get(projectile_key);
        let raw_speed = pd.map(|p| p.speed).unwrap_or(600);
        let gravity = pd.map(|p| p.gravity).unwrap_or(0);
        let dx = (atk.target_x - atk.from_x) as i64;
        let dy = (atk.target_y - atk.from_y) as i64;
        let dist = ((dx * dx + dy * dy) as f64).sqrt() as i32;
        let speed = if gravity > 0 && dist > 0 {
            let g_accel = (gravity as f64) * 0.3;
            let arc_ticks = (2.0 * dist as f64 / g_accel.max(1.0)).sqrt().max(1.0);
            ((dist as f64 / arc_ticks) as i32).max(60)
        } else {
            (raw_speed * 6 / 10).max(60)
        };
        let homing = pd.map(|p| p.homing).unwrap_or(true);
        let splash = pd.map(|p| p.radius).unwrap_or(0);
        let aoe_air = pd.map(|p| p.aoe_to_air || p.hits_air).unwrap_or(true);
        let aoe_ground = pd.map(|p| p.aoe_to_ground || (!p.aoe_to_air && !p.hits_air)).unwrap_or(true);
        let source_id = match (atk.team, atk.tower_id) {
            (Team::Player1, 0) => P1_PRINCESS_LEFT_ID,
            (Team::Player1, 1) => P1_PRINCESS_RIGHT_ID,
            (Team::Player1, 2) => P1_KING_TOWER_ID,
            (Team::Player2, 0) => P2_PRINCESS_LEFT_ID,
            (Team::Player2, 1) => P2_PRINCESS_RIGHT_ID,
            (Team::Player2, 2) => P2_KING_TOWER_ID,
            _ => continue,
        };
        let id = state.alloc_id();
        let mut proj = Entity::new_projectile(
            id,
            atk.team,
            source_id,
            atk.from_x,
            atk.from_y,
            atk.target_id,
            atk.target_x,
            atk.target_y,
            speed,
            atk.damage,
            splash,
            homing,
            0,
            aoe_air,
            aoe_ground,
        );
        proj.card_key = projectile_key.to_string();
        if let EntityKind::Projectile(ref mut p) = proj.kind {
            // Keep homing from source data for Crown Tower arrows/cannonballs.
            // The generic troop path currently forces gravity arcs non-homing; tower
            // projectiles use the explicit homing flag because their data says so.
            p.homing = homing;
        }
        state.entities.push(proj);
    }

    // Reset cooldown ONLY for the specific tower that released a projectile.
    for atk in &tower_attacks {
        let player = state.player_mut(atk.team);
        let tower = match atk.tower_id {
            0 => &mut player.princess_left,
            1 => &mut player.princess_right,
            2 => &mut player.king,
            _ => continue,
        };
        let hs = tower.rage_hitspeed.max(10);
        tower.attack_cooldown = (TOWER_HIT_SPEED as i64 * 100 / hs as i64).max(1) as i32;
    }
'''

replace_once(combat, old_fn, new_fn, "Crown Towers release normal projectile entities")
replace_once(
    engine,
    "combat::tick_towers(state);",
    "combat::tick_towers(state, data);",
    "pass GameData into tower ranged-attack adapter",
)

print("Rudy patched: Crown Tower damage now uses the shared projectile movement/impact pipeline.")
