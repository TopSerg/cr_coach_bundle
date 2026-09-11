"""Replay JSON/CSV placements through the patched Rudy engine.

Rudy is the video-calibrated backend.  Its Python extension is optional, so
this module imports ``cr_engine`` only when selected by the CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from .viewer import write_viewer


TPS = 20
RUNTIME_VERSION = "cr-coach-rudy-replay-v1"
RUDY_UPSTREAM = "050275d70b84614953877e8075dc4b8ba907c67f"
PHYSICS_PROFILE = "rudy-hog-cannon-princess-core-v1"
RULESET_ID = "tournament-11-overlay-v1"
PAD_CARDS = (
    "hog-rider",
    "cannon",
    "knight",
    "archers",
    "fireball",
    "giant",
    "valkyrie",
    "musketeer",
    "zap",
)
CARD_ALIASES = {"log": "the-log"}
TOWER_MAX_HP = {"king-tower": 4824, "princess-tower": 3052}
TOWER_SPECS = (
    (0xFFFF_FF01, 0, "king-tower", "king", 9_000, 28_500),
    (0xFFFF_FF02, 0, "princess-tower", "left", 3_500, 25_500),
    (0xFFFF_FF03, 0, "princess-tower", "right", 14_500, 25_500),
    (0xFFFF_FF04, 1, "king-tower", "king", 9_000, 3_500),
    (0xFFFF_FF05, 1, "princess-tower", "left", 14_500, 6_500),
    (0xFFFF_FF06, 1, "princess-tower", "right", 3_500, 6_500),
)


class RudyRuntimeError(RuntimeError):
    pass


def _get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, values: Iterable[Any]) -> None:
    text = "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values)
    _atomic(path, text)


def _atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _card_id(card: str, available: set[str]) -> str:
    value = CARD_ALIASES.get(card, card)
    if value not in available:
        raise RudyRuntimeError(f"card {card!r} is not available in the Rudy data overlay")
    return value


def _events(spec: Any) -> list[Any]:
    return list(_get(spec, "events", ()) or ())


def _decks(spec: Any, available: set[str]) -> tuple[list[str], list[str]]:
    mode = _get(spec, "mode", "placements")
    result: list[list[str]] = []
    for side in ("team", "opponent"):
        declared = list(_get(spec, f"{side}_initial_queue", None) or _get(spec, f"{side}_deck", ()) or ())
        if mode == "placements":
            declared = []
            for event in _events(spec):
                if _get(event, "side") != side or _get(event, "event_type", "card_play") != "card_play":
                    continue
                card = _card_id(str(_get(event, "card")), available)
                if card not in declared:
                    declared.append(card)
        else:
            declared = [_card_id(str(card), available) for card in declared]
        if len(declared) > 8:
            raise RudyRuntimeError(f"{side} uses more than eight distinct cards")
        for card in PAD_CARDS:
            if len(declared) == 8:
                break
            if card in available and card not in declared:
                declared.append(card)
        if len(declared) != 8:
            raise RudyRuntimeError(f"could not construct an eight-card {side} deck")
        result.append(declared)
    return result[0], result[1]


def _rudy_xy(event: Any) -> tuple[int, int]:
    x = int(_get(event, "x_mtile"))
    y = int(_get(event, "y_mtile"))
    return x - 9_000, 16_000 - y


def _world_xy(entity: Mapping[str, Any]) -> tuple[int, int]:
    return int(entity.get("x", 0)) + 9_000, 16_000 - int(entity.get("y", 0))


def _tower_entities(match: Any) -> list[dict[str, Any]]:
    hp = list(match.p1_tower_hp()) + list(match.p2_tower_hp())
    # Rudy order is king, left, right for each player, matching TOWER_SPECS.
    entities: list[dict[str, Any]] = []
    for current_hp, (uid, owner, card, role, x, y) in zip(hp, TOWER_SPECS):
        entities.append(
            {
                "uid": uid,
                "owner": owner,
                "card_id": card,
                "kind": "tower",
                "role": role,
                "alive": current_hp > 0,
                "hp": max(0, int(current_hp)),
                "max_hp": TOWER_MAX_HP[card],
                "x_mtile": x,
                "y_mtile": y,
            }
        )
    return entities


def _snapshot(match: Any, *, relative_tick: int, mode: str) -> dict[str, Any]:
    entities: list[dict[str, Any]] = _tower_entities(match)
    projectiles: list[dict[str, Any]] = []
    for raw_value in match.get_entities():
        raw = dict(raw_value)
        x, y = _world_xy(raw)
        item = {
            "uid": int(raw["id"]),
            "owner": int(raw["team"]) - 1,
            "card_id": str(raw.get("card_key", "unknown")),
            "kind": str(raw.get("kind", "entity")),
            "alive": bool(raw.get("alive", True)),
            "hp": int(raw.get("hp", 0)),
            "max_hp": int(raw.get("max_hp", 0)),
            "x_mtile": x,
            "y_mtile": y,
            "target_uid": raw.get("target_id"),
            "deploy_remaining_us": max(0, int(raw.get("deploy_timer", 0))) * 50_000,
            "attack_phase": raw.get("attack_phase"),
        }
        if item["kind"] == "projectile":
            item["source_uid"] = raw.get("projectile_source_id")
            item["target_uid"] = raw.get("projectile_target_id")
            projectiles.append(item)
        else:
            entities.append(item)
    players: list[dict[str, Any]] = []
    for player in (1, 2):
        players.append(
            {
                "crowns": int(getattr(match, f"p{player}_crowns")),
                "elixir_milli": None if mode == "placements" else int(getattr(match, f"p{player}_elixir_raw")) // 10,
                "hand": None if mode == "placements" else list(getattr(match, f"p{player}_hand")()),
            }
        )
    result = dict(match.get_result())
    return {
        "tick": relative_tick,
        "state_tick": relative_tick,
        "elapsed_us": relative_tick * 50_000,
        "phase": str(match.phase),
        "terminal": not bool(match.is_running),
        "winner": None if result.get("winner") == "in_progress" else result.get("winner"),
        "entities": entities,
        "projectiles": projectiles,
        "players": players,
        "backend": "rudy",
        "runtime_version": RUNTIME_VERSION,
        "physics_profile": PHYSICS_PROFILE,
        "mode": mode,
    }


def _changes(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    before = {int(row["uid"]): row for row in previous["entities"] if row["kind"] != "tower"}
    after = {int(row["uid"]): row for row in current["entities"] if row["kind"] != "tower"}
    all_before = {int(row["uid"]): row for row in previous["entities"]}
    all_after = {int(row["uid"]): row for row in current["entities"]}
    tick = int(previous["tick"])
    rows: list[dict[str, Any]] = []
    releases: dict[int, list[dict[str, Any]]] = {}
    for uid in sorted(all_before.keys() & all_after.keys()):
        old, new = all_before[uid], all_after[uid]
        if old.get("attack_phase") == "windup" and new.get("attack_phase") == "backswing":
            target_uid = new.get("target_uid")
            if not isinstance(target_uid, int):
                target_uid = old.get("target_uid")
            if isinstance(target_uid, int):
                releases.setdefault(target_uid, []).append(new)
    for uid in sorted(after.keys() - before.keys()):
        entity = after[uid]
        rows.append({"tick": tick, "state_tick": tick + 1, "kind": "entity_created", "data": entity})
    for uid in sorted(before.keys() - after.keys()):
        entity = before[uid]
        sources = releases.get(uid, [])
        if len(sources) == 1:
            source = sources[0]
            rows.append({"tick": tick, "state_tick": tick + 1, "kind": "damage_applied", "data": {"source_uid": source["uid"], "source_card_id": source["card_id"], "target_uid": uid, "target_card_id": entity["card_id"], "damage": int(entity.get("hp", 0)), "hp_after": 0}})
        rows.append({"tick": tick, "state_tick": tick + 1, "kind": "entity_died", "data": {"uid": uid, "card_id": entity["card_id"], "player": entity["owner"]}})
    for uid in sorted(all_before.keys() & all_after.keys()):
        old, new = all_before[uid], all_after[uid]
        damage = int(old.get("hp", 0)) - int(new.get("hp", 0))
        if damage > 0:
            sources = releases.get(uid, [])
            source = sources[0] if len(sources) == 1 else None
            rows.append({"tick": tick, "state_tick": tick + 1, "kind": "damage_applied" if source else "damage_observed", "data": {"source_uid": None if source is None else source["uid"], "source_card_id": None if source is None else source["card_id"], "target_uid": uid, "target_card_id": new["card_id"], "damage": damage, "hp_after": new["hp"]}})
        if old.get("target_uid") != new.get("target_uid"):
            rows.append({"tick": tick, "state_tick": tick + 1, "kind": "target_changed", "data": {"uid": uid, "old_target": old.get("target_uid"), "target_uid": new.get("target_uid")}})
        if old.get("attack_phase") == "windup" and new.get("attack_phase") == "backswing":
            rows.append({"tick": tick, "state_tick": tick + 1, "kind": "attack_released", "data": {"uid": uid, "card_id": new["card_id"], "target_uid": new.get("target_uid")}})
    return rows


def _play(match: Any, event: Any, *, mode: str, available: set[str]) -> int | None:
    player = 1 if _get(event, "side") == "team" else 2
    event_type = _get(event, "event_type", "card_play")
    if event_type == "ability_activation":
        card = _get(event, "ability_card", None)
        candidates = [dict(row) for row in match.get_entities() if int(row["team"]) == player and row.get("alive", True)]
        if card:
            card = _card_id(str(card), available)
            candidates = [row for row in candidates if row.get("card_key") == card]
        if len(candidates) != 1:
            raise RudyRuntimeError(f"ability event requires exactly one matching live hero, found {len(candidates)}")
        match.activate_hero(int(candidates[0]["id"]))
        return int(candidates[0]["id"])
    card = _card_id(str(_get(event, "card")), available)
    x, y = _rudy_xy(event)
    if mode == "placements":
        method = getattr(match, "play_observed_card", None)
        if method is None:
            raise RudyRuntimeError("installed cr_engine lacks play_observed_card(); install the current CR Coach Rudy bundle")
        return int(method(player, card, x, y, 11))
    hand = list(match.p1_hand() if player == 1 else match.p2_hand())
    if card not in hand:
        raise RudyRuntimeError(f"{card!r} is not in player {player} hand at tick {_get(event, 'tick')}: {hand}")
    return int(match.play_card(player, hand.index(card), x, y, 11))


def run_rudy_replay(spec: Any, out_dir: str | Path, *, data_dir: str | Path, sample_ticks: int = 1) -> dict[str, Any]:
    if type(sample_ticks) is not int or sample_ticks <= 0:
        raise ValueError("sample_ticks must be a positive integer")
    if int(_get(spec, "ticks_per_second", TPS)) != TPS:
        raise ValueError("Rudy runtime requires a 20 Hz replay")
    validator = getattr(spec, "validate", None)
    if callable(validator):
        validator()
    if _get(spec, "initial_state", None):
        raise RudyRuntimeError("Rudy checkpoint continuation is not implemented")

    try:
        import cr_engine
    except ImportError as exc:
        raise RudyRuntimeError("cr_engine is not installed; install the current CR Coach Rudy wheel") from exc

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    data = cr_engine.load_data(str(Path(data_dir).resolve()))
    available = {str(dict(row)["key"]) for row in data.list_cards()}
    decks = _decks(spec, available)
    match = cr_engine.new_match(data, decks[0], decks[1])
    mode = str(_get(spec, "mode", "placements"))
    replay_events = _events(spec)
    end_tick = int(_get(spec, "end_tick"))
    snapshots = [_snapshot(match, relative_tick=0, mode=mode)]
    generated: list[dict[str, Any]] = []
    status, failed_index, error = "horizon_reached", None, None
    event_index = 0

    try:
        for tick in range(end_tick):
            while event_index < len(replay_events) and int(_get(replay_events[event_index], "tick")) == tick:
                event = replay_events[event_index]
                try:
                    uid = _play(match, event, mode=mode, available=available)
                except Exception:
                    failed_index = event_index
                    raise
                generated.append(
                    {
                        "tick": tick,
                        "state_tick": tick + 1,
                        "kind": "card_played" if _get(event, "event_type") == "card_play" else "ability_activated",
                        "data": {"side": _get(event, "side"), "player": 0 if _get(event, "side") == "team" else 1, "card_id": _get(event, "card", _get(event, "ability_card")), "uid": uid},
                    }
                )
                event_index += 1
            previous = _snapshot(match, relative_tick=tick, mode=mode)
            match.step()
            current = _snapshot(match, relative_tick=tick + 1, mode=mode)
            generated.extend(_changes(previous, current))
            if (tick + 1) % sample_ticks == 0 or tick + 1 == end_tick or not match.is_running:
                snapshots.append(current)
            if not match.is_running:
                status = "terminal"
                if event_index < len(replay_events):
                    failed_index = event_index
                    raise RudyRuntimeError("match ended before the next replay event")
                break
        if event_index != len(replay_events):
            failed_index = event_index
            raise RudyRuntimeError("replay contains an event beyond end_tick")
    except Exception as exc:
        status, error = "failed", repr(exc)

    final = snapshots[-1]
    digest = hashlib.sha256(json.dumps(final, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    used_cards = sorted({_card_id(str(_get(event, "card")), available) for event in replay_events if _get(event, "event_type") == "card_play"})
    core_validated = set(used_cards).issubset({"hog-rider", "cannon"})
    report = {
        "schema_version": 1,
        "battle_id": _get(spec, "battle_id", "replay"),
        "status": status,
        "error": error,
        "failed_event_index": failed_index,
        "end_tick": int(final["tick"]),
        "requested_end_tick": end_tick,
        "event_count": len(replay_events),
        "simulated_event_count": len(generated),
        "mode": mode,
        "runtime_version": RUNTIME_VERSION,
        "upstream_commit": RUDY_UPSTREAM,
        "physics_profile": PHYSICS_PROFILE,
        "ruleset_id": RULESET_ID,
        "state_hash": digest,
        "resumable": False,
        "cards_used": used_cards,
        "fidelity": "validated_hog_cannon_princess_core" if core_validated else "unverified_for_selected_cards",
        "fidelity_scope": "Solo Hog and pure Hog/Cannon/Princess-Tower video interactions only",
    }
    checkpoint = {
        "schema_version": 1,
        "checkpoint_version": 1,
        "runtime_version": RUNTIME_VERSION,
        "physics_profile": PHYSICS_PROFILE,
        "resumable": False,
        "reason": "Rudy does not expose authoritative state serialization",
        "state": None,
    }
    _write_jsonl(output / "snapshots.jsonl", snapshots)
    _write_jsonl(output / "events.jsonl", generated)
    _write_json(output / "report.json", report)
    _write_json(output / "checkpoint.json", checkpoint)
    write_viewer(output / "replay.html", snapshots=snapshots, events=generated, report=report)
    return report


__all__ = ["PHYSICS_PROFILE", "RUNTIME_VERSION", "RudyRuntimeError", "run_rudy_replay"]
