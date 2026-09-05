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
2. `tools/rudy_windows/patch_rudy_building_grid.py`
   - fixes building snapping for an even-width, centre-origin 18×32 arena;
   - legal tile centres are half-tile coordinates (`..., -1500, -500, 500, 1500, ...`);
   - prevents a requested Cannon `(500,5500)` from being silently moved to `(1000,6000)`.
3. `tools/rudy_windows/patch_rudy_building_deploy_targeting.py`
   - an under-deployment building can already be selected as a target/pull source;
   - its own movement/attack update is still blocked until `deploy_timer == 0`;
   - this matches the PRIMARY video, where Hog starts curving toward Cannon while the deployment clock is still visible.
4. `tools/rudy_windows/patch_rudy_troop_speed.py`
   - CR raw troop speed 45/60/90/120 becomes 0.9/1.2/1.8/2.4 tiles/s;
   - at 20 TPS and 1000 units/tile this is 45/60/90/120 internal units per tick.
5. `tools/rudy_windows/patch_rudy_attack_timing.py`
   - First Hit Speed is modeled separately from regular Load Time;
   - for Hog Rider: 1600 ms Hit Speed - 1000 ms Load Time = 600 ms first windup;
   - `load_first_hit` is not added as a second pre-hit cooldown.

Tournament-level card data is generated separately from `tournament11_profile.json` with `build_tournament_data.py`.

Do not compare a new fidelity result against old stock-Rudy coordinates/speeds before confirming all patches and the Tournament-11 overlay were applied.

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

The older scenarios in `scenarios.json` are separate historical probes and their placement coordinates remain estimates. In particular, do not use their old bridge-centred Hog coordinates as PRIMARY truth.

## Probe A — Hog solo → Princess Tower

Real fixture: `fixtures/real/hog_solo.json`.

Observed:

- 7 Hog hits;
- 317 damage per hit;
- hit times in the trimmed video: `8.06, 9.60, 11.20, 12.78, 14.46, 16.02, 17.62 s`;
- mean inter-hit interval ≈ `1.593 s`.

With the current patched Rudy + Tournament-11 data, this probe passes:

```text
hit count             7 == 7
damage                 317 == 317
mean hit interval      1.600 s vs 1.593 s
first hit after play   5.15 s vs 5.12 s
tower HP sequence      exact
```

This is the guard against re-breaking arena scale, troop speed, attack cadence, range and First Hit Speed while working on Cannon/pathing.

## Probe B — historical preplaced Cannon

Real fixture: `fixtures/real/hog_vs_cannon_preplaced.json`.

Its old simulator placement coordinates were estimated before the final 18×32/1000-unit geometry was established. Keep this probe as historical evidence, but remap its positions from video before using it as a hard current-engine pass/fail test.

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

The progression of the PRIMARY diagnosis was:

```text
cr-bot baseline first hit:                   5.70 s  (+1.40)
patched Rudy before grid/deploy-target fix:  4.70 s  (+0.40)
+ half-tile building grid:                   4.65 s  (+0.35)
+ building targetable during deployment:     4.30 s  (+0.00)
```

With all current patches, Rudy releases Hog attacks at 4.30 / 5.90 / 7.50 s. The third attack is lethal, so Cannon is removed on the same tick rather than producing another non-lethal HP-delta snapshot. Cannon death is 7.50 s and Hog death is 8.70 s, matching the video reference.

`run_primary_pathing.py` records:

- Hog/Cannon hit and death timestamps;
- Hog movement start;
- river entry / centre / exit and crossing duration;
- full Hog x/y path;
- turn angles near the river.

## River jump and bridge-corner probes

Hog Rider has `jump_enabled=true` in the Tournament-11 profile. Rudy exposes this as `can_jump_river`, so jump-capable troops bypass normal bridge routing.

In the PRIMARY trace Hog crosses open river rather than being forced onto a bridge:

```text
river enter   1.65 s  (x=1144, y=-960)
river centre  2.10 s  (x=1558, y=30)
river exit    2.55 s  (x=1814, y=1030)
crossing      0.90 s
```

The video shows the same qualitative behavior: Hog jumps across open water, not over the bridge deck. Rudy currently models this as x/y traversal with `z=0`; it does not yet model the visible airborne arc. That is acceptable for the current headless path/timing test, but must be revisited if airborne state changes targeting/collision semantics.

A separate non-jumper invariant probe places a Knight off-axis from a Cannon and checks bridge routing. Current result:

```text
entered river on bridge          PASS
never occupied open-water river  PASS
no river-edge bounce             PASS
crossed to enemy side            PASS
near-bank route turn             ~56°
far-bank route turn              ~53°
```

This confirms the waypoint topology and bridge lateral clamp are working. The exact corner curvature/turn angle is not yet calibrated against a real-video non-jumper reference.

## Running

The reproducible CI path is:

```text
.github/workflows/rudy-primary-pathing.yml
```

It checks out pinned Rudy, applies all engine patches, builds and installs it, creates the Tournament-11 data overlay, runs the historical probes, then runs PRIMARY + river/bridge diagnostics.

Local legacy runner:

```bash
/path/to/cr_hog_fidelity_test/run_all.sh .
```

A non-zero comparator result means **fidelity divergence**, not necessarily a harness failure.

## Harness self-test

```bash
python -m pytest tests/test_compare.py
```

The synthetic fixture validates the comparator only; it is not a simulator result.
