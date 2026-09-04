#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cr_engine

TPS = 20


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def card_index(match, player, card_key):
    hand = match.get_observation(player)["my_hand"]
    if card_key not in hand:
        raise RuntimeError(f"{card_key!r} not in P{player} hand: {hand}")
    return hand.index(card_key)


def idle(match, ticks):
    for _ in range(ticks):
        match.step()


def first_tower_hit_for_level(data, deck1, deck2, level):
    """Measure Hog damage independent of long travel: spawn close to P2 left tower."""
    m = cr_engine.new_match(data, deck1, deck2)
    idle(m, 200)
    before = m.p2_tower_hp()[1]
    m.spawn_troop(1, "hog-rider", -5100, 8500, level)
    for i in range(120):
        m.step()
        hp = m.p2_tower_hp()[1]
        if hp < before:
            return {
                "level": level,
                "damage": before - hp,
                "first_hit_s": round((i + 1) / TPS, 3),
            }
    return {"level": level, "damage": None, "first_hit_s": None}


def first_hit_from_placement(data, deck1, deck2, x, y, level, max_ticks=600):
    m = cr_engine.new_match(data, deck1, deck2)
    idle(m, 200)
    before = m.p2_tower_hp()[1]
    idx = card_index(m, 1, "hog-rider")
    m.play_card(1, idx, int(x), int(y), int(level))
    for i in range(max_ticks):
        m.step()
        hp = m.p2_tower_hp()[1]
        if hp < before:
            return round((i + 1) / TPS, 3)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--real", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg_all = load_json(args.config)
    cfg = cfg_all["scenarios"]["hog_solo"]
    real = load_json(args.real)
    target_damage = real["observed"]["damage_per_hit"]
    target_first_hit = real["observed"]["first_hit_after_play_s_estimate"]

    data = cr_engine.load_data(args.data_dir)
    deck1 = cfg["p1_deck"]
    deck2 = cfg["p2_deck"]

    stats = data.get_character_stats("hog-rider")

    level_scan = [first_tower_hit_for_level(data, deck1, deck2, level) for level in range(1, 17)]
    valid_damage = [r for r in level_scan if r["damage"] is not None]
    best_level = min(valid_damage, key=lambda r: abs(r["damage"] - target_damage)) if valid_damage else None
    chosen_level = best_level["level"] if best_level else 11

    # Broad placement scan. We intentionally include positions from deep behind the
    # princess tower to the bridge. If matching the real timing requires a position
    # that is visibly inconsistent with the demo, the problem is likely geometry/speed,
    # not coordinate recovery.
    x_values = [-5700, -5100, -4500, -3900, -3300]
    y_values = [-11400, -10200, -9000, -7800, -6600, -5400, -4200, -3000, -1800, -1200]
    placement_scan = []
    for x in x_values:
        for y in y_values:
            t = first_hit_from_placement(data, deck1, deck2, x, y, chosen_level)
            placement_scan.append({
                "x": x,
                "y": y,
                "level": chosen_level,
                "first_hit_s": t,
                "abs_error_s": None if t is None else round(abs(t - target_first_hit), 3),
            })

    valid_pos = [r for r in placement_scan if r["first_hit_s"] is not None]
    valid_pos.sort(key=lambda r: r["abs_error_s"])
    best_position = valid_pos[0] if valid_pos else None

    result = {
        "target_from_real_demo": {
            "damage_per_hit": target_damage,
            "first_hit_after_play_s": target_first_hit,
        },
        "rudy_hog_basic_stats": stats,
        "level_scan": level_scan,
        "best_level_by_damage": best_level,
        "placement_level_used": chosen_level,
        "best_position_by_first_hit": best_position,
        "placement_scan": placement_scan,
        "interpretation_hints": [
            "If no Rudy level produces 317 damage, the source stats/level mapping are wrong for this demo.",
            "If a level other than 11 produces 317 while the demo is level 11, that indicates a level-indexing/stat-data mismatch.",
            "If the first-hit timing only matches near the bridge while the video deployment was much deeper, investigate arena scale and movement-speed conversion.",
            "Do not tune Cannon behavior until Hog damage and solo travel timing are understood.",
        ],
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== RUDY HOG DIAGNOSTIC ===")
    print(f"Real damage/hit: {target_damage}")
    print("Rudy level scan:")
    for r in level_scan:
        mark = " <-- closest" if best_level and r["level"] == best_level["level"] else ""
        print(f"  level {r['level']:2d}: damage={str(r['damage']):>4s}{mark}")

    print(f"\nReal first hit after play: {target_first_hit:.3f}s")
    if best_position:
        print(
            "Best scanned position: "
            f"({best_position['x']}, {best_position['y']}) at level {chosen_level} -> "
            f"{best_position['first_hit_s']:.3f}s "
            f"(error {best_position['abs_error_s']:.3f}s)"
        )
    else:
        print("No scanned position reached the target tower.")

    print(f"\nFull report: {args.out}")


if __name__ == "__main__":
    main()
