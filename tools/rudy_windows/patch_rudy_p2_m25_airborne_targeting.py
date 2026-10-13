#!/usr/bin/env python3
"""M12/M25: reconcile target eligibility immediately after river-jump plane changes.

The shared targeting pipeline already filters current locks by attacks_ground /
attacks_air. However, it runs before troop movement, while P1 changes an
entity's jump phase AFTER movement. Without a second, transition-only pass,
ground-only defenders can attack a freshly airborne target in the same tick.

No per-card branches: rerun normal target selection ONLY on an actual
ground/air eligibility transition. Inferno's valid air-capable sticky lock and
ramp remain untouched; Cannon's now-invalid lock is released immediately.
"""
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2] / "third_party"
    / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
)


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    data = path.read_text(encoding="utf-8")
    if new in data:
        print("Already patched:", label)
        return
    count = data.count(old)
    if count != 1:
        raise RuntimeError(f"M25 {label}: expected one marker, got {count}")
    path.write_text(data.replace(old, new, 1), encoding="utf-8")
    print("Patched:", label)


combat = ROOT / "combat.rs"
replace_once(
    combat,
    "pub fn tick_river_jumps(state: &mut GameState) {\n"
    "    for entity in &mut state.entities {",
    "pub fn tick_river_jumps(state: &mut GameState) -> bool {\n"
    "    let mut eligibility_changed = false;\n"
    "    for entity in &mut state.entities {",
    "return whether a troop changed ground/air target eligibility",
)
replace_once(
    combat,
    """        if let EntityKind::Troop(t) = &mut entity.kind {
            if next == crate::entities::RiverJumpPhase::Airborne""",
    """        // A phase change between ground and airborne changes which
        // attackers may legally retain this troop as a target.
        if (phase == crate::entities::RiverJumpPhase::Airborne)
            != (next == crate::entities::RiverJumpPhase::Airborne) {
            eligibility_changed = true;
        }
        if let EntityKind::Troop(t) = &mut entity.kind {
            if next == crate::entities::RiverJumpPhase::Airborne""",
    "detect only actual target-plane transitions",
)
replace_once(
    combat,
    """            t.river_jump_phase = next;
        }
    }
}

/// Run movement for all troops.""",
    """            t.river_jump_phase = next;
        }
    }
    eligibility_changed
}

/// Run movement for all troops.""",
    "propagate eligibility transition result",
)

engine = ROOT / "engine.rs"
replace_once(
    engine,
    """    combat::tick_river_jumps(state);
""",
    """    if combat::tick_river_jumps(state) {
        // Eligibility changed AFTER the ordinary pre-movement targeting pass.
        // Re-run the same data-driven targeting rules before any attack:
        // ground-only attackers must drop airborne targets immediately;
        // air-capable sticky locks and Inferno ramp remain intact.
        combat::tick_targeting(state);
    }
""",
    "recheck locks on jump takeoff/landing before combat",
)
print("P2 M25 shared airborne target-lock reconciliation installed.")
