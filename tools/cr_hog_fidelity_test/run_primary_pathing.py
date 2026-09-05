#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cr_engine


TPS = 20
TILE = 1000
RIVER_Y_MIN = -1000
RIVER_Y_MAX = 1000
BRIDGE_LEFT_X = -5500
BRIDGE_RIGHT_X = 5500
BRIDGE_HALF_W = 1500

P1_DECK = [
    "hog-rider",
    "knight",
    "archers",
    "fireball",
    "giant",
    "valkyrie",
    "musketeer",
    "zap",
]
P2_DECK = [
    "cannon",
    "knight",
    "archers",
    "fireball",
    "giant",
    "valkyrie",
    "musketeer",
    "zap",
]


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path}")


def card_index(match: Any, player: int, card_key: str) -> int:
    hand = list(match.get_observation(player)["my_hand"])
    if card_key not in hand:
        raise RuntimeError(f"{card_key!r} not in P{player} hand: {hand}")
    return hand.index(card_key)


def play(match: Any, player: int, card_key: str, pos: tuple[int, int]) -> None:
    idx = card_index(match, player, card_key)
    result = match.play_card(player, idx, int(pos[0]), int(pos[1]))
    if result is False:
        raise RuntimeError(f"play_card rejected: P{player} {card_key} @ {pos}")


def idle(match: Any, ticks: int) -> None:
    for _ in range(ticks):
        match.step()


def cell_to_rudy(cell: list[int] | tuple[int, int]) -> tuple[int, int]:
    """Convert 18x32 top-left-origin cell index to Rudy center-origin mtile units.

    Cell centers are half-tile shifted from arena center:
      x = (col - 8.5) * 1000
      y = (15.5 - row) * 1000
    """
    col, row = int(cell[0]), int(cell[1])
    return (
        int(round((col - 8.5) * TILE)),
        int(round((15.5 - row) * TILE)),
    )


def raw_entities(match: Any) -> list[dict[str, Any]]:
    return [dict(e) for e in match.get_entities()]


def tower_snapshot(match: Any) -> dict[str, Any]:
    p1 = match.p1_tower_hp()
    p2 = match.p2_tower_hp()
    return {
        "p1": {"king": p1[0], "left": p1[1], "right": p1[2]},
        "p2": {"king": p2[0], "left": p2[1], "right": p2[2]},
    }


def frame(match: Any, t0_tick: int) -> dict[str, Any]:
    return {
        "tick": int(match.tick),
        "t_rel_s": round((int(match.tick) - t0_tick) / TPS, 3),
        "towers": tower_snapshot(match),
        "entities": raw_entities(match),
    }


def find_card(fr: dict[str, Any], card: str, team: int | None = None) -> dict[str, Any] | None:
    matches = []
    for entity in fr.get("entities", []):
        if entity.get("card_key") != card:
            continue
        if team is not None and int(entity.get("team", -1)) != team:
            continue
        matches.append(entity)
    if not matches:
        return None
    alive = [e for e in matches if e.get("alive", True) and int(e.get("hp", 0)) > 0]
    return alive[0] if alive else matches[0]


