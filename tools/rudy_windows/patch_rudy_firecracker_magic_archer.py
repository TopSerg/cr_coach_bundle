#!/usr/bin/env python3
"""Add the two missing line-projectile mechanics used by the full demo.

The pinned Rudy data already describes both mechanics, but the engine ignored
the relevant fields:

* FirecrackerProjectile.spawn_projectile points at FirecrackerExplosion.  The
  child record supplies spawn_count=5, projectile_range=5000 and the fan width.
* EliteArcherArrow supplies projectile_range=11000 and projectile_radius=250;
  it must keep travelling through the acquired target and damage each body on
  the swept line once.

This patch deliberately keys only the piercing behaviour by the canonical
Magic Archer projectile.  Other projectiles also use projectile_range for
different semantics (rolling spells, scatter endpoints), so treating every
ranged projectile as piercing would be incorrect.
"""
from pathlib import Path


ROOT = (
    Path(__file__).resolve().parents[2]
    / "third_party"
    / "clash-royale-suite"
    / "cr-rudy-sim"
    / "simulator"
    / "engine"
    / "src"
)


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


data_types = ROOT / "data_types.rs"
entities = ROOT / "entities.rs"
combat = ROOT / "combat.rs"


replace_once(
    data_types,
'''    #[serde(default)]
    pub spawn_character: Option<String>,
    #[serde(default, deserialize_with = "null_or_i32")]
    pub spawn_character_count: i32,
''',
'''    #[serde(default)]
    pub spawn_character: Option<String>,
    #[serde(default, deserialize_with = "null_or_i32")]
    pub spawn_character_count: i32,
    /// Projectile emitted when this projectile lands (Firecracker shell -> sparks).
    #[serde(default)]
    pub spawn_projectile: Option<String>,
    /// Number of sibling projectiles emitted by the child projectile record.
    #[serde(default, deserialize_with = "null_or_i32")]
    pub spawn_count: i32,
    /// Small origin spread for emitted projectiles.
    #[serde(default, deserialize_with = "null_or_i32")]
    pub spawn_radius: i32,
    /// Minimum child travel distance (Firecracker sparks use 5000).
    #[serde(default, deserialize_with = "null_or_i32")]
    pub min_distance: i32,
''',
    "secondary projectile data fields",
)


replace_once(
    entities,
'''    pub aoe_to_ground: bool,

    // ── Volley dedup (Model C: Princess multi-arrow) ──
''',
'''    pub aoe_to_ground: bool,

    // ── Spawn-on-impact projectile (Firecracker shell) ──
    /// Child projectile record emitted at impact, if any.
    pub spawn_projectile_key: Option<String>,
    /// Fixed launch point, used to preserve the shot direction at impact.
    pub launch_x: i32,
    pub launch_y: i32,

    // ── Piercing line projectile (Magic Archer) ──
    /// Continue to a fixed range and damage every swept body once.
    pub is_piercing: bool,
    pub piercing_radius: i32,
    pub piercing_range: i32,

    // ── Volley dedup (Model C: Princess multi-arrow) ──
''',
    "projectile runtime fields",
)


replace_once(
    entities,
'''                aoe_to_air,
                aoe_to_ground,
                volley_id: 0,
''',
'''                aoe_to_air,
                aoe_to_ground,
                spawn_projectile_key: None,
                launch_x: from_x,
                launch_y: from_y,
                is_piercing: false,
                piercing_radius: 0,
                piercing_range: 0,
                volley_id: 0,
''',
    "projectile runtime defaults",
)


