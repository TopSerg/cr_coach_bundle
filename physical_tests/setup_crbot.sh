#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/.physical_deps/cr-bot"
PIN="40ca2b16bc276fc982a3aa80c7415b24439cbd3c"
REMOTE="https://github.com/Keschler/cr-bot.git"

if [[ -d "$DEST/simulator" && -d "$DEST/.git" ]]; then
  HEAD="$(git -C "$DEST" rev-parse HEAD 2>/dev/null || true)"
  if [[ "$HEAD" == "$PIN" ]]; then
    echo "cr-bot simulator already prepared at $PIN"
    exit 0
  fi
fi

echo "Preparing lightweight cr-bot simulator checkout..."
echo "Only simulator/ will be materialized; the full upstream repository is not downloaded."

mkdir -p "$(dirname "$DEST")"
if [[ ! -d "$DEST/.git" ]]; then
  rm -rf "$DEST"
  git init "$DEST"
  git -C "$DEST" remote add origin "$REMOTE"
  git -C "$DEST" config remote.origin.promisor true
  git -C "$DEST" config remote.origin.partialclonefilter blob:none
  git -C "$DEST" config extensions.partialClone origin
  git -C "$DEST" sparse-checkout init --cone
  git -C "$DEST" sparse-checkout set simulator
fi

git -C "$DEST" fetch --depth 1 --filter=blob:none origin "$PIN"
git -C "$DEST" checkout --detach FETCH_HEAD

HEAD="$(git -C "$DEST" rev-parse HEAD)"
[[ "$HEAD" == "$PIN" ]] || { echo "Expected $PIN, got $HEAD" >&2; exit 1; }
[[ -d "$DEST/simulator" ]] || { echo "simulator/ was not materialized" >&2; exit 1; }

echo "Ready: $DEST"
echo "Pinned commit: $HEAD"
