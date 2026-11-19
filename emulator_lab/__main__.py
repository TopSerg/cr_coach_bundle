"""Run from repository root: python -m emulator_lab <command> --help."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from . import adb as adb_api
from .compare import compare_files, diagnose
from .reference import reference_from_session
from .session import (create_session, start_match, record_action, capture_frames,
                      capture_videos, export_replay, atomic_json)
from .tuning import propose_from_file, apply_proposal


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Two-emulator CR physical fidelity lab; no direct CR internals")
    parser.add_argument("--adb", default="adb", help="adb.exe path (Android platform-tools)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="list attached ADB devices")
    p = sub.add_parser("init", help="create a recording session from measured screen geometry")
    p.add_argument("--config", type=_path, required=True)
    p.add_argument("--session", type=_path, required=True)
    p = sub.add_parser("start", help="mark battle start on common host clock")
    p.add_argument("--session", type=_path, required=True)
    p = sub.add_parser("play", help="send a known placement on a chosen device; log ADB timing bracket")
    p.add_argument("--session", type=_path, required=True)
    p.add_argument("--side", choices=("team", "opponent"), required=True)
    p.add_argument("--card", required=True)
    p.add_argument("--slot", type=int, required=True)
    p.add_argument("--x", type=int, required=True)
    p.add_argument("--y", type=int, required=True)
    p.add_argument("--delay", type=float, default=0.12)
    p = sub.add_parser("capture", help="capture timestamp-bracketed PNG frames from both ADB devices")
    p.add_argument("--session", type=_path, required=True)
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--interval", type=float, default=0.5)
    p = sub.add_parser("video", help="capture both supplemental Android MP4 videos (not tick-precise)")
    p.add_argument("--session", type=_path, required=True)
    p.add_argument("--seconds", type=int, required=True)
    p = sub.add_parser("observe", help="OCR tower HP from frames; templates optionally yield unverified candidates")
    p.add_argument("--session", type=_path, required=True)
    p.add_argument("--out", type=_path)
    p.add_argument("--templates", action="store_true")
    p.add_argument("--tesseract", help="explicit Tesseract executable if not on PATH")
    p = sub.add_parser("reference", help="promote repeated high-confidence OCR into sparse physical reference")
    p.add_argument("--session", type=_path, required=True)
    p.add_argument("--detections", type=_path)
    p.add_argument("--out", type=_path)
    p.add_argument("--min-confidence", type=float, default=0.85)
    p = sub.add_parser("export", help="export ADB actions to simulate.py replay schema")
    p.add_argument("--session", type=_path, required=True)
    p.add_argument("--duration", type=float)
    p.add_argument("--out", type=_path)
    p = sub.add_parser("compare", help="compare sparse image observations with Rudy snapshots.jsonl")
    p.add_argument("--reference", type=_path, required=True)
    p.add_argument("--snapshots", type=_path, required=True)
    p.add_argument("--out", type=_path, required=True)
    p = sub.add_parser("run", help="execute known actions with existing simulate.py Rudy backend, then compare")
    p.add_argument("--session", type=_path, required=True)
    p.add_argument("--rudy-data", type=_path, required=True)
    p.add_argument("--out", type=_path, required=True)
    p.add_argument("--duration", type=float)
    p = sub.add_parser("fit-speed", help="propose bounded shared speed change from three human-reviewed isolated trajectories")
    p.add_argument("--experiments", type=_path, required=True)
    p.add_argument("--category", choices=("slow", "medium", "fast", "veryfast"), required=True)
    p.add_argument("--repo", type=_path, default=Path.cwd())
    p.add_argument("--out", type=_path, required=True)
    p = sub.add_parser("apply", help="stage reviewed speed proposal in a new LOCAL Git branch; never push")
    p.add_argument("--proposal", type=_path, required=True)
    p.add_argument("--repo", type=_path, default=Path.cwd())
    p.add_argument("--branch", required=True)
    p.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "devices":
            result = [device.__dict__ if hasattr(device, "__dict__") else {"serial": device.serial, "status": device.status} for device in adb_api.devices(args.adb)]
        elif args.cmd == "init":
            result = create_session(args.config, args.session, args.adb)
        elif args.cmd == "start":
            result = start_match(args.session)
        elif args.cmd == "play":
            result = record_action(args.session, args.side, args.card, args.slot, args.x, args.y, args.adb, args.delay)
        elif args.cmd == "capture":
            result = {"samples_per_device": capture_frames(args.session, args.seconds, args.interval, args.adb)}
        elif args.cmd == "video":
            result = capture_videos(args.session, args.seconds, args.adb)
        elif args.cmd == "observe":
            from .vision import observe_frames
            result = {"detections": observe_frames(args.session, args.out or args.session / "detections.jsonl", templates=args.templates, ocr_binary=args.tesseract)}
        elif args.cmd == "reference":
            result = reference_from_session(args.session, args.detections or args.session / "detections.jsonl", args.out or args.session / "reference.json", args.min_confidence)
        elif args.cmd == "export":
            result = export_replay(args.session, args.duration)
            atomic_json(args.out or args.session / "replay.json", result)
        elif args.cmd == "compare":
            result = compare_files(args.reference, args.snapshots, args.out)
            result["diagnostic"] = diagnose(result)
            atomic_json(args.out, result)
        elif args.cmd == "run":
            root = Path(__file__).resolve().parents[1]
            replay_path = args.session / "replay.json"
            atomic_json(replay_path, export_replay(args.session, args.duration))
            cmd = [sys.executable, str(root / "simulate.py"), str(replay_path), "--engine", "rudy", "--rudy-data", str(args.rudy_data), "--out", str(args.out / "simulation"), "--sample-ticks", "1"]
            subprocess.run(cmd, cwd=root, check=True)
            reference = args.session / "reference.json"
            if reference.is_file():
                result = compare_files(reference, args.out / "simulation" / "snapshots.jsonl", args.out / "visual_report.json")
                result["diagnostic"] = diagnose(result)
                atomic_json(args.out / "visual_report.json", result)
            else:
                result = {"simulation_only": True, "message": "reference.json missing; run observe and reference to compare"}
        elif args.cmd == "fit-speed":
            result = propose_from_file(args.experiments, args.category, args.repo, args.out)
        elif args.cmd == "apply":
            result = {"local_commit": apply_proposal(args.repo, json.loads(args.proposal.read_text(encoding="utf-8")), args.branch, approved=args.approve),
                      "note": "Local branch only. Rebuild Rudy, rerun full physical gates, push and open PR after review."}
        else:
            raise AssertionError("unreachable")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if args.cmd == "compare" and result["status"] == "FIRST_DIVERGENCE" else 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
