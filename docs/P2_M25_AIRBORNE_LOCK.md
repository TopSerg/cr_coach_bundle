# P2 M25 — Airborne target-lock continuity (2026-10-13)

**Source:** explicit user clarification of Clash Royale jump semantics, plus the
existing P1 `RiverJumpPhase` / targeting contract.

## Required rules

A river-jumping ground troop becomes **AIRBORNE** for target eligibility.
Target selection is not globally reset just because a jump began:

* An attacker with `attacks_air = false` (Cannon) must invalidate its
  `target_uid` on takeoff and can acquire another eligible ground target.
* An attacker with `attacks_air = true` (Inferno Tower, Musketeer) preserves a
  valid sticky target throughout the jump, subject to ordinary range, death
  and other reset conditions.
* Inferno Tower must retain `ramp_target_uid` and `ramp_ticks` while its lock
  remains valid and the target remains in attack range. It should not restart
  stage 1 merely because the target briefly changed gameplay plane.

## Discovered processing-order bug

Current Rudy runs `tick_targeting` before `tick_movement`.
P1 updates `RiverJumpPhase` after movement and before combat. On the first
airborne tick, a previously locked ground-only attacker could therefore
attack a newly airborne target using its stale `target_uid`.

`tools/rudy_windows/patch_rudy_p2_m25_airborne_targeting.py` changes the
shared `tick_river_jumps` helper to return whether any troop crossed
GROUND ⇄ AIRBORNE. **Only if the gameplay plane changed** does it run the
existing data-driven `tick_targeting` again before combat. This performs
ordinary eligibility/lock handling and leaves valid Inferno targets intact.

No card identifiers, damage statistics, cooldowns or projectile logic are
special-cased.

## Synthetic acceptance gates

Run against the same patched Rust wheel as historical Hog/Cannon regressions:

```powershell
python tools/m25_airborne_lock_smoke.py
```

The two tests use the same Hog path and an already-deployed Knight that enters
sight after the first lock, but before takeoff.

1. **M12**: Cannon first locks Hog, then changes target to Knight on the exact
   `JUMP_STARTED` tick, recorded by `TARGET_CHANGED`. Cannon never keeps
   the airborne Hog as its target.
2. **M25**: Inferno Tower first locks Hog and starts ramping. After takeoff,
   `target_uid` and `ramp_target_uid` remain Hog, `ramp_ticks` never resets
   and continues increasing. No `TARGET_CHANGED/DROPPED` on takeoff.

**Current status:** synthetic gate only, until CI passes. **PHYSICAL VERIFIED:
false** until a current-patch, timestamped real-game recording confirms
timing, beam continuity and target switching.

Next edge cases to validate independently: no replacement ground target,
Inferno target leaving range mid-jump, stun overlapping takeoff, already-fired
Cannon projectile versus airborne Hog, and post-landing reacquisition.
