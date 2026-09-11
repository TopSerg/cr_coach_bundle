"""Black-box tests for running a placement replay and saving its trace."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / ".physical_deps" / "cr-bot"
if (BACKEND / "simulator").is_dir() and str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


DECK = [
    "hog-rider",
    "cannon",
    "musketeer",
    "skeletons",
    "ice-golem",
    "ice-spirit",
    "fireball",
    "log",
]


def _load_runtime():
    from cr_coach.replay.io import load_replay
    from cr_coach.runtime.runner import run_replay, write_json

    return load_replay, run_replay, write_json


def _input(tmp_path: Path, payload: dict, name: str = "input.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(tmp_path: Path, payload: dict, *, sample_ticks: int = 1, name: str = "run"):
    load_replay, run_replay, _ = _load_runtime()
    source = _input(tmp_path, payload, f"{name}.json")
    spec = load_replay(source)
    out = tmp_path / f"{name}-out"
    report = run_replay(spec, out, sample_ticks=sample_ticks)
    return report, out, spec


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_runner_writes_the_documented_artifact_set(tmp_path: Path):
    report, out, _ = _run(tmp_path, {"duration_s": 0.1, "events": []})
    assert report["status"] == "horizon_reached"
    assert report["end_tick"] == 2
    for name in ("report.json", "checkpoint.json", "events.jsonl", "snapshots.jsonl", "replay.html"):
        assert (out / name).is_file(), name


def test_report_records_pinned_ruleset_and_unverified_fidelity(tmp_path: Path):
    report, out, _ = _run(tmp_path, {"duration_s": 0.1, "events": []})
    on_disk = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report == on_disk
    assert report["ruleset_id"] == "2026-08-04-roster"
    assert report["fidelity"] == "unverified_against_real_game"
    assert report["state_hash"]
    assert report["physics_profile"] == "hog-bridge-first-hit-v1"


def test_snapshot_cadence_does_not_change_authoritative_checkpoint(tmp_path: Path):
    payload = {
        "duration_s": 1.0,
        "events": [{"time": 0, "side": "team", "card": "hog-rider", "x": 14, "y": 17}],
    }
    report_1, out_1, _ = _run(tmp_path, payload, sample_ticks=1, name="every-tick")
    report_2, out_2, _ = _run(tmp_path, payload, sample_ticks=2, name="every-other-tick")
    assert report_1["state_hash"] == report_2["state_hash"]
    assert len(_read_jsonl(out_1 / "snapshots.jsonl")) > len(_read_jsonl(out_2 / "snapshots.jsonl"))


def test_event_tick_is_visible_after_the_physics_boundary(tmp_path: Path):
    payload = {
        "duration_s": 0.1,
        "events": [{"time": 0, "side": "team", "card": "hog-rider", "x": 9, "y": 18}],
    }
    _, out, _ = _run(tmp_path, payload)
    snapshots = _read_jsonl(out / "snapshots.jsonl")
    events = _read_jsonl(out / "events.jsonl")
    assert snapshots[0]["tick"] == 0
    assert any(row.get("kind") == "card_played" and row.get("tick") == 0 for row in events)
    assert any(row.get("kind") == "entity_created" and row.get("tick") == 0 for row in events)
    checkpoint = json.loads((out / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["state"]["tick"] == 2
    assert any(entity["card_id"] == "hog-rider" for entity in checkpoint["state"]["entities"])


def test_mid_horizon_checkpoint_keeps_a_live_tower_projectile(tmp_path: Path):
    # Keep a deterministic checkpoint while the Princess Tower projectile is
    # in flight. Checking ``alive`` guards against accidentally serializing
    # only resolved/expired shots.
    payload = {
        "duration_s": 3.2,
        "events": [
            {"time": 0, "side": "team", "card": "hog-rider", "x": 3, "y": 20},
            {"time": 0, "side": "opponent", "card": "cannon", "x": 3, "y": 10},
        ],
    }
    report, out, _ = _run(tmp_path, payload, name="half")
    assert report["end_tick"] == 64
    checkpoint = json.loads((out / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["state"]["tick"] == 64
    assert any(
        projectile.get("source_card_id") == "princess-tower" and projectile.get("alive") is True
        for projectile in checkpoint["state"]["projectiles"]
    )


def test_rejected_match_action_is_reported_with_its_original_index(tmp_path: Path):
    payload = {
        "mode": "match",
        "duration_s": 1,
        "team_deck": DECK,
        "opponent_deck": DECK,
        "events": [
            {"time": 0, "side": "team", "card": "hog-rider", "x": 9, "y": 18},
            # Hog has been consumed from the opening hand and is not yet back
            # in the cycle, so this event is a deterministic divergence.
            {"time": 0.05, "side": "team", "card": "hog-rider", "x": 9, "y": 18},
        ],
    }
    report, out, _ = _run(tmp_path, payload, name="failed")
    assert report["status"] == "failed"
    assert report["failed_event_index"] == 1
    assert json.loads((out / "checkpoint.json").read_text(encoding="utf-8"))["state"]["tick"] < 2


def test_replay_html_is_self_contained(tmp_path: Path):
    _, out, _ = _run(
        tmp_path,
        {"duration_s": 0.1, "events": [{"time": 0, "side": "team", "card": "hog-rider", "x": 9, "y": 18}]},
        name="html",
    )
    html = (out / "replay.html").read_text(encoding="utf-8")
    assert "snapshots.jsonl" in html
    assert "events.jsonl" in html
    assert "hog-rider" in html
    assert "CR Coach Replay" in html
    assert "<script" in html
    assert "http://" not in html and "https://" not in html


def test_write_json_creates_parent_and_is_deterministic(tmp_path: Path):
    _, _, write_json = _load_runtime()
    path = tmp_path / "nested" / "result.json"
    value = {"z": 1, "a": [2, 3]}
    returned = write_json(path, value)
    assert Path(returned) == path
    first = path.read_text(encoding="utf-8")
    write_json(path, value)
    assert path.read_text(encoding="utf-8") == first
    assert json.loads(first) == value


def test_runner_rejects_nonpositive_snapshot_cadence(tmp_path: Path):
    load_replay, run_replay, _ = _load_runtime()
    spec = load_replay(_input(tmp_path, {"duration_s": 1, "events": []}))
    with pytest.raises(ValueError):
        run_replay(spec, tmp_path / "bad-out", sample_ticks=0)


def _new_coach_engine():
    try:
        from cr_coach.engine.physics import CoachBattleEngine
        from simulator.actions import PlayCardAction
        from simulator.engine import BASE_HOG_CYCLE_DECK
        from simulator.ruleset import load_ruleset
    except ImportError as exc:  # pragma: no cover - exercised in dependency-free local runs
        pytest.skip(f"pinned cr-bot checkout is unavailable: {exc}")
    engine = CoachBattleEngine(load_ruleset("2026-08-04-roster"))
    deck = tuple(BASE_HOG_CYCLE_DECK)
    state = engine.new_battle(decks=(deck, deck), seed=0, shuffle_decks=False)
    return engine, state, PlayCardAction


def _step_to(engine, state, action_factory, *, owner: int, cell: tuple[int, int], end_tick: int):
    for tick in range(end_tick):
        actions = [action_factory(owner, 0, cell)] if tick == 0 else []
        engine.step(state, actions)


def _live_hog(state, owner: int):
    return next(
        entity
        for entity in state.entities.values()
        if entity.card_id == "hog-rider" and entity.owner == owner and entity.alive
    )


def test_coach_hog_from_center_routes_to_the_right_bridge_before_cannon():
    engine, state, action_factory = _new_coach_engine()
    _step_to(engine, state, action_factory, owner=0, cell=(9, 18), end_tick=49)
    hog = _live_hog(state, 0)
    assert 12_500 <= hog.x_mtile <= 14_500
    assert hog.y_mtile >= 17_000


def test_coach_hog_mirrors_to_the_opposite_bridge_with_lowercase_card_id():
    engine, state, action_factory = _new_coach_engine()
    # Mirror of (9, 18) on the 18x32 world grid is (8, 13).  The owner-1
    # Hog must use the opposite (left) bridge while retaining its canonical
    # lowercase card ID in authoritative state.
    _step_to(engine, state, action_factory, owner=1, cell=(8, 13), end_tick=49)
    hog = _live_hog(state, 1)
    assert hog.card_id == "hog-rider"
    assert 2_500 <= hog.x_mtile <= 5_500
    assert hog.y_mtile <= 15_000


def test_coach_hog_keeps_river_jump_when_cannon_is_the_target():
    engine, state, action_factory = _new_coach_engine()
    # The Crown-target bridge rule must not turn a building pull into a
    # ground route.  A same-tick Cannon gives Hog a building target and the
    # roster's authored river-jump lifecycle should remain observable.
    for tick in range(150):
        actions = []
        if tick == 0:
            actions = [action_factory(0, 0, (9, 18)), action_factory(1, 1, (9, 10))]
        engine.step(state, actions)
    assert any(
        event.kind == "river_airborne_changed" and event.get("airborne") is True
        for event in state.events
    )
