# External engine fidelity probe — 2026-09-22

Branch: `probe/external-engine-fidelity-20260922`

GitHub Actions run: `35714778086`

Compared engines:
- current Rudy baseline from run `35607857492`
- Hasty-CR `913608b4dc7772008402493b27dc29020fe51718`
- CRForge `b41cf9b6276945152ec4c869ce56f98a5fa3f513`

References:
- `d03_hog_cannon_01_SECONDARY`
- `d02_hog_cannon_01_CROSSDEMO`
- `d03_hog_cannon_02_PRIMARY`

Tolerance in the video references: ±0.10 s.

## Strict isolated scenarios

| Scenario | Engine | Hog hit times (s) | Cannon death (s) | Hog death (s) | Verdict |
|---|---|---|---:|---:|---|
| SECONDARY real | video | 4.70 / 6.30 / 7.90 | 7.90 | 9.25 | reference |
| SECONDARY | Rudy | 4.65 / 6.25 / 7.85 | 7.85 | 9.25 | PASS |
| SECONDARY | Hasty-CR raw | 4.90 / 6.50 / 8.10 | 8.10 | 8.95 | FAIL, max error 0.30 s |
| SECONDARY | CRForge | 6.40 / 8.05 / — | 9.70 | 10.45 | FAIL, max error 1.80 s |
| CROSSDEMO real | video | 4.25 / 5.85 | 6.25 visual death | 7.15 | reference |
| CROSSDEMO | Rudy | 4.35 / 5.95 | 6.25 | 7.25 | PASS |
| CROSSDEMO | Hasty-CR raw | 4.80 / 6.40 | not dead before Hog | 7.30 | FAIL |
| CROSSDEMO | CRForge | 6.30 / — | 7.95 | 8.80 | FAIL, max error 2.05 s |

### Notes

Hasty-CR cannot be reproduced from its repository alone with the author's current extracted client data because `tmp/gamedata/csv_logic` is not committed. The probe therefore used the public historical `smlbiobot/cr-csv` snapshot. A second Hasty run overrode Hog/Cannon visible stats with the tournament-11 values used by Rudy; interaction timing still remained outside ±0.10 s and CROSSDEMO still failed to kill the Cannon correctly.

The CROSSDEMO result is important because the Cannon is pre-placed. Correct passive lifetime/HP decay affects whether the second Hog hit is lethal. Rudy reproduces both the hit timing and the later visual death timing; the tested Hasty setup does not.

CRForge has a hard-coded `PLACEMENT_SYNC_DELAY = 1.0f` before spawning a played card. Its source explicitly calls this a server-latency buffer. The large +1.2…2.05 s timing errors in these probes make it unsuitable as a drop-in fidelity engine without recalibration.

## PRIMARY contextual scenario

PRIMARY contains already-live Ice Golem + Hunter context.

Rudy:
- Hog hits: 4.30 / 5.90 / 7.50 — exact
- Cannon death: 7.50 — exact
- Hog death: 8.20 vs 8.70 — 0.50 s early
- current first divergence: context/tower damage chain leading to Hog death

The Hasty public-data setup could not inject Ice Golem because that historical snapshot lacks the required `ice_golem` card entry. CRForge's public GameSession bridge does not expose arbitrary live-entity state injection. Their PRIMARY numbers are therefore informational only, not a fair strict comparison.

## Native engine candidate

`Jason-XII/clash-royale-battle-engine` is categorically different from Hasty/CRForge: it is a probe around a native Null's Royale / Clash Royale engine, not a clean-room reimplementation.

It cannot be run in ordinary GitHub Actions from the repository alone. Its bootstrap contract requires:
- rooted ARM64 Android emulator,
- package `nullsroyale.rel.free`,
- exact APK version `15.535.13`,
- exact `libg.so` SHA-256 `110aa2b5cac391c498645e072b0d88729428c2c2845e7e2737ca8ee979059783`,
- runtime content version `15.535.86`,
- injected `libcrprobe.so`.

The repository does include the probe binary/source and Python reset/step API, but not the compatible APK/runtime needed to execute the native engine in our CI.

If that native engine passes our SECONDARY/CROSSDEMO references on a compatible local emulator, it is the one candidate that could replace Rudy for physics rollouts. Until that test exists, Rudy remains the only engine in this comparison already validated against our real video references.
