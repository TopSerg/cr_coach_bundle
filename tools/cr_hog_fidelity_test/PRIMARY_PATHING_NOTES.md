# PRIMARY Hog/Cannon pathing notes

This note records the hypotheses that the automated probe is meant to test. It is not treated as engine truth.

## Real-video observations

The PRIMARY clip (`d03_hog_cannon_02_PRIMARY`, source 89.5–103.0 s) shows Hog deployed immediately below the river. During the approach it crosses the river away from the bridge deck, consistent with Hog Rider's river-jump capability. The visible sequence is approximately:

- Hog play: 91.50 s (reference anchor)
- movement/deploy completion: around 92.5–92.6 s
- take-off toward/open river: around 92.8 s
- airborne/crossing frames: roughly 93.0–93.4 s
- landing on enemy side: around 93.6 s

These jump sub-timestamps are visual estimates only; the authoritative combat timestamps remain in `physical_tests/references/d03_hog_cannon_02_primary.json`.

## Geometry hypothesis

The existing manual 18×32 cell mapping in the PRIMARY reference is:

- Hog `(9,18)`
- Cannon `(9,10)`

Using patched Rudy's 1000-unit, centre-origin geometry this maps to:

- Hog `(500,-2500)`
- Cannon `(500,5500)`

This is materially different from the older historical Hog fidelity scenarios that place Hog at X=±5500 near a bridge centre. Those scenarios should not be reused as PRIMARY geometry.

## What the new probe separates

1. deployment/movement start;
2. river traversal and jump-capable routing;
3. Cannon timing and building pull;
4. first Hog hit and subsequent 1.6 s cadence;
5. Cannon/Hog death order;
6. non-jumper bridge waypoint routing and cornering.

If hit cadence is correct but first hit remains late, inspect path length, stop distance, target collision radius and the jump/crossing trajectory before changing Hit Speed.
