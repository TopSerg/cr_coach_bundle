#!/usr/bin/env python3
"""Guard the shared combat-geometry contract without changing the accepted baseline.

Run #34 proved that blindly adding attacker+target collision radii to every
ranged attack double-counts projectile/tower range. Run #35 proved that changing
Crown Tower cooldown cadence in isolation also regresses already-matched video
scenarios because tower release, projectile flight and impact are still collapsed
into one subsystem.

Until the ranged projectile pipeline is unified, this patch intentionally keeps:
  * the validated troop/Hog body-gap geometry from patch_rudy_arena_18x32.py;
  * building/projectile source ranges unchanged;
  * the accepted Crown Tower timing baseline unchanged.

The architectural fix will be introduced only together with projectile
release/flight/impact so the existing regression guards remain authoritative.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"

combat = ROOT / "combat.rs"
text = combat.read_text(encoding="utf-8")

# Fail loudly if the pinned Rudy source changes underneath the assumptions that
# our next projectile patch depends on.
required = [
    "pub fn tick_combat(state: &mut GameState, data: &GameData)",
    "pub fn tick_projectiles(state: &mut GameState, data: &GameData)",
    "pub fn tick_towers(state: &mut GameState)",
    "if atk.is_ranged",
    "bld.is_ranged",
]
missing = [needle for needle in required if needle not in text]
if missing:
    raise RuntimeError(f"Pinned Rudy combat structure changed; missing: {missing}")

print(
    "Rudy unified-combat guard: keep validated baseline geometry/tower timing; "
    "projectile unification pending diagnostics."
)
