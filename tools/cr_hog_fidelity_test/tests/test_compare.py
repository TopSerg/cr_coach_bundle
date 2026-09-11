import json
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare import compare


def synthetic_solo_trace():
    hp_values = [3052, 2735, 2418, 2101, 1784, 1467, 1150, 833]
    # ``hog_solo.json`` stores tower HP transitions relative to the Hog play
    # (the source clip puts that play at 2.94 s).  Keep the fixture on the
    # same clock as the comparator's trace input.
    hit_times = [5.12, 6.66, 8.26, 9.84, 11.52, 13.08, 14.68]
    frames = [{
        "tick": 0, "t_rel_s": 0.0,
        "p1": {"king_hp": 4824, "princess_left_hp": 3052, "princess_right_hp": 3052},
        "p2": {"king_hp": 4824, "princess_left_hp": 3052, "princess_right_hp": 3052},
        "entities": []
    }]
    hp = 3052
    for i, (t, new_hp) in enumerate(zip(hit_times, hp_values[1:]), 1):
        hp = new_hp
        frames.append({
            "tick": round(t * 20), "t_rel_s": t,
            "p1": {"king_hp": 4824, "princess_left_hp": 3052, "princess_right_hp": 3052},
            "p2": {"king_hp": 4824, "princess_left_hp": 3052, "princess_right_hp": hp},
            "entities": [{"id": 1, "team": 1, "kind": "troop", "card": "hog-rider",
                          "x": -5100, "y": 9000, "hp": 1000, "max_hp": 1000,
                          "damage": 317, "alive": True, "attack_phase": "backswing"}]
        })
    return {"frames": frames}


def test_solo_comparator_accepts_exact_fixture():
    real = ROOT / "fixtures" / "real" / "hog_solo.json"
    with tempfile.TemporaryDirectory() as td:
        trace = Path(td) / "trace.json"
        trace.write_text(json.dumps(synthetic_solo_trace()), encoding="utf-8")
        result = compare(real, trace)
        assert result["pass"], result
