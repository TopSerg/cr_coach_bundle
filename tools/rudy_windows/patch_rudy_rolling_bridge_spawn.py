#!/usr/bin/env python3
"""Fix demo2 rolling spells at bridges and Barbarian Barrel termination.

Rolling ground projectiles may not cross open water, but they do cross either
bridge.  Barbarian Barrel's troop is also a termination effect: the Barbarian
must appear where the rolling projectile actually breaks, including an early
break at an open-water river edge.
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


entities = ROOT / "entities.rs"
lib = ROOT / "lib.rs"
combat = ROOT / "combat.rs"


replace_once(
    entities,
'''    /// Tower sentinel IDs already hit by this rolling projectile.
    pub hit_towers: Vec<u32>,

    // ── Boomerang projectile (Executioner axe) ──
''',
'''    /// Tower sentinel IDs already hit by this rolling projectile.
    pub hit_towers: Vec<u32>,
    /// Troop emitted where a rolling projectile terminates (Barbarian Barrel).
    pub rolling_spawn_character: Option<String>,
    pub rolling_spawn_level: usize,

    // ── Boomerang projectile (Executioner axe) ──
''',
    "rolling termination spawn fields",
)


replace_once(
    entities,
'''                hit_entities: Vec::new(),
                hit_towers: Vec::new(),
                is_boomerang: false,
''',
'''                hit_entities: Vec::new(),
                hit_towers: Vec::new(),
                rolling_spawn_character: None,
                rolling_spawn_level: 11,
                is_boomerang: false,
''',
    "rolling termination spawn defaults",
)


replace_once(
    lib,
'''                        let roll_speed = entities::speed_to_units_per_tick(proj_stats.speed);
                        let roll_speed = roll_speed.max(30); // Minimum speed
''',
'''                        // Rolling projectile speed is already expressed in arena
                        // units per tick (Log/Barrel=200). Troop category conversion
                        // would halve it and make the roll last twice as long.
                        let roll_speed = proj_stats.speed.max(30);
''',
    "rolling projectile speed units",
)


replace_once(
    lib,
'''                            pd.rolling_range = roll_range;
                            pd.pushback = proj_stats.pushback;
                            pd.pushback_all = proj_stats.pushback_all;
                            pd.target_buff = proj_stats.target_buff.clone();
                            pd.target_buff_time = if proj_stats.buff_time > 0 {
                                entities::ms_to_ticks(proj_stats.buff_time)
                            } else { 0 };
                        }
''',
'''                            pd.rolling_range = roll_range;
                            pd.pushback = proj_stats.pushback;
                            pd.pushback_all = proj_stats.pushback_all;
                            pd.target_buff = proj_stats.target_buff.clone();
                            pd.target_buff_time = if proj_stats.buff_time > 0 {
                                entities::ms_to_ticks(proj_stats.buff_time)
                            } else { 0 };
                            pd.rolling_spawn_character = proj_stats.spawn_character.clone();
                            pd.rolling_spawn_level = level;
                        }
''',
    "Barbarian Barrel runtime spawn payload",
)


replace_once(
    lib,
'''                    if let Some(ref spawn_key) = proj_stats.spawn_character {
                        let spawn_count = if proj_stats.spawn_character_count > 0 {
''',
'''                    if let Some(ref spawn_key) = proj_stats.spawn_character {
                        // Rolling spell troops are emitted by tick_projectiles at
                        // the actual break position, not pre-created at cast origin.
                        if !is_rolling {
                        let spawn_count = if proj_stats.spawn_character_count > 0 {
''',
    "skip eager rolling troop spawn",
)


replace_once(
    lib,
'''                                self.state.entities.push(troop);
                            }
                        }
                    }
                }
            }
        }

        Ok(id.0)
''',
'''                                self.state.entities.push(troop);
                            }
                        }
                        }
                    }
                }
            }
        }

        Ok(id.0)
''',
    "close non-rolling eager spawn guard",
)


replace_once(
    combat,
'''    let mut rolling_entity_hits: Vec<(usize, i32, i32, i32, i32)> = Vec::new();
    let mut rolling_tower_hits: Vec<(EntityId, i32)> = Vec::new();
''',
'''    let mut rolling_entity_hits: Vec<(usize, i32, i32, i32, i32)> = Vec::new();
    let mut rolling_tower_hits: Vec<(EntityId, i32)> = Vec::new();
    // Troops emitted where rolling projectiles terminate.
    let mut rolling_troop_spawns: Vec<(Team, String, i32, i32, usize)> = Vec::new();
''',
    "rolling troop spawn queue",
)


replace_once(
    combat,
'''            if entity.y >= RIVER_Y_MIN && entity.y <= RIVER_Y_MAX {
                // Clamp to the approaching river edge
                entity.y = if entity.team == Team::Player1 { RIVER_Y_MIN } else { RIVER_Y_MAX };
                entity.alive = false;
                // Damage hitbox checks below still run for this final position,
                // so the Log can hit anything at the river edge before dying.
            }
''',
'''            if entity.y >= RIVER_Y_MIN && entity.y <= RIVER_Y_MAX
                && !is_on_bridge(entity.x)
            {
                // Open water stops a ground roll. Either bridge remains valid
                // ground and allows the projectile to continue across the river.
                entity.y = if entity.team == Team::Player1 { RIVER_Y_MIN } else { RIVER_Y_MAX };
                entity.alive = false;
                // Damage hitbox checks below still run for this final position.
            }
''',
    "rolling projectiles cross bridges but not open water",
)


replace_once(
    combat,
'''            let (move_x, move_y) = if dist > 0 {
                let mx = (dx as i64 * proj.speed as i64 / dist as i64) as i32;
                let my = (dy as i64 * proj.speed as i64 / dist as i64) as i32;
                (mx, my)
            } else {
                (0, 0)
            };

            entity.x += move_x;
            entity.y += move_y;
            proj.distance_traveled += proj.speed;
''',
'''            let step = proj.speed.min(dist).max(0);
            let (move_x, move_y) = if dist > 0 {
                let mx = (dx as i64 * step as i64 / dist as i64) as i32;
                let my = (dy as i64 * step as i64 / dist as i64) as i32;
                (mx, my)
            } else {
                (0, 0)
            };

            entity.x += move_x;
            entity.y += move_y;
            proj.distance_traveled += step;
''',
    "rolling projectiles stop exactly at endpoint",
)


replace_once(
    combat,
'''            // Die when we've traveled the full range or passed the target
            if proj.distance_traveled >= proj.rolling_range || dist <= proj.speed {
                entity.alive = false;
            }
''',
'''            // Terminate at full range, endpoint, or an open-water edge. Any
            // payload troop appears exactly at this resolved break position.
            if !entity.alive || proj.distance_traveled >= proj.rolling_range || dist <= proj.speed {
                entity.alive = false;
                if let Some(spawn_key) = proj.rolling_spawn_character.take() {
                    rolling_troop_spawns.push((
                        entity.team,
                        spawn_key,
                        entity.x,
                        entity.y,
                        proj.rolling_spawn_level,
                    ));
                }
            }
''',
    "rolling termination emits payload troop",
)


replace_once(
    combat,
'''    // Spawn secondary projectiles after the parent impact. Firecracker's child
''',
'''    // Materialize rolling-spell payload troops after projectile iteration.
    for (team, spawn_key, x, y, level) in rolling_troop_spawns {
        if let Some(stats) = data.find_character(&spawn_key) {
            let id = state.alloc_id();
            let mut troop = Entity::new_troop(id, team, stats, x, y, level, false);
            troop.deploy_timer = 0;
            state.entities.push(troop);
        }
    }

    // Spawn secondary projectiles after the parent impact. Firecracker's child
''',
    "materialize rolling payload troops",
)


print(
    "Rudy patched: Log/Barbarian Barrel cross bridge ground, keep open-water "
    "blocking, use projectile speed units, and spawn Barbarian at break position."
)
