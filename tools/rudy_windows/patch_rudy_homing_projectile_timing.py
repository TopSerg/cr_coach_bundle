#!/usr/bin/env python3
"""Separate projectile guidance from travel-time physics.

Some Royale projectiles are both gravity-affected and homing. Gravity therefore
cannot be used as a synonym for "fixed ballistic target". The correct shared
model is:
  * gravity controls travel-time / arc speed;
  * homing controls whether the projectile keeps tracking the target;
  * only non-homing gravity projectiles use fixed-point ballistic impact logic.

The gravity acceleration scale is calibrated once at the engine-unit level from
clean Crown-Tower projectile timings; it is not card- or scenario-specific.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
combat = ROOT / "combat.rs"
text = combat.read_text(encoding="utf-8")

GRAVITY_ACCEL_SCALE = "0.45"


def replace_once(old: str, new: str, label: str):
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    text = text.replace(old, new, 1)
    print(f"patched {label}")


# Generic troop/building ranged path: gravity determines travel time even for
# homing projectiles; homing itself remains an independent guidance flag.
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
            let proj_speed = if proj_gravity > 0 && dist_to_target > 0 {
                // Arc travel-time model is independent from guidance. A projectile
                // may follow this gravity-derived timing and still home onto a moving
                // target when its data says homing=true.
                let g_accel = (proj_gravity as f64) * ''' + GRAVITY_ACCEL_SCALE + ''';
                let travel_dist = dist_to_target as f64;
                let arc_ticks = (2.0 * travel_dist / g_accel.max(1.0)).sqrt().max(1.0);
                (travel_dist / arc_ticks) as i32
            } else {
                proj_data.map(|p| p.speed).unwrap_or(60)
            };
''',
"generic gravity travel-time independent from homing guidance",
)

# Fixed ballistic landing is only for non-homing gravity projectiles. Homing
# gravity projectiles keep tracking and merely use gravity-derived travel speed.
replace_once(
'''                        if pd.gravity > 0 {
                            p.is_gravity_arc = true;
                            p.homing = false; // Never track — fly to fixed (target_x, target_y)
                        }
''',
'''                        if pd.gravity > 0 && !pd.homing {
                            p.is_gravity_arc = true;
                            p.homing = false; // Fixed-point ballistic projectile.
                        }
''',
"separate fixed ballistic guidance from gravity travel time",
)

# Crown Tower adapter inserted by patch_rudy_tower_projectiles.py: same shared
# gravity travel-time model, while retaining the projectile's homing flag.
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
        let speed = if gravity > 0 && dist > 0 {
            let g_accel = (gravity as f64) * ''' + GRAVITY_ACCEL_SCALE + ''';
            let arc_ticks = (2.0 * dist as f64 / g_accel.max(1.0)).sqrt().max(1.0);
            ((dist as f64 / arc_ticks) as i32).max(60)
        } else {
            (raw_speed * 6 / 10).max(60)
        };
''',
"Crown Tower gravity travel-time with independent homing guidance",
)

combat.write_text(text, encoding="utf-8")
print(
    "Rudy patched: projectile gravity controls travel time, homing controls guidance; "
    f"gravity acceleration scale={GRAVITY_ACCEL_SCALE}."
)
