from __future__ import annotations

import json
from pathlib import Path

from common import load_backend

from cr_coach.engine.crbot import CrBotEngineAdapter
from cr_coach.replay.schema import ReplayBattle


RESULTS = Path(__file__).resolve().parents[1] / "outputs" / "physical_tests"
MAX_TICKS = 500  # 25 s at 20 TPS
SAMPLE_EVERY = 5
HOG_TRIGGER_Y_MTILE = 17_000
CANNON_CELL = (8, 13)  # canonical cr-bot physical-lab probe


def _entities(snapshot: dict) -> list[dict]:
    return list(snapshot.get("entities", []))


def _find(snapshot: dict, card_id: str, owner: int) -> dict | None:
    matches = [
        entity
        for entity in _entities(snapshot)
        if entity.get("card_id") == card_id and entity.get("owner") == owner
    ]
    if not matches:
        return None
    alive = [entity for entity in matches if entity.get("alive", True) and int(entity.get("hp", 0)) > 0]
    return alive[0] if alive else matches[0]


def _label(snapshot: dict, uid: int | None) -> str | None:
    if uid is None:
        return None
    for entity in _entities(snapshot):
        if int(entity.get("uid", -1)) == int(uid):
            role = entity.get("role")
            suffix = f":{role}" if role else ""
            return f"{entity.get('card_id')}{suffix}#{uid}"
    return f"unknown#{uid}"


