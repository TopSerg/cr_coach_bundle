#!/usr/bin/env python3
"""M17/M18 projectile contract for pinned Rudy after existing P-1/P1 patches.

Guidance is independent of gravity and of shooter lifetime:
- direct-hit (no splash): follow locked target UID;
- splash: commit launch coordinates, not the moving target;
- a released projectile is a separate entity even after shooter death.
"""
from pathlib import Path

ROOT = (Path(__file__).resolve().parents[2] / "third_party" /
        "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src")


def replace(path, old, new, label):
    source = path.read_text(encoding="utf-8")
    if new in source:
        print("already patched:", label)
        return
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"M17/M18 {label}: expected one marker, found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print("patched:", label)


combat = ROOT / "combat.rs"
# The final splash radius is already resolved from projectile and attacker data
# at this constructor, so do not guess from gravity or a hardcoded card name.
# The dedicated scatter/boomerang/rolling branches preserve their semantics.
replace(
    combat,
    """                    homing && !is_scatter,
                    atk.crown_tower_damage_percent,""",
    """                    // M17: lock splash impact point at release, even when
                    // the projectile JSON flags homing (e.g. Wizard).
                    // Direct-hit projectiles keep following their target UID.
                    homing && !is_scatter && proj_splash <= 0,
                    atk.crown_tower_damage_percent,""",
    "shared splash point-lock vs direct-hit homing",
)
# Avoid conflating any ballistic projectile (gravity) with fixed guidance.
# The earlier gravity patch runs first and already separates the two.
replace(
    combat,
    """            // Update homing target position — but NOT for gravity-arc projectiles.
            // Gravity-arc projectiles (Fireball, Rocket, Arrows, Goblin Barrel, etc.)
            // fly to the fixed (target_x, target_y) computed at launch time. In real CR,
            // these land at the cast location — moving troops can dodge them.
            // Data-driven: is_gravity_arc is set from ProjectileStats.gravity > 0 at spawn.
            if proj.homing && !proj.is_gravity_arc {""",
    """            // M17: only UID-guided direct-hit projectiles update their
            // destination. Splash projectiles retain launch coordinates.
            // Gravity controls flight physics, not the destination policy.
            if proj.homing && proj.splash_radius <= 0 && !proj.is_gravity_arc {""",
    "flight guidance based on the authoritative projectile mode",
)

lib = ROOT / "lib.rs"
replace(
    lib,
    """    fn step_trace(&mut self, py: Python<'_>) -> PyResult<PyObject> {""",
    """    /// Synthetic fidelity probes only. Mutation is explicit and happens
    /// between ticks; no gameplay mechanism or per-card override uses it.
    fn debug_relocate_entity(&mut self, uid: u32, x: i32, y: i32) -> bool {
        if let Some(entity) = self.state.entities.iter_mut().find(|e|
            e.id.0 == uid && e.alive && matches!(&e.kind,
                EntityKind::Troop(_) | EntityKind::Building(_))
        ) {
            entity.x = x;
            entity.y = y;
            return true;
        }
        false
    }

    /// Synthetic death-between-release-and-impact fidelity probe.
    /// The next engine tick runs normal death processing and cleanup.
    fn debug_eliminate_entity(&mut self, uid: u32) -> bool {
        if let Some(entity) = self.state.entities.iter_mut().find(|e|
            e.id.0 == uid && e.alive && matches!(&e.kind,
                EntityKind::Troop(_) | EntityKind::Building(_))
        ) {
            entity.hp = 0;
            entity.alive = false;
            return true;
        }
        false
    }

    fn step_trace(&mut self, py: Python<'_>) -> PyResult<PyObject> {""",
    "controlled synthetic movement / elimination helpers",
)
replace(
    lib,
    """            row.set_item("active_projectiles", active_projectiles)?;
            row.set_item(
                "kind",""",
    """            row.set_item("active_projectiles", active_projectiles)?;
            if let EntityKind::Projectile(p) = &e.kind {
                row.set_item("projectile_source_uid", p.source_id.0)?;
                row.set_item("projectile_target_uid", p.target_id.0)?;
                row.set_item("projectile_homing", p.homing)?;
                row.set_item("projectile_guidance", if p.is_rolling {
                    "rolling"
                } else if p.is_boomerang {
                    "boomerang"
                } else if p.homing && p.splash_radius <= 0 {
                    "target_uid"
                } else {
                    "fixed_point"
                })?;
                row.set_item("projectile_destination_x", p.target_x)?;
                row.set_item("projectile_destination_y", p.target_y)?;
                row.set_item("projectile_splash_radius", p.splash_radius)?;
            }
            row.set_item(
                "kind",""",
    "Rust trace projectile trajectory/owner, including dead owners",
)
replace(
    lib,
    """                event.set_item("card_id", &e.card_key)?;
                event_rows.append(event)?;
                continue;""",
    """                event.set_item("card_id", &e.card_key)?;
                if let EntityKind::Projectile(p) = &e.kind {
                    event.set_item("source_uid", p.source_id.0)?;
                    event.set_item("target_uid", p.target_id.0)?;
                    event.set_item("destination_x", p.target_x)?;
                    event.set_item("destination_y", p.target_y)?;
                    event.set_item("homing", p.homing)?;
                    event.set_item("splash_radius", p.splash_radius)?;
                }
                event_rows.append(event)?;
                continue;""",
    "Rust launch event includes stable projectile destination and source",
)
print("M17/M18 shared projectile guidance contract installed.")
