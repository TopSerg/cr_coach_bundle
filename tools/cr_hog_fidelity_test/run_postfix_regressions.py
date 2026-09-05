#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cr_engine
import run_primary_pathing as common


def attack_release_hits(
    frames: list[dict[str, Any]],
    attacker_card: str,
    attacker_team: int,
    target_card: str,
    target_team: int,
) -> list[dict[str, Any]]:
    """Detect actual attack releases without confusing passive building HP decay for hits.

    Rudy exposes attack_phase but not target ID. For these isolated Hog/Cannon probes,
    a Hog hit is a Windup -> Backswing transition on a tick where the Cannon either:
      * loses a large damage step (>= 50% of Hog's listed damage), or
      * disappears on that release tick (lethal hit).

    Small per-tick Cannon HP drops are therefore classified as lifetime decay, not hits.
    """
    events: list[dict[str, Any]] = []
    for prev_fr, cur_fr in zip(frames, frames[1:]):
        a0 = common.find_card(prev_fr, attacker_card, attacker_team)
        a1 = common.find_card(cur_fr, attacker_card, attacker_team)
        if a0 is None or a1 is None:
            continue
        if a0.get("attack_phase") != "windup" or a1.get("attack_phase") != "backswing":
            continue

        t0 = common.find_card(prev_fr, target_card, target_team)
        if t0 is None or int(t0.get("hp", 0)) <= 0:
            continue
        t1 = common.find_card(cur_fr, target_card, target_team)

        attacker_damage = max(int(a0.get("damage", 0)), int(a1.get("damage", 0)), 1)
        before = int(t0.get("hp", 0))
        after = 0 if t1 is None else int(t1.get("hp", 0))
        hp_drop = max(0, before - after)
        lethal_disappearance = t1 is None

        if lethal_disappearance or hp_drop >= max(1, attacker_damage // 2):
            events.append({
                "t": float(cur_fr["t_rel_s"]),
                "before": before,
                "after": after,
                "observed_hp_drop": hp_drop,
                "attacker_damage": attacker_damage,
                "lethal_disappearance": lethal_disappearance,
                "attacker_x": a1.get("x"),
                "attacker_y": a1.get("y"),
                "target_x": None if t1 is None else t1.get("x"),
                "target_y": None if t1 is None else t1.get("y"),
            })
    return events


def passive_decay_events(
    frames: list[dict[str, Any]],
    target_card: str,
    target_team: int,
    attack_times: list[float],
) -> list[dict[str, Any]]:
    hit_ticks = {round(t, 3) for t in attack_times}
    out: list[dict[str, Any]] = []
    prev_hp: int | None = None
    for fr in frames:
        ent = common.find_card(fr, target_card, target_team)
        if ent is None:
            continue
        hp = int(ent.get("hp", 0))
        t = float(fr["t_rel_s"])
        if prev_hp is not None and hp < prev_hp and round(t, 3) not in hit_ticks:
            drop = prev_hp - hp
            # Passive lifetime decay is tiny compared with Hog's 317 damage.
            if drop < 100:
                out.append({"t": t, "before": prev_hp, "after": hp, "loss": drop})
        prev_hp = hp
    return out


def replay_case(data: Any, ref: dict[str, Any]) -> dict[str, Any]:
    mapped = ref["manually_mapped_cells"]
    hog_pos = common.cell_to_rudy(mapped["hog"])
    cannon_pos = common.cell_to_rudy(mapped["cannon"])
    real = ref["events_relative_to_hog_play_s"]
    cannon_rel = float(real["cannon_play"])

    match = cr_engine.new_match(data, common.P1_DECK, common.P2_DECK)
    common.idle(match, 220)

    if cannon_rel < 0:
        common.play(match, 2, "cannon", cannon_pos)
        common.idle(match, int(round(-cannon_rel * common.TPS)))
        t0 = int(match.tick)
        common.play(match, 1, "hog-rider", hog_pos)
    else:
        t0 = int(match.tick)
        common.play(match, 1, "hog-rider", hog_pos)

    frames: list[dict[str, Any]] = [common.frame(match, t0)]
    cannon_played = cannon_rel < 0
    cannon_tick = int(round(cannon_rel * common.TPS)) if cannon_rel >= 0 else None

    for _ in range(260):
        rel_ticks = int(match.tick) - t0
        if not cannon_played and cannon_tick is not None and rel_ticks >= cannon_tick:
            common.play(match, 2, "cannon", cannon_pos)
            cannon_played = True
        match.step()
        frames.append(common.frame(match, t0))

    releases = attack_release_hits(frames, "hog-rider", 1, "cannon", 2)
    sim_hits = [float(e["t"]) for e in releases]
    passive = passive_decay_events(frames, "cannon", 2, sim_hits)
    cannon_death = common.first_absence_after_seen(frames, "cannon", 2)
    hog_death = common.first_absence_after_seen(frames, "hog-rider", 1)

    expected_hits = [float(x) for x in real["hog_hits_cannon"]]
    tol = float(ref.get("comparison_tolerance_s", 0.10))
    comparisons: list[dict[str, Any]] = []

    for i in range(max(len(expected_hits), len(sim_hits))):
        expected = expected_hits[i] if i < len(expected_hits) else None
        sim = sim_hits[i] if i < len(sim_hits) else None
        delta = None if expected is None or sim is None else round(sim - expected, 3)
        comparisons.append({
            "event": f"hog_hit_cannon_{i + 1}",
            "real_s": expected,
            "sim_s": sim,
            "delta_s": delta,
            "pass": expected is not None and sim is not None and abs(delta) <= tol,
        })

    for name, expected, sim in (
        ("cannon_death", float(real["cannon_death"]), cannon_death),
        ("hog_death", float(real["hog_death"]), hog_death),
    ):
        delta = None if sim is None else round(float(sim) - expected, 3)
        comparisons.append({
            "event": name,
            "real_s": expected,
            "sim_s": sim,
            "delta_s": delta,
            "pass": sim is not None and abs(delta) <= tol,
        })

    ordered = sorted(
        comparisons,
        key=lambda r: float("inf") if r["real_s"] is None else float(r["real_s"]),
    )
    first_div = next((r for r in ordered if not r["pass"]), None)

    return {
        "scenario": ref["id"],
        "coordinate_mapping": {
            "hog_cell": mapped["hog"],
            "cannon_cell": mapped["cannon"],
            "hog_rudy": list(hog_pos),
            "cannon_rudy": list(cannon_pos),
        },
        "real_events": real,
        "sim_events": {
            "hog_first_movement_s": common.first_movement_time(frames, "hog-rider", 1),
            "hog_attack_releases_on_cannon": releases,
            "hog_hits_cannon_s": sim_hits,
            "cannon_passive_decay_events": passive,
            "cannon_death_s": cannon_death,
            "hog_death_s": hog_death,
            "hog_river_crossing": common.river_crossing(frames, "hog-rider", 1),
        },
        "comparison": comparisons,
        "first_divergence": first_div,
        "pass": first_div is None,
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--references", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    data = cr_engine.load_data(args.data_dir)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []
    for ref_path in args.references:
        ref = common.load_json(ref_path)
        result = replay_case(data, ref)
        path = out / f"{ref['id'].lower()}.json"
        common.save_json(path, result)
        summary.append({
            "scenario": result["scenario"],
            "pass": result["pass"],
            "first_divergence": result["first_divergence"],
            "real_events": result["real_events"],
            "sim_events": result["sim_events"],
        })

        print(f"\n=== {result['scenario']} ===")
        for row in result["comparison"]:
            print(
                f"{row['event']:20s} real={row['real_s']} sim={row['sim_s']} "
                f"delta={row['delta_s']} pass={row['pass']}"
            )
        print(f"FIRST DIVERGENCE: {result['first_divergence']}")
        passive = result["sim_events"]["cannon_passive_decay_events"]
        print(f"passive Cannon decay samples: {len(passive)}")

    common.save_json(out / "summary.json", {"cases": summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
