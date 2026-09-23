# P0 core mechanics gates

P0 covers `M01`, `M02`, `M04`, `M06`–`M10`, `M38`, and `M39` without replacing
Rudy gameplay systems. The gate runner consumes `Match.step_trace()`; target,
path, deployment, collision, combat, and Crown Tower state all originate in
Rust.

## Run

After building the patched Rudy wheel and Tournament-11 data overlay:

```bash
python tools/p0_core_gates.py \
  --data-dir outputs/rudy_tournament11_data \
  --out-dir outputs/p0_core
```

Run selected gates with `--only M01 M04`. `--no-strict` is diagnostic mode:
reports are still written, but a divergence does not fail the process.

Each gate writes the common bundle:

```text
outputs/p0_core/m01/
  trace.jsonl
  events.jsonl
  report.json
```

`summary.json` is the single CI result. On failure it contains:

```json
{
  "passed": false,
  "first_divergence": {
    "gate": "M08",
    "tick": 37,
    "subsystem": "TARGETING",
    "expected": 12,
    "actual": 14,
    "last_exact_tick": 36
  }
}
```

## Authoritative additions

`patch_rudy_p0_core_observability.py` adds no update logic. It exposes:

- entity `collision_radius` and `deploy_timer` for M01/M39;
- Crown Towers as trace rows, including their real `attack_target` and cooldown;
- exact TowerState `TARGET_ACQUIRED`, `TARGET_DROPPED`, and `TARGET_CHANGED`
  transitions for M38.

The placement patch now selects the legal lattice from deployment footprint:
ordinary odd-footprint buildings remain on tile centres; Tesla and Goblin Drill
use tile intersections. Collision radius remains a separate combat/pathing
quantity.

## Evidence status

The deterministic suite proves simulator invariants. It does not manufacture
real-game truth. The three historical Hog/Cannon references used by M10/M39
remain `CANDIDATE`; M02 still needs a current-patch annotated trajectory before
its `p95 <= 0.25 tile` physical criterion can become `VERIFIED`. The evidence
registry is `physical_tests/references/p0_manifest.json`.

The existing Solo Hog and Hog/Cannon/Princess video regressions run in the same
workflow after the P0 gates and must remain green.
