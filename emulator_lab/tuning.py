"""Evidence-gated numeric calibration; local branch edits, never silent main changes.

Calibration is deliberately restricted to a known Rudy *patch script*.
It cannot infer damage, targeting or collision constants from tower HP alone.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any

from .session import atomic_json

SPEED_CATEGORIES = {"slow": 45, "medium": 60, "fast": 90, "veryfast": 120}
SPEED_SCRIPT = Path("tools/rudy_windows/patch_rudy_troop_speed.py")


def estimate_speed(experiments: list[dict], category: str, patch_source: str) -> dict[str, Any]:
    """Fit raw Rudy units/tick (1000 mtile/tile, 20 TPS) to isolated trajectories.

    Requires 3 distinct scenarios with at least four *independently verified*
    positions, no collisions/charge/slow/jump/knockback and stable measured speed.
    """
    if category not in SPEED_CATEGORIES:
        raise ValueError("category must be slow/medium/fast/veryfast")
    if len({case.get("experiment_id") for case in experiments}) != len(experiments) or len(experiments) < 3:
        raise ValueError("at least 3 distinct experiment IDs required")
    slopes = []
    for case in experiments:
        if case.get("isolated_motion_verified") is not True or case.get("source") != "human_reviewed_trajectory":
            raise ValueError("each trajectory must be independently reviewed and isolated")
        points = case.get("positions", [])
        if len(points) < 4:
            raise ValueError("each experiment must contain >=4 positions")
        values = []
        for p, q in zip(points, points[1:]):
            dt = q["tick"] - p["tick"]
            if type(dt) is not int or dt < 2:
                raise ValueError("trajectory must have increasing tick gap >=2")
            dist = math.hypot(q["x_mtile"] - p["x_mtile"], q["y_mtile"] - p["y_mtile"])
            values.append(dist / dt)
        if not values or statistics.median(values) <= 0:
            raise ValueError("no measured movement")
        median = statistics.median(values)
        if max(abs(v - median) for v in values) > 0.18 * median:
            raise ValueError("nonuniform trajectory; possible path turn/collision/noise")
        slopes.append(median)
    median = statistics.median(slopes)
    if max(abs(v - median) for v in slopes) > 0.05 * median:
        raise ValueError("independent trajectories disagree >5%")
    candidate = round(median)
    current = SPEED_CATEGORIES[category]
    if candidate < current * 0.7 or candidate > current * 1.3:
        raise ValueError("candidate outside conservative ±30% bounds")
    if abs(candidate - current) <= 1:
        return {"ready": False, "reason": "change is <=1 unit/tick", "current": current, "estimated": candidate}
    old_lines = [line for line in patch_source.splitlines() if f"s if s <= {current} => {current}," in line]
    if len(old_lines) != 1:
        raise ValueError("expected a unique old speed line in patch script")
    old = old_lines[0]
    new = f"        s if s <= {current} => {candidate}, // {category}: experiment-calibrated units/tick"
    return {"schema_version": 1, "ready": True, "kind": "rudy_patch_speed_scalar", "category": category,
            "path": str(SPEED_SCRIPT).replace("\\", "/"), "old": old, "new": new,
            "source_sha256": hashlib.sha256(patch_source.encode("utf-8")).hexdigest(),
            "current": current, "proposed": candidate,
            "evidence_ids": [case["experiment_id"] for case in experiments],
            "trajectory_speed_units_per_tick": [round(v, 3) for v in slopes],
            "requires": ["human review", "rebuild Rust extension after patch", "P-1/M01–M39 and old fidelity regressions", "pull request review"],
            "warning": "calibration is a hypothesis; do not use until rebuilt Rudy passes physical regression gates"}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def apply_proposal(root: Path, proposal: dict, branch: str, *, approved: bool,
                   run_tests: bool = True) -> str:
    """Create isolated commit on a new local branch. Never pushes or merges."""
    if not approved:
        raise ValueError("requires explicit --approve; never auto-change physics based on CV alone")
    if proposal.get("kind") != "rudy_patch_speed_scalar" or proposal.get("ready") is not True:
        raise ValueError("not an approved speed scalar proposal")
    if len(set(proposal.get("evidence_ids", []))) < 3:
        raise ValueError("minimum three independent experiment IDs")
    if proposal.get("path") != SPEED_SCRIPT.as_posix():
        raise ValueError("path must be the known Rudy patch script; arbitrary file editing forbidden")
    if not branch.startswith("calibration/") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-_" for c in branch):
        raise ValueError("branch must be a safe calibration/* name")
    path = root / SPEED_SCRIPT
    source = path.read_text(encoding="utf-8")
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != proposal["source_sha256"]:
        raise ValueError("patch source has changed since proposal was computed")
    category = proposal.get("category")
    current = SPEED_CATEGORIES.get(category)
    proposed = proposal.get("proposed")
    if current is None or proposal.get("current") != current or type(proposed) is not int or not current * .7 <= proposed <= current * 1.3:
        raise ValueError("invalid known speed category / bounded candidate")
    expected_new = f"        s if s <= {current} => {proposed}, // {category}: experiment-calibrated units/tick"
    if proposal.get("new") != expected_new or "\n" in proposal.get("old", ""):
        raise ValueError("proposal cannot inject custom code; only numeric calibrated speed lines allowed")
    if source.count(proposal["old"]) != 1:
        raise ValueError("expected old line must occur exactly once")
    if source.count(proposal["new"]):
        raise ValueError("proposed line already exists")
    if not _git(root, "rev-parse", "--is-inside-work-tree") == "true":
        raise ValueError("must run inside a Git checkout")
    if _git(root, "status", "--porcelain"):
        raise ValueError("clean worktree required")
    base = _git(root, "branch", "--show-current")
    if not base:
        raise ValueError("detached HEAD is unsupported")
    _git(root, "switch", "-c", branch)
    try:
        path.write_text(source.replace(proposal["old"], proposal["new"], 1), encoding="utf-8")
        # Syntax tests are a minimum safety check, not a substitute for rebuilding Rudy.
        if run_tests:
            check = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_emulator_lab.py"], cwd=root)
            if check.returncode:
                raise RuntimeError("emulator lab regression checks failed")
        _git(root, "add", "--", proposal["path"])
        _git(root, "commit", "-m", f"experiment(rudy): propose {proposal['category']} speed {proposal['current']}->{proposal['proposed']}")
        return _git(root, "rev-parse", "HEAD")
    except Exception:
        _git(root, "restore", "--", proposal["path"])
        _git(root, "switch", base)
        raise


def propose_from_file(path: Path, category: str, repo_root: Path, out: Path) -> dict:
    experiments = json.loads(path.read_text(encoding="utf-8"))
    source = (repo_root / SPEED_SCRIPT).read_text(encoding="utf-8")
    proposal = estimate_speed(experiments, category, source)
    atomic_json(out, proposal)
    return proposal
