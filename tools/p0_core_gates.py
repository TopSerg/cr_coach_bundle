#!/usr/bin/env python3
"""Deterministic Rudy M-gates for P0 (M01/M02/M04/M06-M10/M38/M39).

Every scenario consumes ``Match.step_trace()`` and therefore checks Rust's
authoritative state. The runner writes one trace/events pair per gate plus a
single machine-readable report whose failure contract is FIRST_DIVERGENCE.
Physical evidence is tracked separately from deterministic synthetic coverage:
passing this runner never upgrades a candidate video to VERIFIED.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "starter"))
sys.path.insert(0, str(ROOT / "tools" / "cr_hog_fidelity_test"))

import cr_engine  # type: ignore  # noqa: E402
import placement  # type: ignore  # noqa: E402


TPS = 20
BRIDGES = ((-7000, -4000), (4000, 7000))
BASE_DECK = [
    "hog-rider", "cannon", "knight", "archers",
    "fireball", "giant", "valkyrie", "musketeer",
]
P0_IDS = ("M01", "M02", "M04", "M06", "M07", "M08", "M09", "M10", "M38", "M39")


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


@dataclass
class Gate:
    gate_id: str
    title: str
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    observations: dict[str, Any] = field(default_factory=dict)
    divergence: dict[str, Any] | None = None

    def fail(self, tick: int, subsystem: str, expected: Any, actual: Any, detail: str) -> None:
        if self.divergence is not None:
            return
        exact = [int(x["tick"]) for x in self.snapshots if int(x["tick"]) < tick]
        self.divergence = {
            "tick": int(tick),
            "subsystem": subsystem.upper(),
            "expected": expected,
            "actual": actual,
            "detail": detail,
            "last_exact_tick": max(exact) if exact else None,
        }

    def result(self) -> dict[str, Any]:
        return {
            "id": self.gate_id,
            "title": self.title,
            "passed": self.divergence is None,
            "first_divergence": self.divergence,
            "last_exact_tick": None if not self.snapshots else int(self.snapshots[-1]["tick"]),
            "observations": self.observations,
        }


def new_match(data: Any, required_card: str | None = None) -> Any:
    deck = BASE_DECK
    if required_card is not None:
        deck = [required_card] + [card for card in BASE_DECK if card != required_card][:7]
    match = cr_engine.new_match(data, deck, BASE_DECK)
    if not hasattr(match, "step_trace"):
        raise RuntimeError("P0 requires P-1 Match.step_trace()")
    return match


def step(gate: Gate, match: Any, ticks: int = 1) -> None:
    for _ in range(ticks):
        raw = dict(match.step_trace())
        row = {"tick": int(raw["tick"]), "entities": [dict(x) for x in raw["entities"]]}
        gate.snapshots.append(row)
        gate.events.extend(dict(x) for x in raw["events"])


def entity(gate: Gate, uid: int, snapshot: dict[str, Any] | None = None) -> dict[str, Any] | None:
    fr = snapshot or (gate.snapshots[-1] if gate.snapshots else {"entities": []})
    return next((x for x in fr["entities"] if int(x["uid"]) == int(uid)), None)


def first_event(gate: Gate, kind: str, uid: int | None = None) -> dict[str, Any] | None:
    return next((e for e in gate.events if e.get("type") == kind and (uid is None or e.get("uid") == uid)), None)


def trace_until(gate: Gate, match: Any, predicate: Callable[[], bool], limit: int = 240) -> bool:
    for _ in range(limit):
        step(gate, match)
        if predicate():
            return True
    return False


def p0_spawn_troop(match: Any, player: int, card: str, x: int, y: int, hp: int = 100, passive: bool = False) -> int:
    if hp != 100 or passive:
        return int(match.seed_troop_state(player, card, x, y, 11, hp, passive))
    return int(match.spawn_troop(player, card, x, y, 11, False))


def gate_m01(data: Any) -> Gate:
    g = Gate("M01", "Placement / geometry")
    cases = [
        ("hog-rider", "troop", [9, 18], None),
        ("cannon", "building", [9, 21], None),
        ("tesla", "building", [9, 21], "top_left"),
    ]
    rows = []
    for card, kind, anchor, corner in cases:
        match = new_match(data, card)
        if corner:
            expected_grid2 = placement.even_footprint_center_from_selected_tile(anchor, selected_corner=corner)
        else:
            expected_grid2 = placement.cell_center_to_grid2(anchor)
        requested = placement.grid2_to_rudy(expected_grid2)
        uid = int(match.play_observed_card(1, card, *requested, 11))
        step(g, match)
        actual = entity(g, uid)
        expected_profile = placement.profile_for(card, kind)
        row = {
            "card_id": card,
            "selected_anchor": anchor,
            "selected_corner": corner,
            "requested_center": list(requested),
            "resolved_center": None if actual is None else [actual["x"], actual["y"]],
            "grid2_phase": expected_profile.center_phase,
            "footprint_tiles": list(expected_profile.footprint_tiles),
            "collision_radius": None if actual is None else actual.get("collision_radius"),
        }
        rows.append(row)
        if actual is None:
            g.fail(int(match.tick), "placement", {"card_id": card}, None, "placed entity missing from trace")
        elif (int(actual["x"]), int(actual["y"])) != requested:
            g.fail(int(match.tick), "placement", list(requested), [actual["x"], actual["y"]], f"{card} resolved center")
        elif int(actual.get("collision_radius", 0)) <= 0:
            g.fail(int(match.tick), "geometry", "positive collision_radius stored separately", actual.get("collision_radius"), card)
    g.observations["placements"] = rows
    return g


def gate_m02(data: Any) -> Gate:
    g = Gate("M02", "Ground pathfinding calibration board")
    starts = (-7500, -4500, -1500, 1500, 4500, 7500)
    routes = []
    for x in starts:
        match = new_match(data)
        uid = p0_spawn_troop(match, 1, "knight", x, -9000)
        samples = []
        crossed = False
        for _ in range(300):
            step(g, match)
            e = entity(g, uid)
            if e is None:
                break
            if int(e["y"]) >= -1500 and int(g.snapshots[-1]["tick"]) % 2 == 0:
                samples.append({"tick": g.snapshots[-1]["tick"], "x": e["x"], "y": e["y"], "waypoint": e.get("current_waypoint")})
            if -1000 < int(e["y"]) < 1000:
                on_bridge = any(lo <= int(e["x"]) <= hi for lo, hi in BRIDGES)
                if not on_bridge:
                    g.fail(int(g.snapshots[-1]["tick"]), "pathfinding", "river crossing inside bridge", {"x": e["x"], "y": e["y"]}, f"start_x={x}")
            if int(e["y"]) >= 1000:
                crossed = True
                break
        if not crossed:
            g.fail(int(match.tick), "pathfinding", "bridge exit reached", "not reached", f"start_x={x}")
        routes.append({"start_x": x, "crossed": crossed, "samples": samples})
    g.observations["routes"] = routes
    g.observations["physical_trajectory_status"] = "CANDIDATE_REFERENCE_REQUIRED"
    return g


def gate_m04(data: Any) -> Gate:
    g = Gate("M04", "Ground building-only targeting")
    match = new_match(data)
    hog = p0_spawn_troop(match, 1, "hog-rider", 0, -5000)
    troop = p0_spawn_troop(match, 2, "knight", 0, -3000)
    cannon = int(match.spawn_building(2, "cannon", 0, -500, 11))
    ok = trace_until(g, match, lambda: entity(g, hog) is not None and entity(g, hog).get("target_uid") is not None)
    target = None if not ok else entity(g, hog).get("target_uid")
    if target != cannon:
        g.fail(int(match.tick), "targeting", cannon, target, "building-only troop must ignore troop")
    g.observations.update({"attacker_uid": hog, "ignored_troop_uid": troop, "building_uid": cannon, "target_uid": target})
    return g


def gate_m06(data: Any) -> Gate:
    g = Gate("M06", "Ground target eligibility")
    match = new_match(data)
    attacker = p0_spawn_troop(match, 1, "knight", 0, -3000)
    air = p0_spawn_troop(match, 2, "minion", 0, -1800)
    ground = p0_spawn_troop(match, 2, "knight", 1200, -800)
    ok = trace_until(g, match, lambda: entity(g, attacker) is not None and entity(g, attacker).get("target_uid") is not None)
    target = None if not ok else entity(g, attacker).get("target_uid")
    if target != ground:
        g.fail(int(match.tick), "targeting", ground, target, "ground-only attacker selected air or no target")
    if any(e.get("uid") == attacker and e.get("target_uid") == air for e in g.events):
        g.fail(int(match.tick), "targeting", "air target never acquired", air, "air target appeared in target event")
    g.observations.update({"attacker_uid": attacker, "air_uid": air, "ground_uid": ground, "target_uid": target})
    return g


def ranged_case(data: Any, card: str) -> tuple[Gate, int | None, int]:
    g = Gate("M07", f"Musketeer can target {card}")
    match = new_match(data)
    attacker = p0_spawn_troop(match, 1, "musketeer", 0, -2500)
    wanted = p0_spawn_troop(match, 2, card, 0, -500)
    trace_until(g, match, lambda: entity(g, attacker) is not None and entity(g, attacker).get("target_uid") is not None)
    return g, None if entity(g, attacker) is None else entity(g, attacker).get("target_uid"), wanted


def gate_m07(data: Any) -> Gate:
    g = Gate("M07", "Ranged target eligibility")
    observations = []
    for card in ("knight", "minion"):
        sub, target, wanted = ranged_case(data, card)
        offset = len(g.snapshots)
        g.snapshots.extend(sub.snapshots)
        g.events.extend(sub.events)
        observations.append({"category": "air" if card == "minion" else "ground", "card_id": card, "target_uid": target, "expected_uid": wanted})
        if target != wanted:
            g.fail(int(sub.snapshots[-1]["tick"] if sub.snapshots else offset), "targeting", wanted, target, f"Musketeer must target {card}")
    g.observations["cases"] = observations
    return g


def gate_m08(data: Any) -> Gate:
    g = Gate("M08", "Sticky target")
    match = new_match(data)
    musk = p0_spawn_troop(match, 1, "musketeer", 0, -2000)
    giant = p0_spawn_troop(match, 2, "giant", 0, 1000, passive=True)
    acquired = trace_until(g, match, lambda: entity(g, musk) is not None and entity(g, musk).get("target_uid") == giant)
    if not acquired:
        g.fail(int(match.tick), "targeting", giant, None, "initial Giant lock not acquired")
        return g
    intruder = p0_spawn_troop(match, 2, "skeleton", 200, -900, passive=True)
    spawn_tick = int(match.tick)
    step(g, match, 24)
    changed = next((e for e in g.events if e.get("uid") == musk and e.get("type") in ("TARGET_CHANGED", "TARGET_DROPPED") and int(e["tick"]) > spawn_tick), None)
    if changed:
        g.fail(int(changed["tick"]), "targeting", giant, changed.get("target_uid"), "closer spawn broke sticky lock")
    g.observations.update({"attacker_uid": musk, "locked_uid": giant, "closer_uid": intruder, "closer_spawn_tick": spawn_tick})
    return g


def gate_m09(data: Any) -> Gate:
    g = Gate("M09", "Retarget on death")
    match = new_match(data)
    attacker = p0_spawn_troop(match, 1, "knight", 0, -1000)
    first = p0_spawn_troop(match, 2, "skeleton", 0, 0, hp=1, passive=True)
    # A stationary backup isolates retarget timing. A second troop would walk
    # toward P1 during the first fight and silently leave the controlled board.
    backup = int(match.spawn_building(2, "cannon", 500, 1600, 11))
    trace_until(g, match, lambda: first_event(g, "DEATH", first) is not None, 160)
    death = first_event(g, "DEATH", first)
    # DEATH is emitted at cleanup. Give the normal targeting state machine its
    # documented next tick before judging the retarget boundary.
    if death is not None:
        # Observe a bounded tail so a late implementation reports its exact
        # acquisition tick instead of being misclassified as a missing event.
        step(g, match, 20)
    acquired = next((e for e in g.events if e.get("uid") == attacker and e.get("type") in ("TARGET_ACQUIRED", "TARGET_CHANGED") and e.get("target_uid") == backup and (death is None or e["tick"] >= death["tick"])), None)
    if death is None:
        g.fail(int(match.tick), "combat", "first target death", None, "low-HP target did not die")
    elif acquired is None:
        g.fail(int(death["tick"]), "targeting", backup, None, "no retarget after target death")
    elif int(acquired["tick"]) - int(death["tick"]) > 1:
        g.fail(int(acquired["tick"]), "targeting", f"retarget <= tick {int(death['tick']) + 1}", acquired["tick"], "late retarget")
    g.observations.update({"attacker_uid": attacker, "dead_target_uid": first, "backup_uid": backup, "death_tick": None if death is None else death["tick"], "retarget_tick": None if acquired is None else acquired["tick"]})
    return g


def pull_probe(data: Any, cannon_x: int, cannon_y: int, delay: int = 0) -> dict[str, Any]:
    g = Gate("probe", "pull")
    match = new_match(data)
    hog = p0_spawn_troop(match, 1, "hog-rider", 500, -7500)
    step(g, match, max(0, delay))
    cannon = int(match.spawn_building(2, "cannon", cannon_x, cannon_y, 11))
    spawn_tick = int(match.tick)
    trace_until(g, match, lambda: first_event(g, "TARGET_ACQUIRED", hog) is not None, 180)
    acquired = next((e for e in g.events if e.get("uid") == hog and e.get("type") in ("TARGET_ACQUIRED", "TARGET_CHANGED") and e.get("target_uid") == cannon), None)
    # Direct test setup inserts the authoritative entity synchronously between
    # engine ticks. Its insertion tick is therefore the exact spawn tick; a
    # transition event is reserved for spawns performed inside engine::tick.
    step(g, match, 25)
    first_active = next((fr["tick"] for fr in g.snapshots if (entity(g, cannon, fr) or {}).get("deploy_timer", 1) <= 0), None)
    return {
        "pull": acquired is not None,
        "hog_uid": hog,
        "cannon_uid": cannon,
        "play_tick": spawn_tick,
        "spawn_tick": spawn_tick,
        "targetable_tick": None if acquired is None else acquired["tick"],
        "active_tick": first_active,
        "trace": g,
    }


def gate_m10(data: Any) -> Gate:
    g = Gate("M10", "Hog/Cannon spatial pull matrix")
    matrix = []
    for dy in range(-2, 3):
        row = []
        for dx in range(-2, 3):
            probe = pull_probe(data, 500 + dx * 1000, -500 + dy * 1000)
            row.append("PULL" if probe["pull"] else "NO_PULL")
            g.snapshots.extend(probe["trace"].snapshots)
            g.events.extend(probe["trace"].events)
        matrix.append(row)
    if not any(cell == "PULL" for row in matrix for cell in row):
        g.fail(0, "targeting", "at least one PULL", matrix, "spatial sweep never pulls Hog")
    g.observations.update({"origin_rudy": [500, -500], "axis_tiles": [-2, -1, 0, 1, 2], "matrix": matrix, "physical_evidence": ["d03_hog_cannon_02_primary.json", "d03_hog_cannon_01_secondary.json", "d02_hog_cannon_01_crossdemo.json"], "evidence_status": "CANDIDATE"})
    return g


def gate_m38(data: Any) -> Gate:
    g = Gate("M38", "Princess Tower targeting")
    match = new_match(data)
    first = p0_spawn_troop(match, 1, "skeleton", -5500, 3000, hp=1, passive=True)
    backup = p0_spawn_troop(match, 1, "giant", -4500, 2500, passive=True)
    trace_until(g, match, lambda: first_event(g, "DEATH", first) is not None, 200)
    tower_events = [e for e in g.events if e.get("source_kind") == "tower" and e.get("type") in ("TARGET_ACQUIRED", "TARGET_CHANGED")]
    first_lock = next((e for e in tower_events if e.get("target_uid") == first), None)
    retarget = next((e for e in tower_events if e.get("target_uid") == backup and (first_lock is None or e["tick"] >= first_lock["tick"])), None)
    if first_lock is None:
        g.fail(int(match.tick), "tower_targeting", first, [e.get("target_uid") for e in tower_events], "tower did not acquire first arrival")
    elif retarget is None:
        g.fail(int(match.tick), "tower_targeting", backup, [e.get("target_uid") for e in tower_events], "tower did not retarget after death")
    g.observations.update({"first_uid": first, "backup_uid": backup, "tower_target_events": tower_events})
    return g


def gate_m39(data: Any) -> Gate:
    g = Gate("M39", "Deploy-time aggro boundary")
    sweep = []
    # Ten seconds at one authoritative tick (50 ms) resolution brackets both
    # the early deploy pull and the point where Hog is already committed.
    for delay in range(0, 201):
        probe = pull_probe(data, 500, -500, delay)
        sweep.append({k: probe[k] for k in ("play_tick", "spawn_tick", "targetable_tick", "active_tick", "pull")})
        g.snapshots.extend(probe["trace"].snapshots)
        g.events.extend(probe["trace"].events)
    pull_indices = [i for i, row in enumerate(sweep) if row["pull"]]
    transitions = [i for i in range(1, len(sweep)) if sweep[i]["pull"] != sweep[i - 1]["pull"]]
    early = [row for row in sweep if row["pull"] and row["targetable_tick"] is not None and row["active_tick"] is not None and row["targetable_tick"] < row["active_tick"]]
    if not pull_indices:
        g.fail(0, "deploy_aggro", "at least one PULL", sweep, "timing sweep contains no pull")
    elif len(transitions) != 1:
        g.fail(int(sweep[transitions[0]]["play_tick"] if transitions else 0), "deploy_aggro", "one monotonic PULL/NO_PULL boundary", transitions, "timing sweep is constant or non-monotonic")
    elif not early:
        g.fail(int(sweep[pull_indices[0]]["targetable_tick"] or 0), "deploy_aggro", "target acquisition before deploy completes", sweep[pull_indices[0]], "building was not targetable during deployment")
    g.observations.update({"step_ms": 50, "sweep": sweep, "boundary_indices": transitions, "evidence_status": "CANDIDATE"})
    return g


GATES: dict[str, Callable[[Any], Gate]] = {
    "M01": gate_m01, "M02": gate_m02, "M04": gate_m04, "M06": gate_m06,
    "M07": gate_m07, "M08": gate_m08, "M09": gate_m09, "M10": gate_m10,
    "M38": gate_m38, "M39": gate_m39,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", nargs="*", choices=P0_IDS)
    ap.add_argument("--no-strict", action="store_true", help="write report but do not fail the process")
    args = ap.parse_args()
    selected = args.only or list(P0_IDS)
    data = cr_engine.load_data(args.data_dir)
    out = Path(args.out_dir)
    results = []
    for gate_id in selected:
        gate = GATES[gate_id](data)
        gate_dir = out / gate_id.lower()
        dump_jsonl(gate_dir / "trace.jsonl", gate.snapshots)
        dump_jsonl(gate_dir / "events.jsonl", gate.events)
        dump_json(gate_dir / "report.json", gate.result())
        results.append(gate.result())
        state = "PASS" if gate.divergence is None else "FIRST_DIVERGENCE"
        print(f"{gate_id}: {state}")
        if gate.divergence:
            print(json.dumps(gate.divergence, ensure_ascii=False))
    first = next((r for r in results if not r["passed"]), None)
    summary = {
        "schema_version": 1,
        "phase": "P0",
        "passed": first is None,
        "first_divergence": None if first is None else {"gate": first["id"], **first["first_divergence"]},
        "gates": results,
        "evidence_policy": "Synthetic PASS is necessary but does not imply physical VERIFIED.",
    }
    dump_json(out / "summary.json", summary)
    return 0 if first is None or args.no_strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
