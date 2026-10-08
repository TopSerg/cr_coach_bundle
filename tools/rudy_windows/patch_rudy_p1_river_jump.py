#!/usr/bin/env python3
"""P1: data-driven river-jump runtime state for the pinned, already P-1-patched Rudy.

The state belongs to each Rust TroopData, not to the Python replay validator.
The four phases are conservative geometric transitions; timing/arc parameters
still need current-patch physical calibration before M11/M12 can be VERIFIED.
"""
from pathlib import Path

ROOT = (Path(__file__).resolve().parents[2] / "third_party" /
        "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    data = path.read_text(encoding="utf-8")
    if new in data:
        print("Already patched:", label)
        return
    n = data.count(old)
    if n != 1:
        raise RuntimeError(f"P1 {label}: expected one marker, found {n}")
    path.write_text(data.replace(old, new, 1), encoding="utf-8")
    print("Patched:", label)


ent = ROOT / "entities.rs"
replace_once(
    ent,
    "#[derive(Debug, Clone)]\npub struct TroopData {",
    """/// Explicit river-jump lifecycle independent from Dash and Charge.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RiverJumpPhase {
    None,
    Approaching,
    Airborne,
    Landing,
}

#[derive(Debug, Clone)]
pub struct TroopData {""",
    "river jump phase enum",
)
replace_once(
    ent,
    "    pub can_jump_river: bool,\n",
    """    pub can_jump_river: bool,
    pub river_jump_phase: RiverJumpPhase,
    pub jump_start_tick: i32,
    pub jump_start_x: i32,
    pub jump_start_y: i32,
    pub jump_land_tick: i32,
    pub jump_land_x: i32,
    pub jump_land_y: i32,
""",
    "river jump authoritative fields",
)
replace_once(
    ent,
    "    pub fn is_flying(&self) -> bool {\n        self.z > 0\n    }",
    """    pub fn is_flying(&self) -> bool {
        self.z > 0 || matches!(
            &self.kind,
            EntityKind::Troop(t) if t.river_jump_phase == RiverJumpPhase::Airborne
        )
    }""",
    "airborne gameplay plane (not visual-only z)",
)
replace_once(
    ent,
    "                kamikaze: stats.kamikaze,\n",
    """                river_jump_phase: RiverJumpPhase::None,
                jump_start_tick: -1,
                jump_start_x: 0,
                jump_start_y: 0,
                jump_land_tick: -1,
                jump_land_x: 0,
                jump_land_y: 0,
                kamikaze: stats.kamikaze,
""",
    "jump fields at troop spawn",
)

combat = ROOT / "combat.rs"
marker = "/// Run movement for all troops.\npub fn tick_movement(state: &mut GameState) {"
helper = """/// P1: update the persistent river-jump lifecycle *after* movement and before
/// collision/combat.  Airborne troops are treated as air-layer targets by the
/// existing generic targeting, spell, projectile and collision pipelines.
///
/// This conservative band-crossing model is a synthetic baseline. Exact onset,
/// landing arcs and special Inferno lock continuity need physical fidelity data.
pub fn tick_river_jumps(state: &mut GameState) {
    for entity in &mut state.entities {
        let phase = match &entity.kind {
            EntityKind::Troop(t) if t.can_jump_river && entity.z <= 0
                && entity.alive && entity.deploy_timer <= 0 => t.river_jump_phase,
            _ => continue,
        };
        let over_water = entity.y > RIVER_Y_MIN
            && entity.y < RIVER_Y_MAX
            && !is_on_bridge(entity.x);
        let near_entry = match entity.team {
            Team::Player1 => entity.y <= RIVER_Y_MIN
                && entity.y >= RIVER_Y_MIN - 500,
            Team::Player2 => entity.y >= RIVER_Y_MAX
                && entity.y <= RIVER_Y_MAX + 500,
        };
        let next = if over_water {
            crate::entities::RiverJumpPhase::Airborne
        } else if phase == crate::entities::RiverJumpPhase::Airborne {
            crate::entities::RiverJumpPhase::Landing
        } else if phase == crate::entities::RiverJumpPhase::Landing {
            crate::entities::RiverJumpPhase::None
        } else if near_entry && !is_on_bridge(entity.x) {
            crate::entities::RiverJumpPhase::Approaching
        } else {
            crate::entities::RiverJumpPhase::None
        };

        if let EntityKind::Troop(t) = &mut entity.kind {
            if next == crate::entities::RiverJumpPhase::Airborne
                && phase != crate::entities::RiverJumpPhase::Airborne {
                t.jump_start_tick = state.tick;
                t.jump_start_x = entity.x;
                t.jump_start_y = entity.y;
            }
            if next == crate::entities::RiverJumpPhase::Landing
                && phase == crate::entities::RiverJumpPhase::Airborne {
                t.jump_land_tick = state.tick;
                t.jump_land_x = entity.x;
                t.jump_land_y = entity.y;
            }
            t.river_jump_phase = next;
        }
    }
}

"""
replace_once(combat, marker, helper + marker, "authoritative post-movement jump lifecycle")

engine = ROOT / "engine.rs"
replace_once(
    engine,
    "    combat::tick_movement(state);\n",
    """    combat::tick_movement(state);
    // P1: refresh the persistent airborne/landing state before collision and combat.
    combat::tick_river_jumps(state);
""",
    "wire jump tick between movement and collision",
)

lib = ROOT / "lib.rs"
replace_once(
    lib,
    "            row.set_item(\"movement_state\", movement_state)?;\n",
    """            // Phase is authoritative in TroopData; don't infer it from y in Python.
            let jump_state = match &e.kind {
                EntityKind::Troop(t) => match t.river_jump_phase {
                    entities::RiverJumpPhase::None => "none",
                    entities::RiverJumpPhase::Approaching => "approaching_jump",
                    entities::RiverJumpPhase::Airborne => "airborne",
                    entities::RiverJumpPhase::Landing => "landing",
                },
                _ => "none",
            };
            if jump_state != "none" {
                movement_state = jump_state;
            }
            row.set_item("movement_state", movement_state)?;
            row.set_item("jump_state", jump_state)?;
            if let EntityKind::Troop(t) = &e.kind {
                row.set_item("jump_start_tick", if t.jump_start_tick >= 0 { Some(t.jump_start_tick) } else { None })?;
                row.set_item("jump_start_x", if t.jump_start_tick >= 0 { Some(t.jump_start_x) } else { None })?;
                row.set_item("jump_start_y", if t.jump_start_tick >= 0 { Some(t.jump_start_y) } else { None })?;
                row.set_item("jump_land_tick", if t.jump_land_tick >= 0 { Some(t.jump_land_tick) } else { None })?;
                row.set_item("jump_land_x", if t.jump_land_tick >= 0 { Some(t.jump_land_x) } else { None })?;
                row.set_item("jump_land_y", if t.jump_land_tick >= 0 { Some(t.jump_land_y) } else { None })?;
            }
""",
    "expose jump state/start/land positions in Rust trace",
)

data = lib.read_text(encoding="utf-8")
start_marker = "                // River jumpers in pinned Rudy do not have a separate animation"
end_marker = "                if old_t.attack_phase != entities::AttackPhase::Windup"
if "old_t.river_jump_phase != new_t.river_jump_phase" not in data:
    if data.count(start_marker) != 1 or data.count(end_marker) != 1:
        raise RuntimeError("P1 authoritative jump events: P-1 marker mismatch")
    start = data.index(start_marker)
    end = data.index(end_marker, start)
    event_code = """                // P1: emit explicit troop phase transitions, not river-band guesses.
                if old_t.river_jump_phase != new_t.river_jump_phase {
                    let kind = match new_t.river_jump_phase {
                        entities::RiverJumpPhase::Airborne => Some("JUMP_STARTED"),
                        entities::RiverJumpPhase::Landing => Some("JUMP_LANDED"),
                        _ => None,
                    };
                    if let Some(kind) = kind {
                        let event = PyDict::new_bound(py);
                        event.set_item("tick", self.state.tick)?;
                        event.set_item("uid", e.id.0)?;
                        event.set_item("type", kind)?;
                        event.set_item("x", e.x)?;
                        event.set_item("y", e.y)?;
                        event.set_item("jump_state", if kind == "JUMP_STARTED" {
                            "airborne"
                        } else {
                            "landing"
                        })?;
                        event_rows.append(event)?;
                    }
                }

"""
    lib.write_text(data[:start] + event_code + data[end:], encoding="utf-8")
    print("Patched: jump event sourcing from authoritative runtime state")
else:
    print("Already patched: jump events")
print("P1 Rudy river-jump state patch completed.")

# Generic status-driven combat reset. This is deliberately not keyed to card names:
# every stunned/frozen combatant invalidates its target and any active ramp,
# and the existing shared cooldown/charge reset remains authoritative.
replace_once(
    combat,
    """        let entity = &state.entities[i];
        if !entity.is_targetable() {
            continue;
        }

        // Fix #12+13: Extract targeting params""",
    """        let entity = &state.entities[i];
        if !entity.is_targetable() || entity.is_immobilized() {
            continue;
        }

        // Fix #12+13: Extract targeting params""",
    "no new target lock during stun/freeze",
)
replace_once(
    combat,
    """            // Stun/Freeze breaks inferno beam — reset ramp
            let entity = &mut state.entities[ei];
            match &mut entity.kind {""",
    """            // Stun/freeze invalidates the sticky lock. Retargeting resumes
            // through the same shared pipeline after the control effect ends.
            let entity = &mut state.entities[ei];
            entity.target = None;
            match &mut entity.kind {""",
    "generic target invalidation on stun/freeze",
)
replace_once(
    combat,
    "if t.ramp_damage3 > 0 { t.ramp_ticks = 0; }",
    "if t.ramp_damage3 > 0 { t.ramp_ticks = 0; t.ramp_target = None; }",
    "generic Inferno troop ramp reset on stun",
)
replace_once(
    combat,
    "EntityKind::Building(ref mut b) if b.ramp_damage3 > 0 => { b.ramp_ticks = 0; }",
    "EntityKind::Building(ref mut b) if b.ramp_damage3 > 0 => { b.ramp_ticks = 0; b.ramp_target = None; }",
    "generic Inferno building ramp reset on stun",
)
replace_once(
    lib,
    """            row.set_item("charge_state", charge_state)?;
""",
    """            row.set_item("charge_state", charge_state)?;
            row.set_item("ramp_ticks", match &e.kind {
                EntityKind::Troop(t) => t.ramp_ticks,
                EntityKind::Building(b) => b.ramp_ticks,
                _ => 0,
            })?;
            row.set_item("ramp_target_uid", match &e.kind {
                EntityKind::Troop(t) => t.ramp_target.map(|v| v.0),
                EntityKind::Building(b) => b.ramp_target.map(|v| v.0),
                _ => None,
            })?;
""",
    "expose authoritative Inferno ramp state for M23",
)
print("P1 Rudy stun-retarget and ramp reset patch completed.")
