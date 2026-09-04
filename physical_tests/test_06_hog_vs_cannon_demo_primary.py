from __future__ import annotations

import json
from pathlib import Path

from common import load_backend

from cr_coach.engine.crbot import CrBotEngineAdapter
from cr_coach.replay.schema import ReplayBattle


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "outputs" / "physical_tests"
REFERENCE_PATH = Path(__file__).resolve().parent / "references" / "d03_hog_cannon_02_primary.json"
MAX_TICKS = 260  # 13 s at 20 TPS
TICKS_PER_SECOND = 20
HOG_CELL = (9, 18)
CANNON_CELL = (9, 10)


def _entity(snapshot: dict, *, card_id: str | None = None, owner: int | None = None, uid: int | None = None) -> dict | None:
    matches = []
    for entity in snapshot.get("entities", []):
        if uid is not None and int(entity.get("uid", -1)) != uid:
            continue
        if card_id is not None and entity.get("card_id") != card_id:
            continue
        if owner is not None and entity.get("owner") != owner:
            continue
        matches.append(entity)
    if not matches:
        return None
    alive = [entity for entity in matches if entity.get("alive", True) and int(entity.get("hp", 0)) > 0]
    return alive[0] if alive else matches[0]


def _time_s(tick: int) -> float:
    return round(tick / TICKS_PER_SECOND, 3)


def _load_reference() -> dict:
    data = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    if data["ticks_per_second"] != TICKS_PER_SECOND:
        raise SystemExit("FAIL: reference timebase differs from simulator timebase")
    return data


