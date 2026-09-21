#!/usr/bin/env python3
"""Restore CR target reacquisition and spawner-unit deploy timing.

Rudy keeps a valid target until it leaves a large leash.  That is correct for
building-only troops, but ordinary troops must be able to leave a crown tower
when a closer enemy troop enters sight.  The Golem replay exposes this with
Dark Witch versus Goblin Demolisher: the tower remains locked even after the
Demolisher becomes the nearer valid target.

Spawner-created troops also bypass ``Entity::new_troop``'s deploy timer.  That
made Bats emitted by Night Witch active immediately despite their public
``deploy_delay``.  Preserve the data-defined activation delay for regular
spawner children; attached riders keep their existing instant-attach path.
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
COMBAT = ROOT / "combat.rs"
ENGINE = ROOT / "engine.rs"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


old_signature = """    target_lowest_hp: bool,
    // Fix #13: deprioritize/ignore targets with specific buff (Ram Rider bola).
"""
new_signature = """    target_lowest_hp: bool,
    // Ground troops prefer visible enemy troops immediately. Flying troops
    // enable that preference after their first attack release.
    prefer_troops: bool,
    // Fix #13: deprioritize/ignore targets with specific buff (Ram Rider bola).
"""
replace_once(COMBAT, old_signature, new_signature, "target priority argument")

old_find_target = """    let mut best_id: Option<EntityId> = None;
    let mut best_dist: i64 = i64::MAX;
    let mut best_hp: i32 = i32::MAX;
    // Fix #13: fallback target for deprioritized enemies (only used if no better target)
"""
new_find_target = """    let mut best_id: Option<EntityId> = None;
    let mut best_dist: i64 = i64::MAX;
    let mut best_hp: i32 = i32::MAX;
    // Ground troops use troop-over-tower priority immediately. Flying troops
    // keep their initial tower target until their first release, then use the
    // same priority on subsequent reacquisition.
    let mut best_is_troop = false;
    // Fix #13: fallback target for deprioritized enemies (only used if no better target)
"""
replace_once(COMBAT, old_find_target, new_find_target, "troop target class state")

old_standard_target = """            } else {
                // Standard: nearest target
                if dist < best_dist {
                    best_dist = dist;
                    best_id = Some(snap.id);
                }
            }
"""
new_standard_target = """            } else {
                // Standard CR target priority: visible enemy troops outrank
                // crown towers; distance breaks ties within one target class.
                let better_target = if prefer_troops {
                    let prefer_troop = snap.is_troop && !best_is_troop;
                    prefer_troop || (snap.is_troop == best_is_troop && dist < best_dist)
                } else {
                    dist < best_dist
                };
                if better_target {
                    best_dist = dist;
                    best_id = Some(snap.id);
                    best_is_troop = snap.is_troop;
                }
            }
"""
replace_once(COMBAT, old_standard_target, new_standard_target, "troop-over-tower target priority")

old_targeting_params = """        let (sight_sq, min_range_sq, atk_ground, atk_air, only_buildings, only_troops, only_towers,
             only_king_tower, lowest_hp, retarget_every_tick, deprio_buff) =
"""
new_targeting_params = """        let (sight_sq, min_range_sq, atk_ground, atk_air, only_buildings, only_troops, only_towers,
             only_king_tower, lowest_hp, retarget_every_tick, prefer_troops, deprio_buff) =
"""
replace_once(COMBAT, old_targeting_params, new_targeting_params, "target priority tuple")

old_troop_tuple = """                    t.target_lowest_hp,
                    t.retarget_each_tick,
                    // Fix #13: deprioritize buff key (Ram Rider "BolaSnare").
"""
new_troop_tuple = """                    t.target_lowest_hp,
                    t.retarget_each_tick,
                    // Flying swarms keep their initial tower pull until the
                    // first release; ground troops use troop priority at once.
                    !entity.is_flying() || t.has_fired_first || same_group_has_fired,
                    // Fix #13: deprioritize buff key (Ram Rider "BolaSnare").
"""
replace_once(COMBAT, old_troop_tuple, new_troop_tuple, "flying first-target grace")

old_building_tuple = """                EntityKind::Building(b) if b.hit_speed > 0 => (
                    b.range_sq,
                    b.min_range_sq, // Mortar dead zone
                    b.attacks_ground,
                    b.attacks_air,
                    false,
                    false,
                    false,
                    false, // Buildings don't target only king tower
                    false,
                    false,
                    None, // Buildings don't deprioritize by buff
                ),
"""
new_building_tuple = old_building_tuple.replace(
    "                    false,\n                    None, // Buildings don't deprioritize by buff",
    "                    false,\n                    false,\n                    None, // Buildings don't deprioritize by buff",
    1,
)
replace_once(COMBAT, old_building_tuple, new_building_tuple, "building target priority default")

old_group_marker = """        let my_id = entity.id;
        let my_team = entity.team;
