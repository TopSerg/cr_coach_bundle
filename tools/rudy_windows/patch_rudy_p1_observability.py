#!/usr/bin/env python3
"""Patch pinned Rudy with the P-1 authoritative observability API.

This patch deliberately does not alter gameplay semantics.  It adds one Rust-side
step API that clones the pre-tick GameState, advances the real engine exactly once,
then emits:
  * an extended authoritative entity trace for the resulting tick;
  * deterministic transition events derived inside Rust from the two authoritative
    GameState values.

Fields that Rudy does not model explicitly yet (notably a persistent river-jump
state and persistent knockback state) are exposed as null/idle rather than guessed
in Python.  Their event names are reserved by the P-1 schema and will become
emittable when those mechanics gain authoritative runtime state.
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
COMBAT = ROOT / "combat.rs"

combat_text = COMBAT.read_text(encoding="utf-8")
if "pub fn debug_path_state(" not in combat_text:
    marker = """/// Run movement for all troops.
pub fn tick_movement(state: &mut GameState) {
"""
    if combat_text.count(marker) != 1:
        raise RuntimeError("P-1 observability patch: tick_movement marker not found exactly once")
    helper = r"""/// Read-only P-1 path observability helper.
///
/// Returns (final movement target, current bridge waypoint). It calls the same
/// existing routing helpers used by movement and never mutates GameState.
pub fn debug_path_state(state: &GameState, entity: &Entity) -> ((i32, i32), Option<(i32, i32)>) {
    let target_pos = entity
        .target
        .and_then(|target_id| {
            state.entities.iter()
                .find(|candidate| candidate.id == target_id)
                .map(|target| (target.x, target.y))
        })
        .unwrap_or_else(|| default_target_for_troop(state, entity.team, entity.x));

    let can_skip_river = entity.is_flying() || match &entity.kind {
        EntityKind::Troop(t) => t.can_jump_river,
        _ => false,
    };
    let waypoint = if !can_skip_river
        && needs_river_crossing(entity.y, target_pos.1, entity.team)
        && !is_on_bridge(entity.x)
    {
        Some(next_waypoint_for_crossing(
            entity.x, entity.y, target_pos.0, target_pos.1, entity.team,
        ))
    } else {
        None
    };
    (target_pos, waypoint)
}

"""
    combat_text = combat_text.replace(marker, helper + marker, 1)
    COMBAT.write_text(combat_text, encoding="utf-8")

text = LIB.read_text(encoding="utf-8")
if "fn step_trace(&mut self, py: Python<'_>)" in text:
    print("Rudy P-1 observability already patched.")
    raise SystemExit(0)

marker = '''    /// Advance the match by one tick. Returns True if match is still running.
    fn step(&mut self) -> bool {
'''
if text.count(marker) != 1:
    raise RuntimeError("P-1 observability patch: step() marker not found exactly once")

method = r'''    /// P-1 authoritative observability step.
    ///
    /// Advances the actual Rust engine by one tick and returns an extended trace
    /// plus transition events generated in Rust from authoritative pre/post
    /// GameState values.  No gameplay semantics are changed by this method.
    fn step_trace(&mut self, py: Python<'_>) -> PyResult<PyObject> {
        let before = self.state.clone();
        engine::tick(&mut self.state, &self.data);

        let entity_rows = pyo3::types::PyList::empty_bound(py);
        for e in &self.state.entities {
            let row = PyDict::new_bound(py);
            let old = before.entities.iter().find(|candidate| candidate.id == e.id);
            let (vx, vy) = match old {
                Some(prev) => ((e.x - prev.x) * 20, (e.y - prev.y) * 20),
                None => (0, 0),
            };

            let active_statuses: Vec<String> = e
                .buffs
                .iter()
                .filter(|buff| !buff.is_expired())
                .map(|buff| buff.key.clone())
                .collect();

            let active_projectiles: Vec<u32> = self
                .state
                .entities
                .iter()
                .filter_map(|projectile| match &projectile.kind {
                    EntityKind::Projectile(p) if p.source_id == e.id => Some(projectile.id.0),
                    _ => None,
                })
                .collect();

            let (path_target, current_waypoint) = if matches!(&e.kind, EntityKind::Troop(_)) {
                let (target, waypoint) = combat::debug_path_state(&self.state, e);
                (Some(target), waypoint)
            } else {
                (None, None)
            };

            let mut movement_state = if e.deploy_timer > 0 {
                "deploying"
            } else if e.is_immobilized() {
                "immobilized"
            } else if e.is_flying() {
                "air"
            } else {
                "ground"
            };

            let mut combat_phase = "idle";
            let mut windup_remaining = 0i32;
            let mut cooldown_remaining = 0i32;
            let mut load_progress = 0i32;
            let mut charge_state = "none";

            if let EntityKind::Troop(t) = &e.kind {
                if t.is_burrowing {
                    movement_state = "burrowing";
                } else if t.is_dashing {
                    movement_state = "dashing";
                } else if t.is_charging {
                    movement_state = "charging";
                } else if vx != 0 || vy != 0 {
                    movement_state = if e.is_flying() { "air_moving" } else { "ground_moving" };
                } else if e.deploy_timer <= 0 {
                    movement_state = if e.is_flying() { "air_idle" } else { "ground_idle" };
                }

                combat_phase = match t.attack_phase {
                    entities::AttackPhase::Idle => "idle",
                    entities::AttackPhase::Windup => "windup",
                    entities::AttackPhase::Backswing => "backswing",
                    entities::AttackPhase::PostAttackStop => "post_attack_stop",
                };
                if t.attack_phase == entities::AttackPhase::Windup {
                    windup_remaining = t.phase_timer.max(0);
                }
                cooldown_remaining = t.attack_cooldown.max(0);
                load_progress = if t.hit_speed > 0 {
                    (t.hit_speed - t.attack_cooldown).clamp(0, t.hit_speed)
                } else {
                    0
                };
                charge_state = if t.charge_range <= 0 {
                    "none"
                } else if t.is_charging {
                    "charging"
                } else if t.charge_hit_ready {
                    "ready"
                } else {
                    "building"
                };
            } else if let EntityKind::Building(b) = &e.kind {
                cooldown_remaining = b.attack_cooldown.max(0);
                load_progress = if b.hit_speed > 0 {
                    (b.hit_speed - b.attack_cooldown).clamp(0, b.hit_speed)
                } else {
                    0
                };
                combat_phase = if b.attack_cooldown > 0 { "cooldown" } else { "idle" };
                movement_state = "building";
            } else if matches!(&e.kind, EntityKind::Projectile(_)) {
                movement_state = "projectile";
                combat_phase = "flight";
            } else if matches!(&e.kind, EntityKind::SpellZone(_)) {
                movement_state = "spell_zone";
            }

            row.set_item("tick", self.state.tick)?;
            row.set_item("uid", e.id.0)?;
            row.set_item("card_id", &e.card_key)?;
            row.set_item("team", if e.team == Team::Player1 { 0 } else { 1 })?;
            row.set_item("x", e.x)?;
            row.set_item("y", e.y)?;
            row.set_item("vx", vx)?;
            row.set_item("vy", vy)?;
            row.set_item("hp", e.hp)?;
            row.set_item("shield_hp", e.shield_hp)?;
            row.set_item("movement_state", movement_state)?;
            row.set_item("target_uid", e.target.map(|id| id.0))?;
            row.set_item("target_locked", e.target.is_some())?;
            row.set_item("combat_phase", combat_phase)?;
            row.set_item("windup_remaining", windup_remaining)?;
            row.set_item("cooldown_remaining", cooldown_remaining)?;
            row.set_item("load_progress", load_progress)?;
            row.set_item("active_statuses", active_statuses)?;
            row.set_item("charge_state", charge_state)?;
            row.set_item("path_target", path_target)?;
            row.set_item("current_waypoint", current_waypoint)?;
            row.set_item("active_projectiles", active_projectiles)?;
            row.set_item(
                "kind",
                match &e.kind {
                    EntityKind::Troop(_) => "troop",
                    EntityKind::Building(_) => "building",
                    EntityKind::Projectile(_) => "projectile",
                    EntityKind::SpellZone(_) => "spell_zone",
                },
            )?;
            entity_rows.append(row)?;
        }

        let event_rows = pyo3::types::PyList::empty_bound(py);

        // Spawn / projectile-spawn and state-transition events.
        for e in &self.state.entities {
            let old = before.entities.iter().find(|candidate| candidate.id == e.id);
            if old.is_none() {
                let event = PyDict::new_bound(py);
                event.set_item("tick", self.state.tick)?;
                event.set_item("uid", e.id.0)?;
                event.set_item(
                    "type",
                    if matches!(&e.kind, EntityKind::Projectile(_)) {
                        "PROJECTILE_SPAWN"
                    } else {
                        "SPAWN"
                    },
                )?;
                event.set_item("card_id", &e.card_key)?;
                event_rows.append(event)?;
                continue;
            }

            let old = old.unwrap();
            if old.target != e.target {
                let event = PyDict::new_bound(py);
                event.set_item("tick", self.state.tick)?;
                event.set_item("uid", e.id.0)?;
                let event_type = match (old.target, e.target) {
                    (None, Some(_)) => "TARGET_ACQUIRED",
                    (Some(_), None) => "TARGET_DROPPED",
                    (Some(_), Some(_)) => "TARGET_CHANGED",
                    (None, None) => "TARGET_CHANGED",
                };
                event.set_item("type", event_type)?;
                event.set_item("old_target_uid", old.target.map(|id| id.0))?;
                event.set_item("target_uid", e.target.map(|id| id.0))?;
                event_rows.append(event)?;

                let path = PyDict::new_bound(py);
                path.set_item("tick", self.state.tick)?;
                path.set_item("uid", e.id.0)?;
                path.set_item("type", "PATH_REBUILT")?;
                path.set_item("reason", "target_changed")?;
                event_rows.append(path)?;
            }

            let old_stunned = old.is_stunned();
            let new_stunned = e.is_stunned();
            if old_stunned != new_stunned {
                let event = PyDict::new_bound(py);
                event.set_item("tick", self.state.tick)?;
                event.set_item("uid", e.id.0)?;
                event.set_item("type", if new_stunned { "STUN_APPLIED" } else { "STUN_EXPIRED" })?;
                event_rows.append(event)?;
            }

            // Knockback is represented authoritatively in pinned Rudy by the
            // short-lived knockback_stun buff added at the exact displacement
            // site.  Export its lifetime transition instead of guessing from
            // position deltas in Python.
            let old_knockback = old.buffs.iter().any(|buff| {
                buff.key == "knockback_stun" && !buff.is_expired()
            });
            let new_knockback = e.buffs.iter().any(|buff| {
                buff.key == "knockback_stun" && !buff.is_expired()
            });
            if old_knockback != new_knockback {
                let event = PyDict::new_bound(py);
                event.set_item("tick", self.state.tick)?;
                event.set_item("uid", e.id.0)?;
                event.set_item(
                    "type",
                    if new_knockback { "KNOCKBACK_STARTED" } else { "KNOCKBACK_ENDED" },
                )?;
                event_rows.append(event)?;
            }

            if let (EntityKind::Troop(old_t), EntityKind::Troop(new_t)) = (&old.kind, &e.kind) {
                // River jumpers in pinned Rudy do not have a separate animation
                // state; their authoritative mechanic is "can cross the river
                // directly".  Emit jump boundary events at the exact engine tick
                // where their authoritative position enters/leaves the river band.
                if new_t.can_jump_river {
                    let old_in_river = old.y > game_state::RIVER_Y_MIN
                        && old.y < game_state::RIVER_Y_MAX;
                    let new_in_river = e.y > game_state::RIVER_Y_MIN
                        && e.y < game_state::RIVER_Y_MAX;
                    let crossed_whole_band = match e.team {
                        Team::Player1 => old.y <= game_state::RIVER_Y_MIN
                            && e.y >= game_state::RIVER_Y_MAX,
                        Team::Player2 => old.y >= game_state::RIVER_Y_MAX
                            && e.y <= game_state::RIVER_Y_MIN,
                    };

                    if (!old_in_river && new_in_river) || crossed_whole_band {
                        let event = PyDict::new_bound(py);
                        event.set_item("tick", self.state.tick)?;
                        event.set_item("uid", e.id.0)?;
                        event.set_item("type", "JUMP_STARTED")?;
                        event_rows.append(event)?;
                    }
                    if (old_in_river && !new_in_river) || crossed_whole_band {
                        let event = PyDict::new_bound(py);
                        event.set_item("tick", self.state.tick)?;
                        event.set_item("uid", e.id.0)?;
                        event.set_item("type", "JUMP_LANDED")?;
                        event_rows.append(event)?;
                    }
                }

                if old_t.attack_phase != entities::AttackPhase::Windup
                    && new_t.attack_phase == entities::AttackPhase::Windup
                {
                    let event = PyDict::new_bound(py);
                    event.set_item("tick", self.state.tick)?;
                    event.set_item("uid", e.id.0)?;
                    event.set_item("type", "ATTACK_WINDUP_STARTED")?;
                    event.set_item("target_uid", e.target.map(|id| id.0))?;
                    event_rows.append(event)?;
                }

                if old_t.is_charging != new_t.is_charging {
                    let event = PyDict::new_bound(py);
                    event.set_item("tick", self.state.tick)?;
                    event.set_item("uid", e.id.0)?;
                    event.set_item("type", if new_t.is_charging { "CHARGE_STARTED" } else { "CHARGE_RESET" })?;
                    event_rows.append(event)?;
                }

                if !new_t.is_ranged
                    && old_t.attack_phase == entities::AttackPhase::Windup
                    && new_t.attack_phase == entities::AttackPhase::Backswing
                {
                    let event = PyDict::new_bound(py);
                    event.set_item("tick", self.state.tick)?;
                    event.set_item("uid", e.id.0)?;
                    event.set_item("type", "MELEE_HIT")?;
                    event.set_item("target_uid", old.target.map(|id| id.0).or(e.target.map(|id| id.0)))?;
                    event_rows.append(event)?;
                }
            }

            if old.hp > e.hp {
                // Resolve the source inside Rust when the authoritative transition
                // makes it unambiguous: direct melee release or a projectile that
                // disappeared on this target during the same engine tick.
                let mut source_uid: Option<u32> = None;
                let mut source_card_id: Option<String> = None;

                for source_after in &self.state.entities {
                    if let Some(source_before) = before.entities.iter().find(|candidate| candidate.id == source_after.id) {
                        if let (EntityKind::Troop(old_t), EntityKind::Troop(new_t)) = (&source_before.kind, &source_after.kind) {
                            if !new_t.is_ranged
                                && old_t.attack_phase == entities::AttackPhase::Windup
                                && new_t.attack_phase == entities::AttackPhase::Backswing
                                && source_before.target == Some(e.id)
                            {
                                source_uid = Some(source_after.id.0);
                                source_card_id = Some(source_after.card_key.clone());
                            }
                        }
                    }
                }

                if source_uid.is_none() {
                    for projectile_before in &before.entities {
                        if let EntityKind::Projectile(projectile) = &projectile_before.kind {
                            let disappeared = !self.state.entities.iter().any(|candidate| candidate.id == projectile_before.id);
                            if disappeared && projectile.target_id == e.id {
                                source_uid = Some(projectile.source_id.0);
                                source_card_id = before
                                    .entities
                                    .iter()
                                    .find(|candidate| candidate.id == projectile.source_id)
                                    .map(|candidate| candidate.card_key.clone());
                                break;
                            }
                        }
                    }
                }

                let event = PyDict::new_bound(py);
                event.set_item("tick", self.state.tick)?;
                event.set_item("uid", e.id.0)?;
                event.set_item("type", "DAMAGE")?;
                event.set_item("target_uid", e.id.0)?;
                event.set_item("target_card_id", &e.card_key)?;
                event.set_item("source_uid", source_uid)?;
                event.set_item("source_card_id", source_card_id)?;
                event.set_item("damage", old.hp - e.hp)?;
                event.set_item("hp_after", e.hp)?;
                event_rows.append(event)?;
            }
        }

        // Death and projectile-impact events for entities removed by cleanup.
        for old in &before.entities {
            if self.state.entities.iter().any(|candidate| candidate.id == old.id) {
                continue;
            }

            if let EntityKind::Projectile(projectile) = &old.kind {
                let target_changed = self
                    .state
                    .entities
                    .iter()
                    .find(|candidate| candidate.id == projectile.target_id)
                    .map(|target| {
                        before
                            .entities
                            .iter()
                            .find(|candidate| candidate.id == projectile.target_id)
                            .map(|previous_target| target.hp < previous_target.hp)
                            .unwrap_or(false)
                    })
                    .unwrap_or_else(|| {
                        before.entities.iter().any(|candidate| candidate.id == projectile.target_id)
                    });
                if target_changed {
                    let event = PyDict::new_bound(py);
                    event.set_item("tick", self.state.tick)?;
                    event.set_item("uid", old.id.0)?;
                    event.set_item("type", "PROJECTILE_HIT")?;
                    event.set_item("source_uid", projectile.source_id.0)?;
                    event.set_item("target_uid", projectile.target_id.0)?;
                    event_rows.append(event)?;
                }
            } else {
                let event = PyDict::new_bound(py);
                event.set_item("tick", self.state.tick)?;
                event.set_item("uid", old.id.0)?;
                event.set_item("type", "DEATH")?;
                event.set_item("card_id", &old.card_key)?;
                event.set_item("player", if old.team == Team::Player1 { 0 } else { 1 })?;
                event_rows.append(event)?;
            }
        }

        let root = PyDict::new_bound(py);
        root.set_item("tick", self.state.tick)?;
        root.set_item("entities", entity_rows)?;
        root.set_item("events", event_rows)?;
        Ok(root.into())
    }

'''

text = text.replace(marker, method + marker, 1)
LIB.write_text(text, encoding="utf-8")
print("Rudy patched: P-1 Rust-side extended trace + authoritative transition events.")