replace_once(
    combat,
'''                        if pd.target_buff.is_some() {
                            p.target_buff = pd.target_buff.clone();
                            p.target_buff_time = crate::entities::ms_to_ticks(pd.buff_time);
                            p.apply_buff_before_damage = pd.apply_buff_before_damage;
                        }
''',
'''                        if pd.target_buff.is_some() {
                            p.target_buff = pd.target_buff.clone();
                            p.target_buff_time = crate::entities::ms_to_ticks(pd.buff_time);
                            p.apply_buff_before_damage = pd.apply_buff_before_damage;
                        }

                        // Firecracker's shell emits the child projectile described by
                        // ProjectileStats at its fixed impact point.
                        p.spawn_projectile_key = pd.spawn_projectile.clone();

                        // Magic Archer arrows do not stop at the acquired target. Aim
                        // once, extend the endpoint to the data-driven range, then use
                        // swept collision checks in tick_projectiles.
                        if pd.name == "EliteArcherArrow" && pd.projectile_range > 0 {
                            let aim_dx = tx - spawn_x;
                            let aim_dy = ty - spawn_y;
                            let aim_dist = (((aim_dx as i64) * (aim_dx as i64)
                                + (aim_dy as i64) * (aim_dy as i64)) as f64).sqrt() as i32;
                            if aim_dist > 0 {
                                p.is_piercing = true;
                                p.piercing_radius = pd.projectile_radius.max(pd.radius).max(1);
                                p.piercing_range = pd.projectile_range;
                                p.target_x = spawn_x
                                    + (aim_dx as i64 * pd.projectile_range as i64
                                        / aim_dist as i64) as i32;
                                p.target_y = spawn_y
                                    + (aim_dy as i64 * pd.projectile_range as i64
                                        / aim_dist as i64) as i32;
                                p.homing = false;
                                p.is_gravity_arc = false;
                            }
                        }
''',
    "spawn-on-impact and Magic Archer launch semantics",
)


replace_once(
    combat,
'''    struct RollingTarget {
        idx: usize,
        id_raw: u32,
        team: Team,
        x: i32,
        y: i32,
        is_flying: bool,
        alive: bool,
    }
''',
'''    struct RollingTarget {
        idx: usize,
        id_raw: u32,
        team: Team,
        x: i32,
        y: i32,
        collision_radius: i32,
        is_flying: bool,
        alive: bool,
    }
''',
    "projectile collision target radius field",
)


replace_once(
    combat,
'''        .map(|(idx, e)| RollingTarget {
            idx, id_raw: e.id.0, team: e.team, x: e.x, y: e.y,
            is_flying: e.is_flying(), alive: e.alive,
        })
''',
'''        .map(|(idx, e)| RollingTarget {
            idx, id_raw: e.id.0, team: e.team, x: e.x, y: e.y,
            collision_radius: e.collision_radius.max(0),
            is_flying: e.is_flying(), alive: e.alive,
        })
''',
    "projectile collision target radius snapshot",
)


replace_once(
    combat,
'''    struct TowerSnapshot {
        id: EntityId,
        team: Team,
        x: i32,
        y: i32,
    }
''',
'''    struct TowerSnapshot {
        id: EntityId,
        team: Team,
        x: i32,
        y: i32,
        collision_radius: i32,
    }
''',
    "projectile tower radius field",
)


replace_once(
    combat,
'''        .filter(|(_, _, t)| t.alive)
        .map(|(id, team, t)| TowerSnapshot { id: *id, team: *team, x: t.pos.0, y: t.pos.1 })
        .collect();

    for entity in state.entities.iter_mut() {
''',
'''        .filter(|(_, _, t)| t.alive)
        .map(|(id, team, t)| TowerSnapshot {
            id: *id,
            team: *team,
            x: t.pos.0,
            y: t.pos.1,
            collision_radius: if *id == P1_KING_TOWER_ID || *id == P2_KING_TOWER_ID {
                KING_TOWER_COLLISION_RADIUS
            } else {
                PRINCESS_TOWER_COLLISION_RADIUS
            },
        })
        .collect();

    // Squared distance from a point to a swept projectile segment. Using the
    // whole segment prevents a fast arrow from tunnelling between 20 Hz ticks.
    fn point_segment_distance_sq(
        px: i32,
        py: i32,
        ax: i32,
        ay: i32,
        bx: i32,
        by: i32,
    ) -> i64 {
        let vx = (bx - ax) as i64;
        let vy = (by - ay) as i64;
        let wx = (px - ax) as i64;
        let wy = (py - ay) as i64;
        let len_sq = vx * vx + vy * vy;
        if len_sq == 0 {
            return wx * wx + wy * wy;
        }
        let dot = wx * vx + wy * vy;
        if dot <= 0 {
            return wx * wx + wy * wy;
        }
        if dot >= len_sq {
            let dx = (px - bx) as i64;
            let dy = (py - by) as i64;
            return dx * dx + dy * dy;
        }
        let closest_x = ax as i64 + vx * dot / len_sq;
        let closest_y = ay as i64 + vy * dot / len_sq;
        let dx = px as i64 - closest_x;
        let dy = py as i64 - closest_y;
        dx * dx + dy * dy
    }

    for entity in state.entities.iter_mut() {
''',
    "swept projectile collision helper",
)


