# P1 — Air, River Jump, Combat: implementation and gates

Status: **synthetic implementation in progress; not physical VERIFIED**.
Source: [CORE_MECHANICS_VALIDATION_SPEC_RU.md](CORE_MECHANICS_VALIDATION_SPEC_RU.md).
Backend: pinned Rudy 050275d70b84614953877e8075dc4b8ba907c67f plus existing production patches and P-1 observability.

## Rust change

The script tools/rudy_windows/patch_rudy_p1_river_jump.py runs after patch_rudy_p1_observability.py and patches the pinned upstream without vendoring Rudy.

- Adds RiverJumpPhase (None → Approaching → Airborne → Landing → None) and stores phase, start/land coordinates and exact ticks on TroopData. Jump and dash are independent.
- tick_river_jumps() updates state after movement and before collisions/combat. Crossing on a bridge is not a jump.
- During Airborne, Entity::is_flying() returns true for the jumper; shared targeting, spell filtering and projectile logic see an air-layer target.
- Rust Match.step_trace() exports jump_state, jump_start_tick/x/y and jump_land_tick/x/y. JUMP_STARTED/LANDED are emitted from actual phase transitions.
- Stun/freeze invalidates sticky target generically; no new target is acquired while immobilized. Existing combat logic interrupts attacks and resets charge; P1 clears Inferno ramp lock as well as ramp ticks.
- Common melee timing, projectile lifecycle and basic stun mechanics remain in existing Rudy pipelines unless a concrete divergence is found.

This is a conservative synthetic baseline, NOT verified live behavior. Airborne onset/landing currently track the river band rather than physically measured animation offsets. In particular Inferno-lock continuity over river jump requires a real current-patch experiment.

## P1 gate matrix

| Gate | Status | Synthetic check |
|---|---|---|
| M03 | SYNTHETIC | Air unit travels over open river without bridge detour |
| M05 | SYNTHETIC | Balloon selects buildings over troops |
| M11 | SYNTHETIC | Jump state, start/landing events, tick/x/y |
| M12 | SYNTHETIC | Ground-only target filtering vs airborne and air-capable acquisition |
| M14 | SYNTHETIC | Melee windup, impact, damage |
| M15 | SYNTHETIC | First hit/cadence order |
| M16 | SYNTHETIC | Ranged projectile spawn, hit, damage |
| M17 | PENDING | Moving-target projectile model requires controlled experiment |
| M18 | PENDING | Shooter death after projectile release requires controlled experiment |
| M21 | SYNTHETIC | Stun applied and expired |
| M22 | SYNTHETIC | Stun drops and reacquires target |
| M23 | SYNTHETIC | Inferno ramp reset after Zap; further card coverage pending |

Run the P1 smoke gate on the same patched Windows wheel as the existing physical regressions:
- python tools/p1_observability_smoke.py
- python tools/p1_mechanics_smoke.py

CI: .github/workflows/build-rudy-arena18x32-windows.yml.

## Physical verification required

Each M03/M05/M11/M12/M14–M18/M21–M23 still needs a current-patch, tick-annotated Friendly Battle reference with card/tick/x/y and relevant observations. Compare with validate_mechanics.py using --reference, --snapshots, --events. The existing Hog/Cannon/Princess reference suite protects old behavior but does not prove P1 fidelity.

Mark VERIFIED only after synthetic + real video agree with exact event order, damage/target identity and specified tolerance (timing ≤100 ms, trajectory p95 ≤0.25 tile where applicable). Never mark a physical gate VERIFIED solely on a synthetic pass.


## M17/M18 clarified gameplay contract (2026-10-08)

User reference (synthetic target behavior, awaiting numerical current-patch video):
- **Direct-hit projectile** (Musketeer, Sparky, Minions): after release its target UID remains locked and the destination updates every tick to that entity's authoritative current position. This is independent of the source troop's subsequent target choices.
- **Splash projectile** (Wizard, Bowler, Princess): impact center is the exact launch-time destination; moving the aimed target away must not drag the impact point. Splash damage is resolved for all entities intersecting the radius *at impact* (not at release).
- **Shooter death (M18):** after release the projectile remains an independently owned entity; removing its shooter cannot delete the projectile. Existing source UID, target UID, guidance mode and launch destination remain observable. The projectile persists until its normal impact/resolution.
- These are independent of gravity: arc/travel-time and guidance are separate parameters. Rolling, scatter and boomerang mechanics continue using their specialized paths.

Implemented in tools/rudy_windows/patch_rudy_m17_m18_projectile_contract.py and asserted in tools/m17_m18_projectile_smoke.py. The synthetic probes explicitly relocate the moving target and eliminate the shooter **between simulation ticks** after projectile spawn, rather than deriving results from approximate Python positions. They make no claim about unexplored cases like the target itself dying or leaving the arena before impact.

M17 and M18 status becomes **SYNTHETIC** after the Windows CI gate succeeds; **PHYSICAL VERIFIED remains false** until current-patch video fidelity acceptance.
