#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUDY_SIM="${1:-.}"

cd "$RUDY_SIM"

python "$ROOT/run_rudy.py" \
  --scenario all \
  --config "$ROOT/scenarios.json" \
  --data-dir data/ \
  --out-dir "$ROOT/sim_out"

set +e
python "$ROOT/compare.py" \
  "$ROOT/fixtures/real/hog_solo.json" \
  "$ROOT/sim_out/hog_solo_trace.json" \
  --out "$ROOT/sim_out/hog_solo_report.json"
SOLO_RC=$?

python "$ROOT/compare.py" \
  "$ROOT/fixtures/real/hog_vs_cannon_preplaced.json" \
  "$ROOT/sim_out/hog_cannon_trace.json" \
  --out "$ROOT/sim_out/hog_cannon_report.json"
CANNON_RC=$?
set -e

echo
echo "Reports:"
echo "  $ROOT/sim_out/hog_solo_report.json"
echo "  $ROOT/sim_out/hog_cannon_report.json"

if [[ $SOLO_RC -ne 0 || $CANNON_RC -ne 0 ]]; then
  echo "At least one fidelity probe diverged from the real demo (this is useful evidence, not a harness failure)."
  exit 2
fi

echo "Both probes are within configured tolerances."