def hp_drop_events(frames: list[dict[str, Any]], card: str, team: int | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    prev_hp: int | None = None
    for fr in frames:
        entity = find_card(fr, card, team)
        if entity is None:
            continue
        hp = int(entity.get("hp", 0))
        if prev_hp is not None and hp < prev_hp:
            events.append(
                {
                    "t": fr["t_rel_s"],
                    "before": prev_hp,
                    "after": hp,
                    "damage": prev_hp - hp,
                    "x": entity.get("x"),
                    "y": entity.get("y"),
                }
            )
        prev_hp = hp
    return events


def first_absence_after_seen(frames: list[dict[str, Any]], card: str, team: int | None = None) -> float | None:
    seen = False
    for fr in frames:
        entity = find_card(fr, card, team)
        alive = entity is not None and entity.get("alive", True) and int(entity.get("hp", 0)) > 0
        if alive:
            seen = True
        elif seen:
            return float(fr["t_rel_s"])
    return None


def first_movement_time(frames: list[dict[str, Any]], card: str, team: int) -> float | None:
    start: tuple[int, int] | None = None
    for fr in frames:
        entity = find_card(fr, card, team)
        if entity is None:
            continue
        pos = (int(entity.get("x", 0)), int(entity.get("y", 0)))
        if start is None:
            start = pos
            continue
        if pos != start:
            return float(fr["t_rel_s"])
    return None


def river_crossing(frames: list[dict[str, Any]], card: str, team: int) -> dict[str, Any]:
    enter = center = exit_ = None
    samples: list[dict[str, Any]] = []
    for fr in frames:
        entity = find_card(fr, card, team)
        if entity is None:
            continue
        x = int(entity.get("x", 0))
        y = int(entity.get("y", 0))
        if -3500 <= y <= 3500:
            samples.append({"t": fr["t_rel_s"], "x": x, "y": y})
        if enter is None and y > RIVER_Y_MIN:
            enter = {"t": fr["t_rel_s"], "x": x, "y": y}
        if center is None and y >= 0:
            center = {"t": fr["t_rel_s"], "x": x, "y": y}
        if exit_ is None and y >= RIVER_Y_MAX:
            exit_ = {"t": fr["t_rel_s"], "x": x, "y": y}
    duration = None
    if enter is not None and exit_ is not None:
        duration = round(float(exit_["t"]) - float(enter["t"]), 3)
    return {
        "enter": enter,
        "center": center,
        "exit": exit_,
        "duration_s": duration,
        "samples": samples,
    }


def position_path(frames: list[dict[str, Any]], card: str, team: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    last: tuple[int, int] | None = None
    for fr in frames:
        entity = find_card(fr, card, team)
        if entity is None:
            continue
        pos = (int(entity.get("x", 0)), int(entity.get("y", 0)))
        if last != pos:
            out.append({"t": fr["t_rel_s"], "x": pos[0], "y": pos[1]})
            last = pos
    return out


def turn_angles(path: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(2, len(path)):
        a, b, c = path[i - 2], path[i - 1], path[i]
        v1 = (b["x"] - a["x"], b["y"] - a["y"])
        v2 = (c["x"] - b["x"], c["y"] - b["y"])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 == 0 or n2 == 0:
            continue
        cosv = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        angle = math.degrees(math.acos(cosv))
        if angle > 0.1:
            rows.append({"t": b["t"], "x": b["x"], "y": b["y"], "angle_deg": round(angle, 2)})
    return rows


def run_primary(data: Any, reference: dict[str, Any]) -> dict[str, Any]:
    mapped = reference["manually_mapped_cells"]
    hog_pos = cell_to_rudy(mapped["hog"])
    cannon_pos = cell_to_rudy(mapped["cannon"])
    real = reference["events_relative_to_hog_play_s"]
    cannon_delay_ticks = int(round(float(real["cannon_play"]) * TPS))

    match = cr_engine.new_match(data, P1_DECK, P2_DECK)
    idle(match, 200)
    t0 = int(match.tick)
    play(match, 1, "hog-rider", hog_pos)

    frames: list[dict[str, Any]] = [frame(match, t0)]
    cannon_played = False
    for _ in range(260):
        rel_ticks = int(match.tick) - t0
        if not cannon_played and rel_ticks >= cannon_delay_ticks:
            play(match, 2, "cannon", cannon_pos)
            cannon_played = True
        match.step()
        frames.append(frame(match, t0))

    cannon_hits = hp_drop_events(frames, "cannon", team=2)
    hog_damage_events = hp_drop_events(frames, "hog-rider", team=1)
    sim_hog_hits = [float(e["t"]) for e in cannon_hits]
    cannon_death = first_absence_after_seen(frames, "cannon", team=2)
    hog_death = first_absence_after_seen(frames, "hog-rider", team=1)
    crossing = river_crossing(frames, "hog-rider", 1)
    path = position_path(frames, "hog-rider", 1)

    comparisons: list[dict[str, Any]] = []
    expected_hits = [float(v) for v in real["hog_hits_cannon"]]
    for i, expected in enumerate(expected_hits):
        sim = sim_hog_hits[i] if i < len(sim_hog_hits) else None
        comparisons.append(
            {
                "event": f"hog_hit_cannon_{i + 1}",
                "real_s": expected,
                "sim_s": sim,
                "delta_s": None if sim is None else round(sim - expected, 3),
            }
        )
    for name, expected, sim in (
        ("cannon_death", float(real["cannon_death"]), cannon_death),
        ("hog_death", float(real["hog_death"]), hog_death),
    ):
        comparisons.append(
            {
                "event": name,
                "real_s": expected,
                "sim_s": sim,
                "delta_s": None if sim is None else round(sim - expected, 3),
            }
        )

    return {
        "scenario": "d03_hog_cannon_02_PRIMARY_rudy",
        "coordinate_mapping": {
            "source_cells": mapped,
            "hog_rudy": list(hog_pos),
            "cannon_rudy": list(cannon_pos),
            "formula": "x=(col-8.5)*1000; y=(15.5-row)*1000",
        },
        "real_events": real,
        "sim_events": {
            "cannon_play_s": cannon_delay_ticks / TPS,
            "hog_hits_cannon_s": sim_hog_hits,
            "cannon_death_s": cannon_death,
            "hog_death_s": hog_death,
            "hog_first_movement_s": first_movement_time(frames, "hog-rider", 1),
            "hog_river_crossing": crossing,
            "hog_hp_drop_events": hog_damage_events,
        },
        "comparison": comparisons,
        "hog_path": path,
        "hog_turns": turn_angles(path),
        "frames": frames,
    }


def inside_bridge(x: int) -> bool:
    return abs(x - BRIDGE_LEFT_X) <= BRIDGE_HALF_W or abs(x - BRIDGE_RIGHT_X) <= BRIDGE_HALF_W


def run_bridge_corner(data: Any) -> dict[str, Any]:
    """Invariant probe for a non-jumper approaching an off-axis target via a bridge.

    Knight starts near center on P1 side. Cannon is preplaced on P2 center-left.
    The probe checks that the troop reaches a bridge before entering the river,
    crosses without river-barrier bounce, and records the heading change around
    the bridge entry/exit for later comparison to video.
    """
    match = cr_engine.new_match(data, P1_DECK, P2_DECK)
    idle(match, 300)
    # Put Cannon down first and let its deployment complete.
    cannon_pos = (0, 5000)
    play(match, 2, "cannon", cannon_pos)
    idle(match, 25)
    t0 = int(match.tick)
    knight_pos = (500, -3500)
    play(match, 1, "knight", knight_pos)

    frames = [frame(match, t0)]
    for _ in range(220):
        match.step()
        frames.append(frame(match, t0))

    path = position_path(frames, "knight", 1)
    crossing = river_crossing(frames, "knight", 1)
    enter = crossing["enter"]
    entered_on_bridge = None if enter is None else inside_bridge(int(enter["x"]))

    river_samples = [p for p in path if RIVER_Y_MIN < int(p["y"]) < RIVER_Y_MAX]
    off_bridge_in_river = [p for p in river_samples if not inside_bridge(int(p["x"]))]

    # Detect a bounce/stall: after first reaching near-side river edge, Y should not
    # retreat materially back onto P1 side before exiting the river.
    bounce = False
    if enter is not None:
        entered = False
        max_y = -10**9
        for p in path:
            if p["t"] < enter["t"]:
                continue
            entered = True
            y = int(p["y"])
            max_y = max(max_y, y)
            if entered and max_y > RIVER_Y_MIN + 100 and y < RIVER_Y_MIN - 100:
                bounce = True
                break

    turns = turn_angles(path)
    bridge_turns = [t for t in turns if -3000 <= int(t["y"]) <= 3000]

    return {
        "scenario": "bridge_corner_nonjumper",
        "placement": {"knight": list(knight_pos), "cannon": list(cannon_pos)},
        "crossing": crossing,
        "entered_river_on_bridge": entered_on_bridge,
        "off_bridge_river_samples": off_bridge_in_river,
        "river_bounce_detected": bounce,
        "max_bridge_zone_turn_deg": max((float(t["angle_deg"]) for t in bridge_turns), default=0.0),
        "bridge_zone_turns": bridge_turns,
        "path": path,
        "frames": frames,
        "invariants": {
            "entered_on_bridge": entered_on_bridge is True,
            "never_off_bridge_inside_river": len(off_bridge_in_river) == 0,
            "no_river_bounce": not bounce,
            "crossed_to_enemy_side": crossing["exit"] is not None,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    data = cr_engine.load_data(args.data_dir)
    reference = load_json(args.reference)
    out = Path(args.out_dir)

    primary = run_primary(data, reference)
    bridge = run_bridge_corner(data)
    save_json(out / "primary_hog_cannon_rudy.json", primary)
    save_json(out / "bridge_corner_rudy.json", bridge)

    print("\n=== PRIMARY Rudy comparison ===")
    print(f"mapped Hog:    {primary['coordinate_mapping']['hog_rudy']}")
    print(f"mapped Cannon: {primary['coordinate_mapping']['cannon_rudy']}")
    for row in primary["comparison"]:
        print(
            f"{row['event']:20s} real={row['real_s']} sim={row['sim_s']} "
            f"delta={row['delta_s']}"
        )
    rc = primary["sim_events"]["hog_river_crossing"]
    print(f"river crossing: enter={rc['enter']} exit={rc['exit']} duration={rc['duration_s']}s")

    print("\n=== Bridge-corner invariant probe ===")
    for key, value in bridge["invariants"].items():
        print(f"{key}: {value}")
    print(f"max bridge-zone turn: {bridge['max_bridge_zone_turn_deg']} deg")

    # Diagnostic probe: do not make CI red for a fidelity mismatch. A malformed
    # engine/harness still raises above; divergences are persisted in JSON.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
