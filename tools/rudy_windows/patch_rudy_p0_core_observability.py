#!/usr/bin/env python3
"""Add the remaining read-only state needed by the P0 M-gates.

P-1 deliberately covered ordinary Rudy entities. Crown Towers are held in
``TowerState`` rather than ``Entity`` and therefore need a small adapter. This
patch only serialises authoritative state and emits target transitions; it does
not participate in simulation updates.
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
LIB = ROOT / "lib.rs"

text = LIB.read_text(encoding="utf-8")
if 'row.set_item("kind", "tower")?' in text:
    print("Rudy P0 core observability already patched.")
    raise SystemExit(0)

# Geometry needed by M01 is engine state. Keep it distinct from the placement
# footprint in the reference file: collision radius is not a deploy footprint.
old_geometry = '''            row.set_item("active_projectiles", active_projectiles)?;
            row.set_item(
                "kind",'''
new_geometry = '''            row.set_item("active_projectiles", active_projectiles)?;
            row.set_item("collision_radius", e.collision_radius)?;
            row.set_item("deploy_timer", e.deploy_timer)?;
            row.set_item(
                "kind",'''
if text.count(old_geometry) != 1:
    raise RuntimeError("P0 observability: P-1 entity geometry marker not found exactly once")
text = text.replace(old_geometry, new_geometry, 1)

marker = '''        let event_rows = pyo3::types::PyList::empty_bound(py);

        // Spawn / projectile-spawn and state-transition events.'''

tower_trace = r'''        // Crown Towers are authoritative TowerState values, not Entity values.
        // Export them into the same per-tick collection so M38 uses no Python
        // reconstruction. Stable high IDs are the engine's projectile source IDs.
        for team in [Team::Player1, Team::Player2] {
            let player = self.state.player(team);
            let towers = [
                ("princess-left", &player.princess_left,
                    if team == Team::Player1 { combat::P1_PRINCESS_LEFT_ID } else { combat::P2_PRINCESS_LEFT_ID }),
                ("princess-right", &player.princess_right,
                    if team == Team::Player1 { combat::P1_PRINCESS_RIGHT_ID } else { combat::P2_PRINCESS_RIGHT_ID }),
                ("king-tower", &player.king,
                    if team == Team::Player1 { combat::P1_KING_TOWER_ID } else { combat::P2_KING_TOWER_ID }),
            ];
            for (card_id, tower, uid) in towers {
                let row = PyDict::new_bound(py);
                row.set_item("tick", self.state.tick)?;
                row.set_item("uid", uid.0)?;
                row.set_item("card_id", card_id)?;
                row.set_item("team", if team == Team::Player1 { 0 } else { 1 })?;
                row.set_item("x", tower.pos.0)?;
                row.set_item("y", tower.pos.1)?;
                row.set_item("vx", 0)?;
                row.set_item("vy", 0)?;
                row.set_item("hp", tower.hp)?;
                row.set_item("shield_hp", 0)?;
                row.set_item("movement_state", "tower")?;
                row.set_item("target_uid", tower.attack_target.map(|id| id.0))?;
                row.set_item("target_locked", tower.attack_target.is_some())?;
                row.set_item("combat_phase", if tower.attack_target.is_some() { "tracking" } else { "idle" })?;
                row.set_item("windup_remaining", 0)?;
                row.set_item("cooldown_remaining", tower.attack_cooldown.max(0))?;
                row.set_item("load_progress", 0)?;
                row.set_item("active_statuses", Vec::<String>::new())?;
                row.set_item("charge_state", "none")?;
                row.set_item("path_target", Option::<(i32, i32)>::None)?;
                row.set_item("current_waypoint", Option::<(i32, i32)>::None)?;
                let projectiles: Vec<u32> = self.state.entities.iter().filter_map(|entity| {
                    match &entity.kind {
                        EntityKind::Projectile(p) if p.source_id == uid => Some(entity.id.0),
                        _ => None,
                    }
                }).collect();
                row.set_item("active_projectiles", projectiles)?;
                row.set_item("collision_radius", 0)?;
                row.set_item("deploy_timer", 0)?;
                row.set_item("kind", "tower")?;
                entity_rows.append(row)?;
            }
        }

        let event_rows = pyo3::types::PyList::empty_bound(py);

        // Tower targeting transitions come from TowerState itself. This is the
        // exact acquisition/drop tick used by combat, including retargets.
        for team in [Team::Player1, Team::Player2] {
            let player = self.state.player(team);
            let old_player = before.player(team);
            let towers = [
                (&old_player.princess_left, &player.princess_left,
                    if team == Team::Player1 { combat::P1_PRINCESS_LEFT_ID } else { combat::P2_PRINCESS_LEFT_ID }),
                (&old_player.princess_right, &player.princess_right,
                    if team == Team::Player1 { combat::P1_PRINCESS_RIGHT_ID } else { combat::P2_PRINCESS_RIGHT_ID }),
                (&old_player.king, &player.king,
                    if team == Team::Player1 { combat::P1_KING_TOWER_ID } else { combat::P2_KING_TOWER_ID }),
            ];
            for (old_tower, tower, uid) in towers {
                if old_tower.attack_target != tower.attack_target {
                    let event = PyDict::new_bound(py);
                    event.set_item("tick", self.state.tick)?;
                    event.set_item("uid", uid.0)?;
                    event.set_item("type", match (old_tower.attack_target, tower.attack_target) {
                        (None, Some(_)) => "TARGET_ACQUIRED",
                        (Some(_), None) => "TARGET_DROPPED",
                        _ => "TARGET_CHANGED",
                    })?;
                    event.set_item("old_target_uid", old_tower.attack_target.map(|id| id.0))?;
                    event.set_item("target_uid", tower.attack_target.map(|id| id.0))?;
                    event.set_item("source_kind", "tower")?;
                    event_rows.append(event)?;
                }
            }
        }

        // Spawn / projectile-spawn and state-transition events.'''

if text.count(marker) != 1:
    raise RuntimeError("P0 observability: P-1 event marker not found exactly once")
LIB.write_text(text.replace(marker, tower_trace, 1), encoding="utf-8")
print("Rudy patched: P0 Crown Tower targeting + entity geometry observability.")
