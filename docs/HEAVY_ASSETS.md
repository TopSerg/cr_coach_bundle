# Heavy assets / datasets

Не тянуть всё сразу. Начать с source + одного controlled replay/video.

## Keschler/cr-bot release v0.5

- `prototype-live-linux-x86_64` — около 882 MB, SHA256 `bd1164f3caa93dd9ccf25552350ab76e1c2a58e5359d5cddbb335506cdf0cf56`
- `prototype.pt` — около 25 MB, SHA256 `cb63215b5f4809fec330faacfd90dc76d451e39bf4cdda5d206159e89ccddb42`

URLs:

- https://github.com/Keschler/cr-bot/releases/download/v0.5/prototype-live-linux-x86_64
- https://github.com/Keschler/cr-bot/releases/download/v0.5/prototype.pt

## Hugging Face — Cochon

Useful commands:

```bash
hf download Cochon123/clash-royale-winner-predictor --local-dir models/winner_predictor
hf download Cochon123/clash-royale-policy-bc-v4 --local-dir models/policy_bc_v4
hf download Cochon123/clash-royale-policy-bc-v6 --local-dir models/policy_bc_v6
hf download Cochon123/clash-royale-policy-bc-v7-pilot-aligned --local-dir models/policy_bc_v7_pilot_aligned
hf download Cochon123/clash-royale-policy-bc-v7-pilot-shuffled --local-dir models/policy_bc_v7_pilot_shuffled
hf download Cochon123/clash-royale-realism-scorer --local-dir models/realism_scorer
hf download Cochon123/clash-royale-style-discriminator --local-dir models/style_discriminator
hf download Cochon123/clash-royale-replays --repo-type dataset --local-dir data/cochon_replays
```

## Other useful replay/video corpora

Potentially large; fetch only after simulator ingestion works:

- `josefbednar/alphaclash-replays`
- `chrisrca/clash-royale-tv-replays` (referenced by Clash-Royale-Pod)

Keep dataset provenance and patch/date metadata. Old video can validate patch-invariant geometry, but not blindly serve as truth for current damage/timing.
