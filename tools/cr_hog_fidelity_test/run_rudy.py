#!/usr/bin/env python3
"""
Run the two video-derived fidelity probes against cr-rudy-sim.

Expected execution location:
  cd <clash-royale-suite>/cr-rudy-sim/simulator
  python /path/to/cr_hog_fidelity_test/run_rudy.py --scenario all \
      --config /path/to/cr_hog_fidelity_test/scenarios.json \
      --out-dir /path/to/cr_hog_fidelity_test/sim_out

The script only uses the public PyO3 API: cr_engine.new_match(), play_card(),
step(), p1/p2_tower_hp(), get_observation(), and get_entities().
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

try:
    import cr_engine
except ImportError:
    raise SystemExit(
        "cr_engine is not importable.\n"
        "Build Rudy first:\n"
        "  cd cr-rudy-sim/simulator/engine\n"
        "  python -m pip install maturin\n"
        "  maturin develop --release\n"
    )


TPS = 20


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def card_index(match, player, card_key):
    hand = match.get_observation(player)["my_hand"]
    if card_key not in hand:
        raise RuntimeError(f"{card_key!r} not in P{player} hand: {hand}")
    return hand.index(card_key)


def tower_snapshot(match, player):
    hp = match.p1_tower_hp() if player == 1 else match.p2_tower_hp()
    return {
        "king_hp": hp[0],
        "princess_left_hp": hp[1],
        "princess_right_hp": hp[2],
    }


def entity_snapshot(match):
    out = []
    for e in match.get_entities():
        out.append({
            "id": e["id"],
            "team": e["team"],
            "kind": e["kind"],
            "card": e["card_key"],
            "x": e["x"],
            "y": e["y"],
            "hp": e["hp"],
            "max_hp": e["max_hp"],
            "damage": e["damage"],
            "alive": e["alive"],
            "attack_phase": e.get("attack_phase", "idle"),
        })
    return out


def frame(match, t0_tick):
    return {
        "tick": match.tick,
        "t_rel_s": round((match.tick - t0_tick) / TPS, 3),
        "p1": tower_snapshot(match, 1),
        "p2": tower_snapshot(match, 2),
        "entities": entity_snapshot(match),
    }


def idle(match, n):
    for _ in range(n):
        match.step()


def play(match, player, card_key, x, y):
    idx = card_index(match, player, card_key)
    return match.play_card(player, idx, int(x), int(y))


def run_solo(data, cfg, pos):
    match = cr_engine.new_match(data, cfg["p1_deck"], cfg["p2_deck"])
    idle(match, cfg["match_idle_ticks_before_action"])
    t0 = match.tick

    play(match, 1, "hog-rider", pos[0], pos[1])
    frames = [frame(match, t0)]
    for _ in range(cfg["max_ticks_after_hog"]):
        match.step()
        frames.append(frame(match, t0))

    return {
        "engine": "cr-rudy-sim",
        "scenario": "hog_solo",
        "placement": {"hog": list(pos)},
        "t0_tick": t0,
        "frames": frames,
    }


def run_cannon(data, cfg):
    match = cr_engine.new_match(data, cfg["p1_deck"], cfg["p2_deck"])
    idle(match, cfg["match_idle_ticks_before_cannon"])
    cannon_tick = match.tick

    cx, cy = cfg["cannon_position_estimate"]
    hx, hy = cfg["hog_position_estimate"]
    play(match, 2, "cannon", cx, cy)

    for _ in range(cfg["hog_delay_ticks_after_cannon"]):
        match.step()

    t0 = match.tick
    play(match, 1, "hog-rider", hx, hy)
    frames = [frame(match, t0)]
    for _ in range(cfg["max_ticks_after_hog"]):
        match.step()
        frames.append(frame(match, t0))

    return {
        "engine": "cr-rudy-sim",
        "scenario": "hog_vs_cannon_preplaced",
        "placement": {"cannon": [cx, cy], "hog": [hx, hy]},
        "cannon_tick": cannon_tick,
        "hog_tick": t0,
        "frames": frames,
    }


def save(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"saved {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["solo", "cannon", "all"], default="all")
    ap.add_argument("--config", required=True)
    ap.add_argument("--data-dir", default="data/")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--solo-x", type=int)
    ap.add_argument("--solo-y", type=int)
    args = ap.parse_args()

    conf = load_json(args.config)
    data = cr_engine.load_data(args.data_dir)
    out = Path(args.out_dir)

    if args.scenario in ("solo", "all"):
        cfg = conf["scenarios"]["hog_solo"]
        pos = list(cfg["hog_position_estimate"])
        if args.solo_x is not None:
            pos[0] = args.solo_x
        if args.solo_y is not None:
            pos[1] = args.solo_y
        save(run_solo(data, cfg, pos), out / "hog_solo_trace.json")

    if args.scenario in ("cannon", "all"):
        cfg = conf["scenarios"]["hog_vs_cannon_preplaced"]
        save(run_cannon(data, cfg), out / "hog_cannon_trace.json")


if __name__ == "__main__":
    main()