replace_once(
    combat,
'''        if proj.is_rolling {
            // ── Rolling projectile (Log, Barb Barrel) ──
''',
'''        if proj.is_piercing {
            // ── Piercing line projectile (Magic Archer) ──
            // Fly to the fixed full-range endpoint and damage every intersected
            // enemy body once. The arrow remains alive after each collision.
            let old_x = entity.x;
            let old_y = entity.y;
            let dx = proj.target_x - old_x;
            let dy = proj.target_y - old_y;
            let dist_sq = (dx as i64) * (dx as i64) + (dy as i64) * (dy as i64);
            let dist = (dist_sq as f64).sqrt() as i32;
            let step = proj.speed.min(dist).max(0);
            if dist > 0 {
                entity.x += (dx as i64 * step as i64 / dist as i64) as i32;
                entity.y += (dy as i64 * step as i64 / dist as i64) as i32;
            }
            proj.distance_traveled += step;

            let proj_team = entity.team;
            let proj_damage = proj.impact_damage;
            let proj_ct_pct = proj.crown_tower_damage_percent;
            for target in &rolling_targets {
                if !target.alive || target.team == proj_team
                    || proj.hit_entities.contains(&target.id_raw)
                {
                    continue;
                }
                if target.is_flying && !proj.aoe_to_air {
                    continue;
                }
                if !target.is_flying && !proj.aoe_to_ground {
                    continue;
                }
                let hit_radius = (proj.piercing_radius + target.collision_radius) as i64;
                if point_segment_distance_sq(
                    target.x, target.y, old_x, old_y, entity.x, entity.y,
                ) <= hit_radius * hit_radius
                {
                    proj.hit_entities.push(target.id_raw);
                    rolling_entity_hits.push((target.idx, proj_damage, 0, 0, 0));
                }
            }

            if proj.aoe_to_ground {
                for ts in &tower_snaps {
                    if ts.team == proj_team || proj.hit_towers.contains(&ts.id.0) {
                        continue;
                    }
                    let hit_radius = (proj.piercing_radius + ts.collision_radius) as i64;
                    if point_segment_distance_sq(
                        ts.x, ts.y, old_x, old_y, entity.x, entity.y,
                    ) <= hit_radius * hit_radius
                    {
                        proj.hit_towers.push(ts.id.0);
                        rolling_tower_hits.push((
                            ts.id,
                            apply_ct_reduction(proj_damage, proj_ct_pct),
                        ));
                    }
                }
            }

            if proj.distance_traveled >= proj.piercing_range || dist <= proj.speed {
                entity.alive = false;
            }
        } else if proj.is_rolling {
            // ── Rolling projectile (Log, Barb Barrel) ──
''',
    "Magic Archer piercing projectile movement",
)


replace_once(
    combat,
'''                    source_id: proj.source_id,
                    chained_hit_radius: proj.chained_hit_radius,
                    chained_hit_count: proj.chained_hit_count,
                });
''',
'''                    source_id: proj.source_id,
                    chained_hit_radius: proj.chained_hit_radius,
                    chained_hit_count: proj.chained_hit_count,
                    spawn_projectile_key: proj.spawn_projectile_key.clone(),
                    launch_x: proj.launch_x,
                    launch_y: proj.launch_y,
                });
''',
    "Firecracker impact payload",
)


