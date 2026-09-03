from __future__ import annotations

import json
from pathlib import Path

from common import load_backend

from cr_coach.engine.crbot import CrBotEngineAdapter
from cr_coach.replay.schema import ReplayBattle


RESULTS = Path(__file__).resolve().parents[1] / "outputs" / "physical_tests"
MAX_TICKS = 500  # 25 s at 20 TPS
SAMPLE_EVERY = 5  # 250 ms


def _entity_map(snapshot: dict) -> dict[int, dict]:
    return {int(entity["uid"]): entity for entity in snapshot.get("entities", [])}


def _enemy_towers(snapshot: dict) -> dict[int, dict]:
    return {
        int(entity["uid"]): entity
        for entity in snapshot.get("entities", [])
        if entity.get("kind") == "tower" and entity.get("owner") == 1
    }


def _hog(snapshot: dict) -> dict | None:
    candidates = [
        entity
        for entity in snapshot.get("entities", [])
        if entity.get("card_id") == "hog-rider" and entity.get("owner") == 0
    ]
    if not candidates:
        return None
    alive = [entity for entity in candidates if entity.get("alive", True) and entity.get("hp", 0) > 0]
    return alive[0] if alive else candidates[0]


def main() -> int:
    engine, deck = load_backend()
    battle = ReplayBattle(
        battle_id="mechanics-hog-vs-tower",
        ticks_per_second=20,
        team_deck=deck,
        opponent_deck=deck,
        team_initial_queue=deck,
        opponent_initial_queue=deck,
    )
    adapter = CrBotEngineAdapter.from_replay(battle, engine=engine)

    initial = adapter.snapshot()
    initial_tower_hp = {uid: int(tower["hp"]) for uid, tower in _enemy_towers(initial).items()}

    # Canonical physical-lab Hog placement from upstream cr-bot.
    adapter.play_card(side="team", card="hog-rider", cell=(3, 20))

    samples: list[dict] = []
    key_events: list[dict] = []
    last_target_uid: int | None = None
    first_hog: dict | None = None
    last_hog: dict | None = None
    min_y = 10**9
    first_tower_damage_tick: int | None = None
    first_tower_damage_uid: int | None = None

    for target_tick in range(1, MAX_TICKS + 1):
        adapter.advance_to(target_tick)
        snapshot = adapter.snapshot()
        entities = _entity_map(snapshot)
        hog = _hog(snapshot)
        enemy_towers = _enemy_towers(snapshot)

        if hog is not None:
            if first_hog is None:
                first_hog = dict(hog)
            last_hog = dict(hog)
            min_y = min(min_y, int(hog.get("y_mtile", min_y)))
            target_uid = hog.get("target_uid")
            if target_uid != last_target_uid:
                target = entities.get(int(target_uid)) if target_uid is not None else None
                key_events.append(
                    {
                        "tick": target_tick,
                        "event": "hog_target_changed",
                        "hog_x_mtile": hog.get("x_mtile"),
                        "hog_y_mtile": hog.get("y_mtile"),
                        "target_uid": target_uid,
                        "target_card": None if target is None else target.get("card_id"),
                        "target_kind": None if target is None else target.get("kind"),
                        "target_role": None if target is None else target.get("role"),
                    }
                )
                last_target_uid = target_uid

        for uid, tower in enemy_towers.items():
            if int(tower["hp"]) < initial_tower_hp[uid] and first_tower_damage_tick is None:
                first_tower_damage_tick = target_tick
                first_tower_damage_uid = uid
                key_events.append(
                    {
                        "tick": target_tick,
                        "event": "first_enemy_tower_damage",
                        "tower_uid": uid,
                        "tower_role": tower.get("role"),
                        "tower_hp": tower.get("hp"),
                        "tower_hp_before": initial_tower_hp[uid],
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
                        "deploy_remaining_us": hog.get("deploy_remaining_us"),
                        "target_uid": hog.get("target_uid"),
                        "attack_count": hog.get("attack_count"),
                    },
                    "enemy_towers": {
                        str(uid): {
                            "role": tower.get("role"),
                            "hp": tower.get("hp"),
                        }
                        for uid, tower in enemy_towers.items()
                    },
                }
            )

        if hog is not None and (not hog.get("alive", True) or int(hog.get("hp", 0)) <= 0):
            break

    final = adapter.snapshot()
    damaged_towers = [
        {
            "uid": uid,
            "role": tower.get("role"),
            "hp_before": initial_tower_hp[uid],
            "hp_after": tower.get("hp"),
            "damage": initial_tower_hp[uid] - int(tower["hp"]),
        }
        for uid, tower in _enemy_towers(final).items()
        if int(tower["hp"]) < initial_tower_hp[uid]
    ]

    target_was_enemy_tower = any(
        event["event"] == "hog_target_changed" and event.get("target_kind") == "tower"
        for event in key_events
    )

    if first_hog is None or last_hog is None:
        raise SystemExit("FAIL: Hog never appeared in simulator state")
    if min_y >= int(first_hog["y_mtile"]) - 5_000:
        raise SystemExit(
            f"FAIL: Hog did not travel far enough: start_y={first_hog['y_mtile']} min_y={min_y}"
        )
    if not target_was_enemy_tower:
        raise SystemExit("FAIL: Hog never acquired an enemy tower as target")
    if first_tower_damage_tick is None or not damaged_towers:
        raise SystemExit("FAIL: Hog never damaged an enemy tower")

    payload = {
        "test": "hog_vs_tower",
        "ticks_per_second": 20,
        "max_ticks": MAX_TICKS,
        "first_hog": {
            "uid": first_hog.get("uid"),
            "x_mtile": first_hog.get("x_mtile"),
            "y_mtile": first_hog.get("y_mtile"),
            "hp": first_hog.get("hp"),
        },
        "last_hog": {
            "uid": last_hog.get("uid"),
            "x_mtile": last_hog.get("x_mtile"),
            "y_mtile": last_hog.get("y_mtile"),
            "hp": last_hog.get("hp"),
            "alive": last_hog.get("alive"),
            "attack_count": last_hog.get("attack_count"),
        },
        "min_y_mtile": min_y,
        "first_tower_damage_tick": first_tower_damage_tick,
        "first_tower_damage_time_s": round(first_tower_damage_tick / 20.0, 3),
        "first_tower_damage_uid": first_tower_damage_uid,
        "damaged_towers": damaged_towers,
        "key_events": key_events,
        "samples": samples,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    result_path = RESULTS / "hog_vs_tower.json"
    result_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print("\n=== TEST 04: Hog lives against towers only ===")
    print(f"spawn: ({first_hog['x_mtile']}, {first_hog['y_mtile']}) hp={first_hog['hp']}")
    print(f"furthest y: {min_y} mtile")
    print(f"first tower damage: tick={first_tower_damage_tick} t={first_tower_damage_tick / 20.0:.2f}s")
    print("damaged towers:")
    for tower in damaged_towers:
        print(
            f"  role={tower['role']} hp {tower['hp_before']} -> {tower['hp_after']} "
            f"(damage={tower['damage']})"
        )
    print("target changes:")
    for event in key_events:
        if event["event"] == "hog_target_changed":
            print(
                f"  t={event['tick'] / 20.0:5.2f}s  "
                f"pos=({event['hog_x_mtile']},{event['hog_y_mtile']})  "
                f"target={event['target_card']}:{event['target_role']}"
            )
    print(f"trace saved: {result_path}")
    print("PASS: Hog deployed, moved across the arena, targeted and damaged an enemy tower")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
