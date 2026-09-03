#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$(pwd)}"
mkdir -p "$ROOT/models" "$ROOT/data" "$ROOT/bin"

command -v hf >/dev/null || {
  echo "Install Hugging Face CLI first: python -m pip install -U huggingface_hub" >&2
  exit 1
}

# Small/medium model first
hf download Cochon123/clash-royale-policy-bc-v7-pilot-aligned --local-dir "$ROOT/models/policy_bc_v7_pilot_aligned"
hf download Cochon123/clash-royale-winner-predictor --local-dir "$ROOT/models/winner_predictor"

# cr-bot release model. The 882 MB executable is intentionally optional.
curl -L --fail --retry 3 \
  -o "$ROOT/models/prototype.pt" \
  https://github.com/Keschler/cr-bot/releases/download/v0.5/prototype.pt

echo "prototype.pt expected sha256: cb63215b5f4809fec330faacfd90dc76d451e39bf4cdda5d206159e89ccddb42"

if [ "${FETCH_CRBOT_BINARY:-0}" = "1" ]; then
  curl -L --fail --retry 3 \
    -o "$ROOT/bin/prototype-live-linux-x86_64" \
    https://github.com/Keschler/cr-bot/releases/download/v0.5/prototype-live-linux-x86_64
  chmod +x "$ROOT/bin/prototype-live-linux-x86_64"
  echo "binary expected sha256: bd1164f3caa93dd9ccf25552350ab76e1c2a58e5359d5cddbb335506cdf0cf56"
fi

if [ "${FETCH_REPLAY_DATASET:-0}" = "1" ]; then
  hf download Cochon123/clash-royale-replays --repo-type dataset --local-dir "$ROOT/data/cochon_replays"
fi