replace_once(
    combat,
'''    // Apply rolling projectile hits (damage + pushback)
    for (idx, dmg, pushback, dir_x, dir_y) in rolling_entity_hits {
''',
'''    // Spawn secondary projectiles after the parent impact. Firecracker's child
    // record is fully data-driven: count, range, fan width, speed, splash and
    // level-scaled damage all come from FirecrackerExplosion.
    let mut secondary_projectiles: Vec<Entity> = Vec::new();
    for impact in &impacts {
        let child_key = match impact.spawn_projectile_key.as_ref() {
            Some(key) => key,
            None => continue,
        };
        let child = match data.projectiles.get(child_key.as_str()) {
            Some(stats) => stats,
            None => continue,
        };
        let dx = impact.impact_x - impact.launch_x;
        let dy = impact.impact_y - impact.launch_y;
        let dir_len = (((dx as i64) * (dx as i64) + (dy as i64) * (dy as i64)) as f64)
            .sqrt() as i32;
        if dir_len <= 0 {
            continue;
        }

        let source_level = state.entities.iter()
            .find(|e| e.id == impact.source_id)
            .and_then(|e| match &e.kind {
                EntityKind::Troop(t) => Some(t.level),
                EntityKind::Building(b) => Some(b.level),
                _ => None,
            })
            .unwrap_or(11);
        let child_damage = if !child.damage_per_level.is_empty() {
            let level_idx = source_level.saturating_sub(1)
                .min(child.damage_per_level.len() - 1);
            child.damage_per_level[level_idx]
        } else {
            child.damage
        };
        let count = child.spawn_count.max(1);
        let range = child.projectile_range.max(child.min_distance).max(1);
        let spread = child.projectile_start_extra_radius.max(0);
        let perp_x = -dy as i64;
        let perp_y = dx as i64;
        let speed = if child.gravity > 0 {
            let gravity_accel = (child.gravity as f64) * 0.45;
            let arc_ticks = (2.0 * range as f64 / gravity_accel.max(1.0))
                .sqrt()
                .max(1.0);
            (range as f64 / arc_ticks) as i32
        } else {
            child.speed * 6 / 10
        }.max(60);

        for i in 0..count {
            let centered_twice = 2 * i - (count - 1);
            let offset = if count > 1 {
                centered_twice as i64 * spread as i64 / (count - 1) as i64
            } else {
                0
            };
            let end_x = impact.impact_x
                + (dx as i64 * range as i64 / dir_len as i64) as i32
                + (perp_x * offset / dir_len as i64) as i32;
            let end_y = impact.impact_y
                + (dy as i64 * range as i64 / dir_len as i64) as i32
                + (perp_y * offset / dir_len as i64) as i32;
            let origin_offset = if spread > 0 {
                offset * child.spawn_radius as i64 / spread as i64
            } else {
                0
            };
            let start_x = impact.impact_x
                + (perp_x * origin_offset / dir_len as i64) as i32;
            let start_y = impact.impact_y
                + (perp_y * origin_offset / dir_len as i64) as i32;
            let id = state.alloc_id();
            let mut projectile = Entity::new_projectile(
                id,
                impact.team,
                impact.source_id,
                start_x,
                start_y,
                EntityId(0),
                end_x,
                end_y,
                speed,
                child_damage,
                child.radius.max(child.projectile_radius),
                false,
                child.crown_tower_damage_percent,
                child.aoe_to_air,
                child.aoe_to_ground,
            );
            projectile.card_key = child_key.clone();
            if let EntityKind::Projectile(ref mut p) = projectile.kind {
                p.is_gravity_arc = child.gravity > 0;
            }
            secondary_projectiles.push(projectile);
        }
    }
    state.entities.extend(secondary_projectiles);

    // Apply rolling and piercing projectile hits (damage + optional pushback)
    for (idx, dmg, pushback, dir_x, dir_y) in rolling_entity_hits {
''',
    "Firecracker secondary fan spawn",
)


replace_once(
    combat,
'''    // Chain lightning (Electro Dragon, Electro Spirit)
    chained_hit_radius: i32,
    chained_hit_count: i32,
}
''',
'''    // Chain lightning (Electro Dragon, Electro Spirit)
    chained_hit_radius: i32,
    chained_hit_count: i32,
    // Spawn-on-impact projectile (Firecracker shell).
    spawn_projectile_key: Option<String>,
    launch_x: i32,
    launch_y: i32,
}
''',
    "Firecracker impact struct fields",
)


print(
    "Rudy patched: Firecracker emits its five data-driven secondary sparks; "
    "Magic Archer arrows sweep the full 11-tile line and hit each target once."
)
