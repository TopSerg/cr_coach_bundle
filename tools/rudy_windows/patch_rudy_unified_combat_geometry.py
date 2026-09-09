#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


combat = ROOT / "combat.rs"

# ---------------------------------------------------------------------------
# Shared combat-range semantics.
#
# Raw CR data contains two different geometric meanings:
#   * melee/body-gap attacks: attack distance is the gap between physical bodies;
#     Rudy therefore needs base_range + attacker_radius + target_radius.
#   * ranged/projectile attacks: the raw CharacterStats/Building range is already
#     the centre-origin firing envelope (PrincessTower=7500, Cannon=5500).
#     Adding body radii again double-counts their size.
#
# Keep this distinction global by attack mode, never by card name.
# ---------------------------------------------------------------------------
marker = """// =========================================================================
// Snapshot types for borrow-safe targeting
// =========================================================================
"""
helper = """// =========================================================================
// Shared combat geometry
// =========================================================================

#[derive(Clone, Copy)]
enum AttackRangeMode {
    /// Melee/contact attack: data range is the allowed gap between body edges.
    BodyGap,
    /// Ranged/projectile attack: data range is already the centre-origin envelope.
    CenterRange,
}

#[inline]
fn effective_attack_range_sq(
    base_range_sq: i64,
    attacker_collision_radius: i64,
    target_collision_radius: i64,
    mode: AttackRangeMode,
) -> i64 {
    match mode {
        AttackRangeMode::CenterRange => base_range_sq.max(0),
        AttackRangeMode::BodyGap => {
            let base_range = (base_range_sq.max(0) as f64).sqrt() as i64;
            let effective_range = base_range
                + attacker_collision_radius.max(0)
                + target_collision_radius.max(0);
            effective_range * effective_range
        }
    }
}

// =========================================================================
// Snapshot types for borrow-safe targeting
// =========================================================================
"""
replace_once(combat, marker, helper, "shared attack-range modes")

# The existing arena patch already made troop movement/body contact edge-aware.
# Route that calculation through the common primitive.  Hog and other melee
# building-targeters therefore keep the exact geometry already verified by video.
replace_once(
    combat,
    """            let base_range = (range_sq as f64).sqrt() as i64;
            let effective_range = base_range
                + my_radius.max(0) as i64
                + target_radius.max(0) as i64;
            if dx * dx + dy * dy <= effective_range * effective_range {
                continue;
            }""",
    """            let effective_range_sq = effective_attack_range_sq(
                range_sq,
                my_radius.max(0) as i64,
                target_radius.max(0) as i64,
                AttackRangeMode::BodyGap,
            );
            if dx * dx + dy * dy <= effective_range_sq {
                continue;
            }""",
    "troop movement shared body-gap range",
)

# Same refactor for troop combat.  We intentionally preserve the currently
# verified body-gap semantics here; a later ranged-troop regression fixture can
# switch projectile troops to CenterRange without touching card-specific code.
replace_once(
    combat,
    """                let base_attack_range = (troop.range_sq as f64).sqrt() as i64;
                let effective_attack_range = base_attack_range
                    + attacker_collision_radius
                    + target_snap.collision_radius.max(0) as i64;
                let effective_attack_range_sq = effective_attack_range * effective_attack_range;""",
    """                let effective_attack_range_sq = effective_attack_range_sq(
                    troop.range_sq,
                    attacker_collision_radius,
                    target_snap.collision_radius.max(0) as i64,
                    AttackRangeMode::BodyGap,
                );""",
    "troop combat shared body-gap range",
)

# Ranged buildings (Cannon/Tesla/etc.) and Crown Towers keep their raw range.
# This is not a special-case: their projectile attacks already use centre-origin
# ranges in the source data.  In particular PrincessTower has range=7500 and
# collision_radius=1000, while its public range is 7.5 tiles; adding 1000 would
# be a second application of tower size.
#
# The original building and tower checks therefore remain centre-distance checks.

# Tower cooldowns were sampled before decrementing, turning a configured
# 16-tick / 0.80 s interval into 17 ticks / 0.85 s.  Use the same global reload
# ordering as attacking buildings: advance reload first, then sample readiness.
replace_once(
    combat,
    """    for player_team in [Team::Player1, Team::Player2] {
        let enemy_team = player_team.opponent();

        // Extract tower info: (x, y, range, damage, ready, tower_id)""",
    """    for player_team in [Team::Player1, Team::Player2] {
        // Advance reload before readiness is sampled. This makes an N-tick
        // Hit Speed produce an exact N-tick release-to-release period.
        {
            let player = state.player_mut(player_team);
            if player.princess_left.alive && player.princess_left.attack_cooldown > 0 {
                player.princess_left.attack_cooldown -= 1;
            }
            if player.princess_right.alive && player.princess_right.attack_cooldown > 0 {
                player.princess_right.attack_cooldown -= 1;
            }
            if player.king.alive && player.king.activated && player.king.attack_cooldown > 0 {
                player.king.attack_cooldown -= 1;
            }
        }

        let enemy_team = player_team.opponent();

        // Extract tower info: (x, y, range, damage, ready, tower_id)""",
    "tower exact attack-cycle update order",
)

replace_once(
    combat,
    """        // Tick all tower cooldowns (independent of whether they fired)
        let player = state.player_mut(player_team);
        if player.princess_left.alive {
            if player.princess_left.attack_cooldown > 0 {
                player.princess_left.attack_cooldown -= 1;
            }
        }
        if player.princess_right.alive {
            if player.princess_right.attack_cooldown > 0 {
                player.princess_right.attack_cooldown -= 1;
            }
        }
        if player.king.alive && player.king.activated {
            if player.king.attack_cooldown > 0 {
                player.king.attack_cooldown -= 1;
            }
        }
""",
    "",
    "remove post-readiness tower cooldown tick",
)

print("Rudy patched: shared body-gap/center-range model and exact Crown Tower cadence.")
