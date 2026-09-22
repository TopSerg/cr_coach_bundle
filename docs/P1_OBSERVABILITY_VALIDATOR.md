# P-1 Observability + Unified Validator

P-1 adds observability only. Gameplay semantics are intentionally unchanged.

## Authoritative Rudy trace

The patched Rust extension exposes `Match.step_trace()`. Each call advances the real Rudy engine by one 20 Hz tick and returns:

- `tick`
- `entities[]`
- `events[]`

Each entity row contains at least:

`tick, uid, card_id, team, x, y, vx, vy, hp, shield_hp, movement_state, target_uid, target_locked, combat_phase, windup_remaining, cooldown_remaining, load_progress, active_statuses, charge_state, path_target, current_waypoint, active_projectiles`.

`vx/vy` are computed inside Rust from authoritative pre/post GameState positions for that engine tick. They are in Rudy internal units per second.

`current_waypoint` is currently `null`: Rudy recomputes bridge routing and does not persist a waypoint as authoritative state. P-1 deliberately does not invent it in Python.

## Event trace

Rust emits tick-precise state transition events where authoritative runtime state exists:

- `TARGET_ACQUIRED`
- `TARGET_DROPPED`
- `TARGET_CHANGED`
- `PATH_REBUILT` (currently target-change driven)
- `CHARGE_STARTED`
- `CHARGE_RESET`
- `ATTACK_WINDUP_STARTED`
- `MELEE_HIT`
- `PROJECTILE_SPAWN`
- `PROJECTILE_HIT`
- `STUN_APPLIED`
- `STUN_EXPIRED`
- `DAMAGE`
- `DEATH`
- `SPAWN`

`JUMP_STARTED/JUMP_LANDED` and `KNOCKBACK_STARTED/KNOCKBACK_ENDED` are reserved by the P-1 schema but are not fabricated yet because pinned Rudy does not currently store a persistent authoritative river-jump/knockback state. Those events must be wired when those mechanics gain explicit runtime states in P1/P2.

## Unified validator

`validate_mechanics.py` is the single file-level entry point:

```bash
python validate_mechanics.py \
  --reference reference.json \
  --snapshots snapshots.jsonl \
  --events events.jsonl \
  --out report.json
```

References are partial: only fields written in the reference are compared. Extra simulator fields are allowed.

The report contains:

- `passed`
- `first_divergence`
- `first_divergence.tick`
- `first_divergence.subsystem`
- `last_exact_tick`

This supports both synthetic M-gates and sparse physical/video references.

## CI gate

`.github/workflows/build-rudy-arena18x32-windows.yml` now:

1. applies all production Rudy patches;
2. applies `patch_rudy_p1_observability.py`;
3. builds the Rust/PyO3 wheel with maturin;
4. executes `tools/p1_observability_smoke.py`;
5. runs the P-1 validator tests;
6. reruns the existing Solo Hog + Hog/Cannon/Princess fidelity gates and user-facing Rudy replay checks.

P-1 is accepted only if this Windows build is green.
