#!/usr/bin/env python3
"""Make projectile travel semantics data-driven by homing, not gravity alone.

Royale data frequently sets both gravity>0 and homing=true for visual-arc arrows
(e.g. ArcherArrow and TowerPrincessProjectile). Treating every gravity projectile
as a fixed ballistic arc makes those homing arrows artificially slow and also
forces them non-homing. A true ballistic timing path is appropriate only when the
projectile is non-homing.

This patch is global: no card names or scenario-specific constants.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
combat = ROOT / "combat.rs"
text = combat.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str):
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    text = text.replace(old, new, 1)
    print(f"patched {label}")


# Generic troop/building ranged path.
replace_once(
'''            let proj_gravity = proj_data.map(|p| p.gravity).unwrap_or(0);
            let proj_speed = if proj_gravity > 0 && dist_to_target > 0 {
                // Parabolic arc: t = sqrt(2 * distance / gravity_accel).
                // gravity in data units (e.g., 40). Scale factor converts data gravity
                // to internal-units/tick²: gravity * 0.3
                let g_accel = (proj_gravity as f64) * 0.3;
                let travel_dist = dist_to_target as f64;
                let arc_ticks = (2.0 * travel_dist / g_accel.max(1.0)).sqrt().max(1.0);
                (travel_dist / arc_ticks) as i32
            } else {
                proj_data.map(|p| p.speed).unwrap_or(60)
            };
            let homing = proj_data.map(|p| p.homing).unwrap_or(true);
''',
'''            let proj_gravity = proj_data.map(|p| p.gravity).unwrap_or(0);
            let homing = proj_data.map(|p| p.homing).unwrap_or(true);
            let proj_speed = if proj_gravity > 0 && !homing && dist_to_target > 0 {
                // True non-homing ballistic arc: t = sqrt(2 * distance / gravity_accel).
                let g_accel = (proj_gravity as f64) * 0.3;
                let travel_dist = dist_to_target as f64;
                let arc_ticks = (2.0 * travel_dist / g_accel.max(1.0)).sqrt().max(1.0);
                (travel_dist / arc_ticks) as i32
            } else {
                // Homing projectiles use their explicit speed even when gravity is
                // present for visual arc metadata.
                proj_data.map(|p| p.speed).unwrap_or(60)
            };
''',
"generic homing-vs-ballistic travel timing",
)

replace_once(
'''                        if pd.gravity > 0 {
                            p.is_gravity_arc = true;
                            p.homing = false; // Never track — fly to fixed (target_x, target_y)
                        }
''',
'''                        if pd.gravity > 0 && !pd.homing {
                            p.is_gravity_arc = true;
                            p.homing = false; // True ballistic projectile: fixed landing point.
                        }
''',
"do not force homing visual-arc projectiles non-homing",
)

# Crown Tower release adapter inserted by patch_rudy_tower_projectiles.py.
replace_once(
'''        let raw_speed = pd.map(|p| p.speed).unwrap_or(600);
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
''',
'''        let raw_speed = pd.map(|p| p.speed).unwrap_or(600);
        let gravity = pd.map(|p| p.gravity).unwrap_or(0);
        let homing = pd.map(|p| p.homing).unwrap_or(true);
        let dx = (atk.target_x - atk.from_x) as i64;
        let dy = (atk.target_y - atk.from_y) as i64;
        let dist = ((dx * dx + dy * dy) as f64).sqrt() as i32;
        let speed = if gravity > 0 && !homing && dist > 0 {
            let g_accel = (gravity as f64) * 0.3;
            let arc_ticks = (2.0 * dist as f64 / g_accel.max(1.0)).sqrt().max(1.0);
            ((dist as f64 / arc_ticks) as i32).max(60)
        } else {
            (raw_speed * 6 / 10).max(60)
        };
''',
"Crown Tower homing projectile travel timing",
)

combat.write_text(text, encoding="utf-8")
print("Rudy patched: gravity changes travel time only for non-homing ballistic projectiles.")
