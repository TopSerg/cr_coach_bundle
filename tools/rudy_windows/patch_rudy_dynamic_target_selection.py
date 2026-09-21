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

        // Ordinary troops can reacquire a closer enemy troop while currently
        // attacking a crown tower.  The old leash-only rule kept Dark Witch on
        // the tower after Goblin Demolisher entered sight, which also prevented
        // the real troop-vs-troop sequence from unfolding.  Keep the rule
        // narrow: only a tower target may be replaced, and only by a strictly
        // closer troop. Building-only troops and all other building pulls retain
        // their existing target semantics.
        let deprio_ref = deprio_buff.as_deref();
        let candidate_target = find_target(
            my_id, my_team, my_x, my_y, sight_sq, min_range_sq, atk_ground, atk_air, only_buildings,
            only_troops, only_towers, only_king_tower, lowest_hp, deprio_ref, &snapshots, &has_buff_fn,
        );
        let switch_to_closer_troop = if current_valid && !force_retarget {
            match (old_target, candidate_target) {
                (Some(old_id), Some(candidate_id))
                    if is_tower_id(old_id) && candidate_id != old_id =>
                {
                    let current_snap = snapshots.iter().find(|s| s.id == old_id);
                    let candidate_snap = snapshots.iter().find(|s| s.id == candidate_id);
                    match (current_snap, candidate_snap) {
                        (Some(current), Some(candidate)) if candidate.is_troop => {
                            let current_dx = (my_x - current.x) as i64;
                            let current_dy = (my_y - current.y) as i64;
                            let candidate_dx = (my_x - candidate.x) as i64;
                            let candidate_dy = (my_y - candidate.y) as i64;
                            candidate_dx * candidate_dx + candidate_dy * candidate_dy
                                < current_dx * current_dx + current_dy * current_dy
                        }
                        _ => false,
                    }
                }
                _ => false,
            }
        } else {
            false
        };

        if current_valid && !force_retarget && !switch_to_closer_troop {
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
