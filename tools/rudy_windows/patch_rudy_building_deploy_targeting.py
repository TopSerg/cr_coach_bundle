#!/usr/bin/env python3
"""Make deployed buildings targetable during their deployment countdown.

PRIMARY Hog/Cannon video shows Hog beginning the pull while Cannon's deployment
clock is still visible. Stock Rudy's Entity::is_targetable() returns false for
all entities with deploy_timer > 0, so the building is invisible to targeting
for its entire one-second deploy.

Patch only target snapshots: an under-deployment building may be selected and
moved toward, but its own update/attack logic still observes deploy_timer and
cannot fire early.
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

old = """            targetable: e.is_targetable(),
            is_invisible: e.is_invisible(),"""
new = """            // Real CR building placement can pull building-targeting troops
            // while the building's deployment clock is still running. Keep normal
            // targetability for everything else; acting/attacking still remains
            // blocked by deploy_timer in the engine update path.
            targetable: if e.is_building() && e.alive && e.deploy_timer > 0 {
                true
            } else {
                e.is_targetable()
            },
            is_invisible: e.is_invisible(),"""

text = COMBAT.read_text(encoding="utf-8")
count = text.count(old)
if count != 1:
    raise RuntimeError(f"building deploy targeting: expected exactly one match in {COMBAT}, found {count}")
COMBAT.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched building deploy targeting: buildings can pull troops before deploy completes")
