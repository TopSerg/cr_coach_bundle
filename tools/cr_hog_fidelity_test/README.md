# Hog fidelity probes for cr-rudy-sim

This package turns the two recorded Clash Royale demos into reproducible
differential tests against **cr-rudy-sim**.

## What is measured from the real demos

### Probe A — Hog solo → Princess Tower

Real video fixture: `fixtures/video/hog_solo_tower.mp4`

Observed tower HP:

```
3052
2735
2418
2101
1784
1467
1150
833
```

Therefore:

- 7 Hog hits
- 317 damage per hit
- hit times in the trimmed video:
  `8.06, 9.60, 11.20, 12.78, 14.46, 16.02, 17.62 s`
- mean inter-hit interval: about `1.593 s`

The exact deployment coordinate is not claimed to be perfectly recovered from
the screen recording. It is stored as an estimate and can be grid-searched
without changing any engine mechanics.

### Probe B — Hog vs preplaced Cannon

Real video fixture: `fixtures/video/hog_vs_cannon_preplaced.mp4`

Observed:

- Cannon exists before Hog chooses its first target.
- Hog is pulled to the Cannon.
- protected Princess Tower HP remains exactly `3052 → 3052`.
- Cannon disappears before Hog.
- visual death-time gap is roughly `0.15 s`.

This probe checks **initial building pull / pathing**, not a late dynamic
retarget. A separate recording is still needed for
`Princess Tower target → late Cannon → target switch`.

## Why the scenario coordinates are estimates

Rudy uses internal coordinates with:

- origin at arena centre
- 1 tile ≈ 600 internal units
- bridge centres at x = ±5100
- P2 Princess Towers at y = +10200

The video-derived estimates in `scenarios.json` are:

```
solo Hog:          (-3300, -7200)   # uncertain; grid-search enabled
Cannon:            (+1200, +6000)
Cannon-test Hog:   (-5100, -1200)   # left bridge
```

These are intentionally configuration, not hardcoded "truth".

## Run against Rudy

Clone/build Rudy in a normal environment:

```bash
git clone https://github.com/nguiaSoren/clash-royale-suite.git
cd clash-royale-suite/cr-rudy-sim/simulator/engine
python -m pip install maturin
maturin develop --release
cd ..
```

Then run:

```bash
/path/to/cr_hog_fidelity_test/run_all.sh .
```

The script uses Rudy's public Python API and writes:

```
sim_out/hog_solo_trace.json
sim_out/hog_cannon_trace.json
sim_out/hog_solo_report.json
sim_out/hog_cannon_report.json
```

A non-zero exit code from `run_all.sh` means **fidelity divergence**, not that
the harness crashed.

## Placement grid search

If the solo result differs and the likely cause is uncertain deployment
location, search only nearby legal coordinates:

```bash
python /path/to/cr_hog_fidelity_test/grid_search_solo.py \
  --config /path/to/cr_hog_fidelity_test/scenarios.json \
  --real /path/to/cr_hog_fidelity_test/fixtures/real/hog_solo.json \
  --data-dir data/ \
  --out-dir /path/to/cr_hog_fidelity_test/sim_out/grid
```

This ranks candidate deployment coordinates by agreement with the **real
video events**. It does not alter Hog speed, attack speed, tower stats,
targeting, collision, or any other simulator rule.

## Pass criteria

Hog solo:

- damage per hit: exact
- hit count: exact
- complete tower HP sequence: exact
- mean hit interval: ±0.10 s
- first hit after deployment estimate: ±0.30 s

Cannon:

- protected tower damage: exactly zero
- Cannon dies before Hog
- death-time gap: ±0.15 s

The first metrics to trust are damage / HP sequence / target outcome.
Absolute timing and path coordinates become stronger after the deployment
coordinate is recovered more precisely.

## Harness self-test

The comparator itself can be checked without Rudy:

```bash
python -m pytest tests/test_compare.py
```

The synthetic fixture is only a software test for the comparator; it is NOT a
simulator result.
