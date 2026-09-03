# First real test checklist

## Test 0 — environment
- [ ] upstream/cr-bot cloned
- [ ] upstream/clash-royale-ai cloned
- [ ] cr-bot tests/smoke run
- [ ] recorded video can be processed by cr-bot/KataCR
- [ ] canonical replay schema imports

## Test 1 — coordinate calibration
Record/label placements near:
- [ ] left bridge
- [ ] right bridge
- [ ] bottom-left legal cell
- [ ] bottom-right legal cell
- [ ] top-left (opponent) equivalent
- [ ] top-right equivalent

Output: `coordinate_calibration.json`.

## Test 2 — Hog only
Known action, no CV action extraction.
Measure:
- [ ] spawn/deploy timestamp
- [ ] trajectory
- [ ] bridge crossing
- [ ] target acquire
- [ ] first tower hit
- [ ] repeated hit timing
- [ ] tower HP transitions

## Test 3 — Cannon only
- [ ] placement snapping
- [ ] deploy timing
- [ ] lifetime
- [ ] HP decay / expiry

## Test 4 — Hog vs Cannon
- [ ] Hog changes target consistently
- [ ] pull trajectory
- [ ] first Cannon shot
- [ ] tower shots
- [ ] Cannon death
- [ ] Hog retarget
- [ ] final Hog HP

## Result
Generate `divergence.json` with:
- last agreed observation;
- first divergence timestamp/tick;
- real observation;
- simulator observation;
- suspected subsystem;
- confidence/measurement uncertainty;
- minimal reproduction scenario.
