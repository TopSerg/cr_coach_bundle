#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def tower_series(trace, player=2, tower="princess_left_hp"):
    vals = []
    for fr in trace["frames"]:
        side = fr["p2"] if player == 2 else fr["p1"]
        vals.append((fr["t_rel_s"], side[tower]))
    return vals


def target_tower_field(target_name: str) -> str:
    mapping = {
        "p2_princess_left": "princess_left_hp",
        "p2_princess_right": "princess_right_hp",
        "p1_princess_left": "princess_left_hp",
        "p1_princess_right": "princess_right_hp",
    }
    try:
        return mapping[target_name]
    except KeyError:
        raise ValueError(f"Unsupported target_tower in real fixture: {target_name!r}")


def hp_drop_events(series):
    events = []
    prev = series[0][1]
    for t, hp in series[1:]:
        if hp < prev:
            events.append({"t": t, "before": prev, "after": hp, "damage": prev - hp})
        prev = hp
    return events


def first_last_seen(trace, card_key):
    seen = []
    for fr in trace["frames"]:
        for e in fr.get("entities", []):
            if e.get("card") == card_key and e.get("alive", True):
                seen.append((fr["t_rel_s"], e))
    if not seen:
        return None, None
    return seen[0][0], seen[-1][0]


def metric(name, real, sim, tol, exact=False):
    if exact:
        passed = real == sim
        delta = 0 if passed else None
    else:
        delta = abs(sim - real)
        passed = delta <= tol
    return {
        "metric": name,
        "real": real,
        "sim": sim,
        "tolerance": tol,
        "pass": passed,
        "abs_error": delta,
    }


def compare_hog_solo(real, trace):
    obs = real["observed"]
    tol = real["tolerances"]
    tower_field = target_tower_field(obs["target_tower"])
    events = hp_drop_events(tower_series(trace, 2, tower_field))

    damages = [e["damage"] for e in events]
    intervals = [events[i]["t"] - events[i - 1]["t"] for i in range(1, len(events))]
    sim_damage = damages[0] if damages and len(set(damages)) == 1 else damages
    sim_mean_interval = mean(intervals)
    first_hit = events[0]["t"] if events else None

    rows = []
    rows.append(metric("hit_count", obs["hit_count"], len(events), tol["hit_count"], exact=True))
    rows.append(metric("damage_per_hit", obs["damage_per_hit"], sim_damage, tol["damage_per_hit"], exact=True))

    if sim_mean_interval is not None:
        rows.append(metric("mean_hit_interval_s", obs["mean_hit_interval_s"], sim_mean_interval, tol["mean_hit_interval_s"]))
    else:
        rows.append({
            "metric": "mean_hit_interval_s", "real": obs["mean_hit_interval_s"],
            "sim": None, "tolerance": tol["mean_hit_interval_s"],
            "pass": False, "abs_error": None,
        })

    if first_hit is not None:
        rows.append(metric(
            "first_hit_after_play_s",
            obs["first_hit_after_play_s_estimate"],
            first_hit,
            tol["first_hit_after_play_s"],
        ))
    else:
        rows.append({
            "metric": "first_hit_after_play_s",
            "real": obs["first_hit_after_play_s_estimate"], "sim": None,
            "tolerance": tol["first_hit_after_play_s"], "pass": False,
            "abs_error": None,
        })

    real_seq = obs["tower_hp_after_hits"]
    sim_seq = [e["after"] for e in events]
    rows.append({
        "metric": "tower_hp_sequence",
        "real": real_seq,
        "sim": sim_seq,
        "tolerance": 0,
        "pass": sim_seq == real_seq,
        "abs_error": None,
    })

    score = 0.0
    score += abs(len(events) - obs["hit_count"]) * 100.0
    if isinstance(sim_damage, int):
        score += abs(sim_damage - obs["damage_per_hit"]) * 2.0
    else:
        score += 1000.0
    if sim_mean_interval is not None:
        score += abs(sim_mean_interval - obs["mean_hit_interval_s"]) * 50.0
    else:
        score += 500.0
    if first_hit is not None:
        score += abs(first_hit - obs["first_hit_after_play_s_estimate"]) * 10.0
    else:
        score += 500.0

    return {
        "scenario": "hog_solo",
        "target_tower": obs["target_tower"],
        "pass": all(r["pass"] for r in rows),
        "score": round(score, 4),
        "metrics": rows,
        "sim_hit_events": events,
    }


def compare_hog_cannon(real, trace):
    obs = real["observed"]
    series = tower_series(trace, 2, "princess_left_hp")
    start_hp = series[0][1]
    end_hp = series[-1][1]
    tower_damage = start_hp - end_hp

    hog_first, hog_last = first_last_seen(trace, "hog-rider")
    cannon_first, cannon_last = first_last_seen(trace, "cannon")

    rows = [metric("protected_tower_damage", obs["tower_damage"], tower_damage, 0, exact=True)]

    if cannon_last is None or hog_last is None:
        rows.append({
            "metric": "cannon_dies_before_hog",
            "real": True, "sim": None, "tolerance": 0,
            "pass": False, "abs_error": None,
        })
        death_gap = None
    else:
        order_ok = cannon_last < hog_last
        rows.append({
            "metric": "cannon_dies_before_hog",
            "real": True, "sim": order_ok, "tolerance": 0,
            "pass": order_ok, "abs_error": None,
        })
        death_gap = hog_last - cannon_last
        rows.append(metric(
            "death_gap_s", obs["death_gap_s_estimate"], death_gap,
            real["tolerances"]["death_gap_s"],
        ))

    return {
        "scenario": "hog_vs_cannon_preplaced",
        "pass": all(r["pass"] for r in rows),
        "metrics": rows,
        "observed_entity_times": {
            "hog_first": hog_first, "hog_last": hog_last,
            "cannon_first": cannon_first, "cannon_last": cannon_last,
            "death_gap_s": death_gap,
        },
    }


def compare(real_path, trace_path):
    real = load(real_path)
    trace = load(trace_path)
    if real["name"] == "hog_solo_tower":
        return compare_hog_solo(real, trace)
    if real["name"] == "hog_vs_cannon_preplaced":
        return compare_hog_cannon(real, trace)
    raise ValueError(f"Unknown real fixture: {real['name']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("real")
    ap.add_argument("trace")
    ap.add_argument("--out")
    args = ap.parse_args()
    result = compare(args.real, args.trace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if result["pass"] else 2)


if __name__ == "__main__":
    main()