def main() -> int:
    engine, deck = load_backend()
    battle = ReplayBattle(
        battle_id="mechanics-hog-vs-cannon",
        ticks_per_second=20,
        team_deck=deck,
        opponent_deck=deck,
        team_initial_queue=deck,
        opponent_initial_queue=deck,
    )
    adapter = CrBotEngineAdapter.from_replay(battle, engine=engine)

    adapter.play_card(side="team", card="hog-rider", cell=(3, 20))

    cannon_queued_tick: int | None = None
    cannon_spawn_tick: int | None = None
    cannon_uid: int | None = None
    cannon_initial_hp: int | None = None
    cannon_min_hp: int | None = None
    hog_targeted_cannon_tick: int | None = None
    hog_start_x: int | None = None
    hog_max_x: int | None = None
    hog_min_hp: int | None = None
    samples: list[dict] = []
    key_events: list[dict] = []
    last_hog_target: int | None = None

    for target_tick in range(1, MAX_TICKS + 1):
        adapter.advance_to(target_tick)
        snapshot = adapter.snapshot()
        hog = _find(snapshot, "hog-rider", 0)
        cannon = _find(snapshot, "cannon", 1)

        if hog is not None:
            hog_x = int(hog.get("x_mtile", 0))
            hog_y = int(hog.get("y_mtile", 0))
            hog_hp = int(hog.get("hp", 0))
            if hog_start_x is None:
                hog_start_x = hog_x
            hog_max_x = hog_x if hog_max_x is None else max(hog_max_x, hog_x)
            hog_min_hp = hog_hp if hog_min_hp is None else min(hog_min_hp, hog_hp)

            current_target = hog.get("target_uid")
            if current_target != last_hog_target:
                key_events.append(
                    {
                        "tick": target_tick,
                        "event": "hog_target_changed",
                        "hog_x_mtile": hog_x,
                        "hog_y_mtile": hog_y,
                        "target_uid": current_target,
                        "target_label": _label(snapshot, current_target),
                    }
                )
                last_hog_target = current_target

            # This reproduces upstream cr-bot physical_lab.hog_cannon_probe:
            # deploy Cannon once Hog crosses y=17000 mtile.
            if cannon_queued_tick is None and hog_y <= HOG_TRIGGER_Y_MTILE:
                adapter.play_card(side="opponent", card="cannon", cell=CANNON_CELL)
                cannon_queued_tick = adapter.tick
                key_events.append(
                    {
                        "tick": adapter.tick,
                        "event": "cannon_queued",
                        "hog_x_mtile": hog_x,
                        "hog_y_mtile": hog_y,
                        "cannon_cell": list(CANNON_CELL),
                    }
                )

        if cannon is not None:
            if cannon_uid is None:
                cannon_uid = int(cannon["uid"])
                cannon_spawn_tick = int(cannon.get("spawn_tick", target_tick))
                cannon_initial_hp = int(cannon["hp"])
                cannon_min_hp = cannon_initial_hp
                key_events.append(
                    {
                        "tick": target_tick,
                        "event": "cannon_spawned",
                        "cannon_uid": cannon_uid,
                        "x_mtile": cannon.get("x_mtile"),
                        "y_mtile": cannon.get("y_mtile"),
                        "hp": cannon_initial_hp,
                    }
                )
            cannon_min_hp = min(int(cannon.get("hp", 0)), int(cannon_min_hp or cannon.get("hp", 0)))

        if (
            hog is not None
            and cannon_uid is not None
            and hog.get("target_uid") == cannon_uid
            and hog_targeted_cannon_tick is None
        ):
            hog_targeted_cannon_tick = target_tick
            key_events.append(
                {
                    "tick": target_tick,
                    "event": "hog_acquired_cannon",
                    "hog_x_mtile": hog.get("x_mtile"),
                    "hog_y_mtile": hog.get("y_mtile"),
                    "hog_hp": hog.get("hp"),
                    "cannon_hp": None if cannon is None else cannon.get("hp"),
                }
            )

        if target_tick % SAMPLE_EVERY == 0 or target_tick <= 2:
            samples.append(
                {
                    "tick": target_tick,
                    "time_s": round(target_tick / 20.0, 3),
                    "hog": None
                    if hog is None
                    else {
                        "uid": hog.get("uid"),
                        "x_mtile": hog.get("x_mtile"),
                        "y_mtile": hog.get("y_mtile"),
                        "hp": hog.get("hp"),
                        "alive": hog.get("alive"),
                        "target_uid": hog.get("target_uid"),
                        "target_label": _label(snapshot, hog.get("target_uid")),
                        "attack_count": hog.get("attack_count"),
                    },
                    "cannon": None
                    if cannon is None
                    else {
                        "uid": cannon.get("uid"),
                        "x_mtile": cannon.get("x_mtile"),
                        "y_mtile": cannon.get("y_mtile"),
                        "hp": cannon.get("hp"),
                        "alive": cannon.get("alive"),
                        "target_uid": cannon.get("target_uid"),
                        "target_label": _label(snapshot, cannon.get("target_uid")),
                        "attack_count": cannon.get("attack_count"),
                    },
                }
            )

        # Once the interaction has completed and Hog is dead, nothing useful
        # remains for this focused probe.
        if (
            cannon_queued_tick is not None
            and hog is not None
            and (not hog.get("alive", True) or int(hog.get("hp", 0)) <= 0)
        ):
            break

    if cannon_queued_tick is None:
        raise SystemExit("FAIL: Hog never crossed the y=17000 trigger used by cr-bot physical lab")
    if cannon_uid is None or cannon_spawn_tick is None or cannon_initial_hp is None:
        raise SystemExit("FAIL: Cannon was queued but never appeared in simulator state")
    if hog_targeted_cannon_tick is None:
        raise SystemExit("FAIL: Hog never acquired Cannon as its target")
    if cannon_min_hp is None or cannon_min_hp >= cannon_initial_hp:
        raise SystemExit(
            f"FAIL: Cannon was targeted but never damaged: initial={cannon_initial_hp}, min={cannon_min_hp}"
        )
    if hog_start_x is None or hog_max_x is None or hog_max_x <= hog_start_x + 500:
        raise SystemExit(
            f"FAIL: expected visible lateral pull toward central Cannon: start_x={hog_start_x}, max_x={hog_max_x}"
        )

    payload = {
        "test": "hog_vs_cannon",
        "ticks_per_second": 20,
        "hog_trigger_y_mtile": HOG_TRIGGER_Y_MTILE,
        "cannon_cell": list(CANNON_CELL),
        "cannon_queued_tick": cannon_queued_tick,
        "cannon_queued_time_s": round(cannon_queued_tick / 20.0, 3),
        "cannon_spawn_tick": cannon_spawn_tick,
        "cannon_uid": cannon_uid,
        "cannon_initial_hp": cannon_initial_hp,
        "cannon_min_hp": cannon_min_hp,
        "cannon_damage_observed": cannon_initial_hp - cannon_min_hp,
        "hog_targeted_cannon_tick": hog_targeted_cannon_tick,
        "hog_targeted_cannon_time_s": round(hog_targeted_cannon_tick / 20.0, 3),
        "hog_start_x_mtile": hog_start_x,
        "hog_max_x_mtile": hog_max_x,
        "hog_lateral_pull_mtile": hog_max_x - hog_start_x,
        "hog_min_hp": hog_min_hp,
        "key_events": key_events,
        "samples": samples,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    result_path = RESULTS / "hog_vs_cannon.json"
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print("\n=== TEST 05: Hog interaction with Cannon ===")
    print(
        f"Cannon queued: tick={cannon_queued_tick} t={cannon_queued_tick / 20.0:.2f}s "
        f"at cell={CANNON_CELL}"
    )
    print(
        f"Hog acquired Cannon: tick={hog_targeted_cannon_tick} "
        f"t={hog_targeted_cannon_tick / 20.0:.2f}s"
    )
    print(
        f"Cannon HP: {cannon_initial_hp} -> {cannon_min_hp} "
        f"(observed damage={cannon_initial_hp - cannon_min_hp})"
    )
    print(
        f"Hog lateral pull: x {hog_start_x} -> {hog_max_x} "
        f"(+{hog_max_x - hog_start_x} mtile)"
    )
    print("key events:")
    for event in key_events:
        if event["event"] in {
            "cannon_queued",
            "cannon_spawned",
            "hog_acquired_cannon",
            "hog_target_changed",
        }:
            print(f"  t={event['tick'] / 20.0:5.2f}s  {event}")
    print(f"trace saved: {result_path}")
    print("PASS: Cannon pulled Hog, Hog retargeted it, changed trajectory and damaged it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
