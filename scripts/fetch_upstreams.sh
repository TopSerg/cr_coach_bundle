#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(pwd)}"
DEST="$ROOT/upstream"
mkdir -p "$DEST"

clone() {
  local url="$1"
  local name="$2"
  if [ -d "$DEST/$name/.git" ]; then
    echo "[update] $name"
    git -C "$DEST/$name" pull --ff-only || true
    git -C "$DEST/$name" submodule update --init --recursive || true
  else
    echo "[clone] $name"
    git clone --depth 1 --recurse-submodules --shallow-submodules "$url" "$DEST/$name"
  fi
}

# Mainline
clone https://github.com/Keschler/cr-bot.git cr-bot
clone https://github.com/cochon123/clash-royale-ai.git clash-royale-ai
clone https://github.com/wty-yy/KataCR.git KataCR
clone https://github.com/RoyaleAPI/cr-api-data.git cr-api-data

# Fidelity / fast backend references
clone https://github.com/nguiaSoren/clash-royale-suite.git clash-royale-suite
clone https://github.com/voonhous/crforge.git crforge
clone https://github.com/max-miller1204/Clash-Royale-Pod.git Clash-Royale-Pod
clone https://github.com/smlbiobot/cr-csv.git cr-csv

# Archaeology / alternative implementations
clone https://github.com/Greedycell/AstralRoyaleLegacy.git AstralRoyaleLegacy
clone https://github.com/retroroyale/ClashRoyale.git RetroRoyale
clone https://github.com/Jason-XII/clash-royale-simulator.git clash-royale-simulator
clone https://github.com/samdickson22/clash-simulator.git clash-simulator
clone https://github.com/krazyness/CRBot-public.git CRBot-public

echo
echo "Done. Upstreams in: $DEST"
