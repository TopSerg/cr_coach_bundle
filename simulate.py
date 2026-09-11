#!/usr/bin/env python3
"""Run with Python 3.11+ from any cwd; only pinned simulator/ is required."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PIN = "40ca2b16bc276fc982a3aa80c7415b24439cbd3c"


def prepare_imports():
    explicit = os.environ.get("CRBOT_PATH")
    candidates = [Path(explicit)] if explicit else [ROOT / "upstream/cr-bot", ROOT / ".physical_deps/cr-bot"]
    backend = next((p for p in candidates if (p / "simulator").is_dir()), None)
    if backend is None:
        raise ValueError("Backend missing. Run: python setup_simulator.py")
    revision = subprocess.run(["git", "-C", str(backend), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if revision != PIN:
        raise ValueError(f"Backend revision {revision} differs from pin {PIN}; run python setup_simulator.py")
    dirty = subprocess.run(["git", "-C", str(backend), "status", "--porcelain", "--", "simulator"], capture_output=True, text=True, check=True).stdout
    if dirty.strip():
        raise ValueError("Backend simulator/ has local changes; cannot label it as the pinned engine")
    sys.path[:0] = [str(ROOT / "starter"), str(backend)]


def main(argv=None):
    p = argparse.ArgumentParser(description="Replay Clash Royale placements (JSON/CSV), Level 11, 20 Hz.")
    p.add_argument("input", nargs="?", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "outputs/replay")
    p.add_argument("--sample-ticks", type=int, default=2, help="snapshot spacing; physics remains 20 Hz")
    p.add_argument("--duration", help="override end time in seconds (absolute simulation time)")
    p.add_argument("--cards", action="store_true", help="list supported card IDs")
    args = p.parse_args(argv)
    try:
        prepare_imports()
        from cr_coach.replay.io import load_replay, seconds_to_tick, DEFAULT_RULESET
        from cr_coach.runtime.runner import run_replay
        from simulator.ruleset import load_ruleset
        if args.cards:
            print('\n'.join(load_ruleset(DEFAULT_RULESET).interaction_set))
            return 0
        if args.input is None:
            p.error("supply a replay JSON/CSV or --cards")
        spec = load_replay(args.input)
        if args.duration is not None:
            from dataclasses import replace
            spec = replace(spec, end_tick=seconds_to_tick(args.duration))
        if args.sample_ticks <= 0:
            raise ValueError("--sample-ticks must be positive")
        protected = [args.input.resolve()]
        if spec.initial_state:
            protected.append(spec.initial_state)
        destinations = [args.out.resolve() / name for name in ('report.json','checkpoint.json','events.jsonl','snapshots.jsonl','replay.html')]
        if any(path in destinations for path in protected):
            raise ValueError("output files must not overwrite the input replay or its checkpoint")
        report = run_replay(spec, args.out, sample_ticks=args.sample_ticks)
        print(json.dumps({k: report[k] for k in ('battle_id','status','end_tick','ruleset_id','state_hash','fidelity')}, indent=2))
        print(f"Playback: {(args.out / 'replay.html').resolve()}")
        return 2 if report['status'] == 'failed' else 0
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
