# Hog fidelity probes for cr-rudy-sim

This package turns the recorded Clash Royale Hog demos into reproducible differential tests against **cr-rudy-sim**.

## Important: patched Rudy baseline

The CR Coach Rudy build is intentionally not stock upstream Rudy. The current build pipeline applies, in order:

1. `tools/rudy_windows/patch_rudy_arena_18x32.py`
   - arena 18 × 32 tiles;
   - 1000 internal units per tile;
   - river Y = -1000..+1000;
   - bridge centres X = ±5500, half-width 1500;
   - Princess Tower centres at X = ±5500, Y = ±9500;
   - edge-to-edge attack/stop range using collision radii;
   - one-tick attack-cycle correction so source Hit Speed is preserved.
2. `tools/rudy_windows/patch_rudy_troop_speed.py`
   - CR raw troop speed 45/60/90/120 becomes 0.9/1.2/1.8/2.4 tiles/s;
   - at 20 TPS and 1000 units/tile this is 45/60/90/120 internal units per tick.
3. `tools/rudy_windows/patch_rudy_attack_timing.py`
   - First Hit Speed is modeled separately from regular Load Time;
   - for Hog Rider: 1600 ms Hit Speed - 1000 ms Load Time = 600 ms first windup;
   - `load_first_hit` is not added as a second pre-hit cooldown.

Tournament-level card data is generated separately from `tournament11_profile.json` with `build_tournament_data.py`.

Do not compare a new fidelity result against old stock-Rudy coordinates/speeds before confirming these patches and the Tournament-11 overlay were applied.

## Coordinate systems

Patched Rudy uses centre-origin coordinates:

- X = -9000 .. +9000;
- Y = -16000 .. +16000;
- one tile = 1000 units.

For an 18×32 top-left-origin arena cell `(col,row)`, the cell-centre conversion used by the PRIMARY probe is:

```text
x = (col - 8.5) * 1000
y = (15.5 - row) * 1000
```

Thus the manual PRIMARY mapping currently stored in
`physical_tests/references/d03_hog_cannon_02_primary.json` becomes:

```text
Hog    cell (9,18) -> Rudy ( 500,-2500)
Cannon cell (9,10) -> Rudy ( 500, 5500)
```

The older scenarios in `scenarios.json` are separate historical probes and their placement coordinates remain estimates.

## Probe A — Hog solo → Princess Tower

Real fixture: `fixtures/real/hog_solo.json`.

Observed:

- 7 Hog hits;
- 317 damage per hit;
- hit times in the trimmed video: `8.06, 9.60, 11.20, 12.78, 14.46, 16.02, 17.62 s`;
- mean inter-hit interval ≈ `1.593 s`.

The exact placement is still an estimate and may be grid-searched without changing engine mechanics.

## Probe B — Hog vs preplaced Cannon

Real fixture: `fixtures/real/hog_vs_cannon_preplaced.json`.

Observed:

- Cannon exists before Hog chooses its first target;
- Hog is pulled to Cannon;
- protected Princess Tower remains `3052 -> 3052`;
- Cannon disappears before Hog;
- visual death-time gap ≈ `0.15 s`.

This is an initial building-pull/pathing probe.

## Probe C — PRIMARY dynamic Cannon

Real reference: `physical_tests/references/d03_hog_cannon_02_primary.json`.

Relative to Hog play:

```text
Cannon play:       2.45 s
Hog hit #1:        4.30 s
Hog hit #2:        5.90 s
Hog hit #3:        7.50 s
Cannon death:      7.50 s
Hog death:         8.70 s
```

`run_primary_pathing.py` replays those action timings on patched Rudy and records:

- Hog/Cannon hit and death timestamps;
- Hog movement start;
- river entry / centre / exit and crossing duration;
- full Hog x/y path;
- turn angles near the river.

This probe is specifically intended to distinguish combat timing from geometry/pathing errors.

## River jump and bridge-corner probes

Hog Rider has `jump_enabled=true` in the Tournament-11 profile. Upstream Rudy exposes this as `can_jump_river`, so jump-capable troops skip normal bridge routing. The PRIMARY trace therefore records whether Hog traverses the river at the expected x/y and timing rather than silently assuming bridge pathing.

A separate non-jumper invariant probe places a Knight off-axis from a Cannon and checks that it:

- reaches a bridge before entering the river;
- never occupies open-water coordinates inside the river;
- does not bounce back to its own bank;
- exits onto the enemy side;
- records its heading change around the bridge entry/exit.

This catches regressions in waypoint routing and the bridge lateral clamp independently of Hog's jump ability.

## Running

The most reproducible path is GitHub Actions:

```text
.github/workflows/rudy-primary-pathing.yml
```

It checks out the pinned Rudy source, applies all engine patches, builds and installs the wheel, creates the Tournament-11 data overlay, runs the older fidelity probes, then runs PRIMARY + river/bridge diagnostics.

Local legacy runner:

```bash
/path/to/cr_hog_fidelity_test/run_all.sh .
```

A non-zero comparator result means **fidelity divergence**, not necessarily a harness failure.

## Pass criteria for the older probes

Hog solo:

- damage per hit: exact;
- hit count: exact;
- complete tower HP sequence: exact;
- mean hit interval: ±0.10 s;
- first hit after deployment estimate: ±0.30 s.

Cannon:

- protected tower damage: exactly zero;
- Cannon dies before Hog;
- death-time gap: ±0.15 s.

The PRIMARY probe reports raw event deltas so we can fix the **first divergence** instead of tuning to the final result.

## Harness self-test

```bash
python -m pytest tests/test_compare.py
```

The synthetic fixture validates the comparator only; it is not a simulator result.