def main() -> int:
    reference = _load_reference()
    engine, deck = load_backend()
    battle = ReplayBattle(
        battle_id="demo-d03-hog-cannon-primary",
        ticks_per_second=TICKS_PER_SECOND,
        team_deck=deck,
        opponent_deck=deck,
        team_initial_queue=deck,
        opponent_initial_queue=deck,
    )
    adapter = CrBotEngineAdapter.from_replay(battle, engine=engine)

    demo = reference["events_relative_to_hog_play_s"]
    cannon_play_tick = int(round(float(demo["cannon_play"]) * TICKS_PER_SECOND))
    tolerance_s = float(reference["comparison_tolerance_s"])

    adapter.play_card(side="team", card="hog-rider", cell=HOG_CELL)

    hog_uid: int | None = None
    cannon_uid: int | None = None
    cannon_placed = False
    cannon_seen = False
    hog_seen = False
    hog_attack_count = 0
    cannon_attack_count = 0
    hog_hit_ticks: list[int] = []
    cannon_fire_ticks: list[int] = []
    acquire_tick: int | None = None
    cannon_death_tick: int | None = None
    hog_death_tick: int | None = None
    retarget_tick: int | None = None
    last_hog_target: int | None = None
    samples: list[dict] = []

    for target_tick in range(1, MAX_TICKS + 1):
        if not cannon_placed and adapter.tick == cannon_play_tick:
            adapter.play_card(side="opponent", card="cannon", cell=CANNON_CELL)
            cannon_placed = True

        adapter.advance_to(target_tick)
        snapshot = adapter.snapshot()

        if hog_uid is None:
            hog = _entity(snapshot, card_id="hog-rider", owner=0)
            if hog is not None:
                hog_uid = int(hog["uid"])
                hog_seen = True
        else:
            hog = _entity(snapshot, uid=hog_uid)

        if cannon_uid is None:
            cannon = _entity(snapshot, card_id="cannon", owner=1)
            if cannon is not None:
                cannon_uid = int(cannon["uid"])
                cannon_seen = True
        else:
            cannon = _entity(snapshot, uid=cannon_uid)

        if hog is not None and cannon_uid is not None:
            target_uid = hog.get("target_uid")
            if target_uid == cannon_uid and acquire_tick is None:
                acquire_tick = target_tick
            if last_hog_target == cannon_uid and target_uid != cannon_uid and cannon_death_tick is not None and retarget_tick is None:
                retarget_tick = target_tick
            last_hog_target = target_uid

            current_attacks = int(hog.get("attack_count", 0) or 0)
            while current_attacks > hog_attack_count:
                if target_uid == cannon_uid:
                    hog_hit_ticks.append(target_tick)
                hog_attack_count += 1

        if cannon is not None:
            current_attacks = int(cannon.get("attack_count", 0) or 0)
            while current_attacks > cannon_attack_count:
                cannon_fire_ticks.append(target_tick)
                cannon_attack_count += 1

        if cannon_seen and cannon_death_tick is None:
            if cannon is None or not cannon.get("alive", True) or int(cannon.get("hp", 0)) <= 0:
                cannon_death_tick = target_tick

        if hog_seen and hog_death_tick is None:
            if hog is None or not hog.get("alive", True) or int(hog.get("hp", 0)) <= 0:
                hog_death_tick = target_tick

        if target_tick % 2 == 0:
            samples.append(
                {
                    "tick": target_tick,
                    "time_s": _time_s(target_tick),
                    "hog": None if hog is None else {
                        "x_mtile": hog.get("x_mtile"),
                        "y_mtile": hog.get("y_mtile"),
                        "hp": hog.get("hp"),
                        "alive": hog.get("alive"),
                        "target_uid": hog.get("target_uid"),
                        "attack_count": hog.get("attack_count"),
                    },
                    "cannon": None if cannon is None else {
                        "x_mtile": cannon.get("x_mtile"),
                        "y_mtile": cannon.get("y_mtile"),
                        "hp": cannon.get("hp"),
                        "alive": cannon.get("alive"),
                        "target_uid": cannon.get("target_uid"),
                        "attack_count": cannon.get("attack_count"),
                    },
                }
            )

        if hog_death_tick is not None and cannon_death_tick is not None:
            break

    if not cannon_placed:
        raise SystemExit("FAIL: Cannon play tick was never reached")
    if hog_uid is None or cannon_uid is None:
        raise SystemExit(f"FAIL: expected Hog and Cannon in simulator state: hog={hog_uid}, cannon={cannon_uid}")
    if acquire_tick is None:
        raise SystemExit("FAIL: Hog never acquired Cannon")
    if not hog_hit_ticks:
        raise SystemExit("FAIL: Hog acquired Cannon but never attacked it")
    if cannon_death_tick is None:
        raise SystemExit("FAIL: Cannon did not die within test window")
    if hog_death_tick is None:
        raise SystemExit("FAIL: Hog did not die within test window")

    sim_metrics = {
        "cannon_play": _time_s(cannon_play_tick),
        "hog_acquire_cannon": _time_s(acquire_tick),
        "hog_hits_cannon": [_time_s(tick) for tick in hog_hit_ticks],
        "cannon_death": _time_s(cannon_death_tick),
        "hog_death": _time_s(hog_death_tick),
        "cannon_fires": [_time_s(tick) for tick in cannon_fire_ticks],
        "retarget_after_cannon": None if retarget_tick is None else _time_s(retarget_tick),
    }

    comparisons: list[dict] = []
    metric_pairs = [
        ("first_hog_hit_on_cannon", float(demo["hog_hits_cannon"][0]), sim_metrics["hog_hits_cannon"][0]),
        ("cannon_death", float(demo["cannon_death"]), sim_metrics["cannon_death"]),
        ("hog_death", float(demo["hog_death"]), sim_metrics["hog_death"]),
    ]
    for name, expected, actual in metric_pairs:
        error = round(actual - expected, 3)
        comparisons.append(
            {
                "metric": name,
                "demo_s": expected,
                "sim_s": actual,
                "error_s": error,
                "within_tolerance": abs(error) <= tolerance_s,
            }
        )

    for i, expected in enumerate(demo["hog_hits_cannon"]):
        if i >= len(sim_metrics["hog_hits_cannon"]):
            comparisons.append(
                {
                    "metric": f"hog_hit_{i + 1}",
                    "demo_s": float(expected),
                    "sim_s": None,
                    "error_s": None,
                    "within_tolerance": False,
                }
            )
            continue
        actual = sim_metrics["hog_hits_cannon"][i]
        error = round(actual - float(expected), 3)
        comparisons.append(
            {
                "metric": f"hog_hit_{i + 1}",
                "demo_s": float(expected),
                "sim_s": actual,
                "error_s": error,
                "within_tolerance": abs(error) <= tolerance_s,
            }
        )

    first_divergence = next((item for item in comparisons if not item["within_tolerance"]), None)
    payload = {
        "test": "hog_vs_cannon_demo_primary",
        "reference": reference,
        "simulation": {
            "hog_cell": list(HOG_CELL),
            "cannon_cell": list(CANNON_CELL),
            "metrics_relative_to_hog_play_s": sim_metrics,
        },
        "comparisons": comparisons,
        "first_divergence": first_divergence,
        "samples": samples,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    result_path = RESULTS / "hog_vs_cannon_demo_primary.json"
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print("\n=== TEST 06: PRIMARY demo Hog vs Cannon fidelity ===")
    print(f"geometry: Hog@{HOG_CELL}, Cannon@{CANNON_CELL}, Cannon play t={cannon_play_tick / 20.0:.2f}s")
    print(f"demo Hog hits: {demo['hog_hits_cannon']}")
    print(f"sim  Hog hits: {sim_metrics['hog_hits_cannon']}")
    print(f"demo Cannon death: {demo['cannon_death']:.2f}s | sim: {sim_metrics['cannon_death']:.2f}s")
    print(f"demo Hog death:    {demo['hog_death']:.2f}s | sim: {sim_metrics['hog_death']:.2f}s")
    if first_divergence is None:
        print(f"PASS: all annotated timing metrics are within ±{tolerance_s:.2f}s")
    else:
        print("FIRST DIVERGENCE:")
        print(
            f"  {first_divergence['metric']}: demo={first_divergence['demo_s']}s "
            f"sim={first_divergence['sim_s']}s error={first_divergence['error_s']}s"
        )
    print(f"trace saved: {result_path}")
    return 0 if first_divergence is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
