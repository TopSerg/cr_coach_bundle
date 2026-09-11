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
    """Prepare the pinned cr-bot backend (backwards-compatible helper)."""
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
    p.add_argument("--engine", choices=("rudy", "crbot"), default="rudy", help="simulation backend (default: video-calibrated Rudy)")
    p.add_argument("--rudy-data", type=Path, default=ROOT / ".rudy" / "data", help="Tournament-11 Rudy data directory")
    args = p.parse_args(argv)
    try:
        if args.engine == "crbot":
            prepare_imports()
        else:
            sys.path.insert(0, str(ROOT / "starter"))
        from cr_coach.replay.io import load_replay, seconds_to_tick, DEFAULT_RULESET
        if args.cards:
            if args.engine == "crbot":
                from simulator.ruleset import load_ruleset

                print('\n'.join(load_ruleset(DEFAULT_RULESET).interaction_set))
            else:
                import cr_engine

                data = cr_engine.load_data(str(args.rudy_data.resolve()))
                print('\n'.join(sorted(str(dict(card)["key"]) for card in data.list_cards())))
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
        if args.engine == "crbot":
            from cr_coach.runtime.runner import run_replay

            report = run_replay(spec, args.out, sample_ticks=args.sample_ticks)
        else:
            from cr_coach.runtime.rudy_runner import run_rudy_replay

            report = run_rudy_replay(spec, args.out, data_dir=args.rudy_data, sample_ticks=args.sample_ticks)
        print(json.dumps({k: report[k] for k in ('battle_id','status','end_tick','ruleset_id','state_hash','fidelity')}, indent=2))
        print(f"Playback: {(args.out / 'replay.html').resolve()}")
        return 2 if report['status'] == 'failed' else 0
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