"""
new_group_marker = """        // A flying swarm member can inherit the wave's target
        // reacquisition after another same-card member has released once.
        // This prevents the second Bat from completing a stale tower windup
        // after the first Bat has already switched the engagement to a troop.
        let same_group_has_fired = if entity.is_flying() {
            state.entities.iter().any(|other| {
                if other.id == entity.id
                    || !other.alive
                    || other.team != entity.team
                    || other.card_key != entity.card_key
                {
                    return false;
                }
                match &other.kind {
                    EntityKind::Troop(other_t) => other_t.has_fired_first,
                    _ => false,
                }
            })
        } else {
            false
        };
        let my_id = entity.id;
        let my_team = entity.team;
"""
replace_once(COMBAT, old_group_marker, new_group_marker, "flying swarm target inheritance")

old_targeting = """        // ── Building pull: building-only troops always retarget to nearest ──
        let force_retarget = (only_buildings && current_valid && old_target.is_some())
            || retarget_every_tick;

        if current_valid && !force_retarget {
            continue;
        }

        // Find the best valid target
        let deprio_ref = deprio_buff.as_deref();
        let new_target = find_target(
            my_id, my_team, my_x, my_y, sight_sq, min_range_sq, atk_ground, atk_air, only_buildings,
            only_troops, only_towers, only_king_tower, lowest_hp, deprio_ref, &snapshots, &has_buff_fn,
        );
"""
new_targeting = """        // ── Building pull: building-only troops always retarget to nearest ──
        let force_retarget = (only_buildings && current_valid && old_target.is_some())
            || retarget_every_tick;

        // Ordinary troops can reacquire a visible enemy troop while currently
        // attacking a crown tower.  The old leash-only rule kept Dark Witch on
        // the tower after Goblin Demolisher entered sight, which also prevented
        // the real troop-vs-troop sequence from unfolding.  Keep the rule
        // narrow: only a tower target may be replaced, and only by a visible
        // troop. Building-only troops and all other building pulls retain
        // their existing target semantics.
        let deprio_ref = deprio_buff.as_deref();
        let candidate_target = find_target(
            my_id, my_team, my_x, my_y, sight_sq, min_range_sq, atk_ground, atk_air, only_buildings,
            only_troops, only_towers, only_king_tower, lowest_hp, prefer_troops, deprio_ref, &snapshots, &has_buff_fn,
        );
        let switch_to_visible_troop = if current_valid && !force_retarget {
            match (old_target, candidate_target) {
                (Some(old_id), Some(candidate_id))
                    if is_tower_id(old_id) && candidate_id != old_id =>
                {
                    let current_snap = snapshots.iter().find(|s| s.id == old_id);
                    let candidate_snap = snapshots.iter().find(|s| s.id == candidate_id);
                    match (current_snap, candidate_snap) {
                        (Some(current), Some(candidate)) if candidate.is_troop => {
                            true
                        }
                        _ => false,
                    }
                }
                _ => false,
            }
        } else {
            false
        };

        if current_valid && !force_retarget && !switch_to_visible_troop {
            continue;
        }

        let new_target = candidate_target;
"""
replace_once(COMBAT, old_targeting, new_targeting, "closer troop target reacquisition")

old_spawner = """    // Spawn regular units with circular offset from parent position.
    // Uses data-driven spawn_angle_shift from the spawned character's stats.
    // When spawn_angle_shift > 0 (Bat=45°, DarkWitch=90°), units are placed
    // at fixed angular intervals. When 0, fall back to equal-division circle.
    for (team, key, x, y, level, idx, count, spawn_radius) in spawns {
        let lookup_key = key.to_lowercase().replace(' ', "-");
        let stats_opt = data.characters.get(&lookup_key)
            .or_else(|| data.characters.get(&key));
        if let Some(stats) = stats_opt {
            let id = state.alloc_id();
            // Place units in a circle around (x, y) using spawn_radius.
            // If spawn_radius is 0, fall back to collision_radius.
            let radius = if spawn_radius > 0 { spawn_radius } else { stats.collision_radius.max(200) };
            let (ox, oy) = if count <= 1 {
                (0, 0)
            } else {
                // Data-driven angular placement from spawn_angle_shift.
                // spawn_angle_shift is in degrees: Bat=45, DarkWitch=90.
                // When > 0, each unit is offset by this fixed angle step.
                // When 0, fall back to equal-division circle (360° / count).
                let angle_step_deg = if stats.spawn_angle_shift > 0 {
                    stats.spawn_angle_shift as f64
                } else {
                    360.0 / count as f64
                };
                let angle = (idx as f64) * angle_step_deg * std::f64::consts::PI / 180.0;
                ((angle.cos() * radius as f64) as i32, (angle.sin() * radius as f64) as i32)
            };
            let mut troop = Entity::new_troop(id, team, stats, x + ox, y + oy, level, false);
            troop.deploy_timer = 0;
            state.entities.push(troop);"""
new_spawner = old_spawner.replace(
    "            troop.deploy_timer = 0;",
    """            // Spawner children are already placed, so skip card deploy_time but
            // preserve a child-specific activation delay (e.g. Bat=400 ms).
            troop.deploy_timer = crate::entities::ms_to_ticks(stats.deploy_delay);""",
    1,
)
replace_once(ENGINE, old_spawner, new_spawner, "spawner child deploy delay")

print("Rudy patched: closer troop reacquisition and data-driven spawner activation delay.")
