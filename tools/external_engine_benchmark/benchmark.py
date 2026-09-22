#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFS = [
    ROOT / "physical_tests/references/d03_hog_cannon_01_secondary.json",
    ROOT / "physical_tests/references/d02_hog_cannon_01_crossdemo.json",
    ROOT / "physical_tests/references/d03_hog_cannon_02_primary.json",
]


def load_refs():
    return [json.loads(p.read_text(encoding="utf-8")) for p in REFS]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def score(reference: dict, observed: dict) -> dict:
    expected = reference["events_relative_to_hog_play_s"]
    tol = float(reference.get("comparison_tolerance_s", 0.1))
    rows = []

    def add(name, exp, got):
        err = None if got is None else round(float(got) - float(exp), 3)
        rows.append({
            "metric": name,
            "real_s": float(exp),
            "sim_s": None if got is None else float(got),
            "error_s": err,
            "pass": got is not None and abs(err) <= tol + 1e-9,
        })

    exp_hits = expected.get("hog_hits_cannon", [])
    got_hits = observed.get("hog_hits_cannon", [])
    for i, exp in enumerate(exp_hits):
        add(f"hog_hit_{i+1}", exp, got_hits[i] if i < len(got_hits) else None)
    if "cannon_lethal_hit" in expected:
        add("cannon_lethal_hit", expected["cannon_lethal_hit"], observed.get("cannon_lethal_hit"))
    add("cannon_death", expected["cannon_death"], observed.get("cannon_death"))
    add("hog_death", expected["hog_death"], observed.get("hog_death"))
    return {
        "reference_id": reference["id"],
        "pass": all(r["pass"] for r in rows),
        "tolerance_s": tol,
        "metrics": rows,
        "max_abs_error_s": max(
            [abs(r["error_s"]) for r in rows if r["error_s"] is not None] or [999.0]
        ),
    }


def key_like(mapping, wanted: str):
    nw = norm(wanted)
    for key in mapping:
        if norm(str(key)) == nw:
            return key
    raise KeyError(f"{wanted!r} not found; sample keys={list(mapping)[:20]}")


def run_hasty(mode: str) -> dict:
    repo = ROOT / "third_party/Hasty-CR"
    sys.path.insert(0, str(repo))
    from sim import arena
    from sim.gamedata import load_gamedata
    from sim.match import Match
    from sim.entities import make_unit

    data_root = repo / "tmp/gamedata/csv_logic"
    cards = load_gamedata(level=11, root=data_root)
    hk = key_like(cards, "hog_rider")
    ck = key_like(cards, "cannon")

    if mode == "normalized":
        hog = cards[hk]
        cannon = cards[ck]
        hu = dataclasses.replace(
            hog.unit,
            hitpoints=1697,
            damage=317,
            hit_speed_ms=1600,
            load_time_ms=1000,
            range_mt=800,
            speed_mt_per_sec=120,
            deploy_time_ms=1000,
            target_only_buildings=True,
            attacks_ground=True,
            attacks_air=False,
            jump_enabled=True,
        )
        cu_kwargs = dict(
            hitpoints=824,
            damage=202,
            hit_speed_ms=1000,
            load_time_ms=1000,
            range_mt=5500,
            deploy_time_ms=1000,
            attacks_ground=True,
            attacks_air=False,
        )
        if "lifetime_ms" in getattr(cannon.unit, "__dataclass_fields__", {}):
            cu_kwargs["lifetime_ms"] = 30000
        cu = dataclasses.replace(cannon.unit, **cu_kwargs)
        cards = dict(cards)
        cards[hk] = dataclasses.replace(hog, unit=hu)
        cards[ck] = dataclasses.replace(cannon, unit=cu)

    refs = load_refs()
    results = []
    for ref in refs:
        # PRIMARY contains already-live Ice Golem + Hunter context. It is run,
        # but not declared strict unless context injection succeeds.
        deck_bottom = [hk] * 8
        deck_top = [ck] * 8
        match = Match(cards=cards, decks=(deck_bottom, deck_top), seed=1, spells={}, level=11)
        match.players[1].hand = [hk] * 4
        match.players[1].queue = [hk] * 4
        match.players[-1].hand = [ck] * 4
        match.players[-1].queue = [ck] * 4
        match.players[1].elixir = 10000
        match.players[-1].elixir = 10000

        placements = ref["placements"]
        hog_cell = placements["hog"]["anchor_cell"]
        cannon_cell = placements["cannon"]["anchor_cell"]
        rel_cannon = float(ref["events_relative_to_hog_play_s"]["cannon_play"])

        def play_hog():
            assert match.play_card(1, hk, arena.tile(*hog_cell)), "Hasty rejected Hog"
            candidates = [
                e for e in match.battle.entities.values()
                if e.side == 1 and norm(e.name) == norm(cards[hk].unit.name)
            ]
            return max(candidates, key=lambda e: e.uid).uid

        def play_cannon():
            assert match.play_card(-1, ck, arena.tile(*cannon_cell)), "Hasty rejected Cannon"
            candidates = [
                e for e in match.battle.entities.values()
                if e.side == -1 and norm(e.name) == norm(cards[ck].unit.name)
            ]
            return max(candidates, key=lambda e: e.uid).uid

        if rel_cannon < 0:
            cannon_uid = play_cannon()
            for _ in range(int(round((-rel_cannon) / 0.05))):
                match.step()
            t0_ms = match.elapsed_ms
            hog_uid = play_hog()
        else:
            t0_ms = match.elapsed_ms
            hog_uid = play_hog()
            for _ in range(int(round(rel_cannon / 0.05))):
                match.step()
            cannon_uid = play_cannon()

        context_injected = False
        if ref["id"].endswith("PRIMARY"):
            # Rudy positions use origin at arena centre, +y upward.
            # Hasty uses top-left origin, +y downward.
            try:
                wanted = {"ice-golem": "ice_golem", "hunter": "hunter"}
                for c in ref.get("context_entities", []):
                    wk = key_like(cards, wanted[c["card"]])
                    x_r, y_r = c["position_rudy"]
                    pos = arena.Point(9000 + int(x_r), 16000 - int(y_r))
                    ent = match.battle.add(make_unit(0, cards[wk].unit, 1, pos, match.elapsed_ms))
                    ent.deploy_remaining_ms = 0
                    ent.hitpoints = max(1, round(ent.max_hitpoints * float(c["hp_percent"]) / 100.0))
                    if c.get("passive"):
                        ent.damage = 0
                        ent.death_damage = 0
                        ent.death_area_damage = 0
                context_injected = True
            except Exception as exc:
                context_injected = False
                context_error = repr(exc)
        else:
            context_error = None

        damage_cursor = 0
        hits = []
        cannon_lethal = None
        cannon_death = None
        hog_death = None
        cannon_seen = True
        hog_seen = True
        max_steps = 260
        for _ in range(max_steps):
            match.step()
            rel_s = round((match.elapsed_ms - t0_ms) / 1000.0, 3)

            for row in match.battle.damage_log[damage_cursor:]:
                if len(row) >= 4:
                    tm, src, tgt, amount = row[:4]
                    if int(src) == int(hog_uid) and int(tgt) == int(cannon_uid) and int(amount) > 0:
                        ht = round((int(tm) - t0_ms) / 1000.0, 3)
                        if not hits or abs(hits[-1] - ht) > 1e-9:
                            hits.append(ht)
            damage_cursor = len(match.battle.damage_log)

            cannon = match.battle.entities.get(cannon_uid)
            hog = match.battle.entities.get(hog_uid)
            if cannon_lethal is None and cannon is not None and cannon.hitpoints <= 0:
                cannon_lethal = rel_s
            if cannon_death is None and cannon_seen and (cannon is None or cannon.hitpoints <= 0):
                cannon_death = rel_s
            if hog_death is None and hog_seen and (hog is None or hog.hitpoints <= 0):
                hog_death = rel_s
            if cannon_death is not None and hog_death is not None:
                break

        if cannon_lethal is None and cannon_death is not None:
            cannon_lethal = cannon_death

        obs = {
            "hog_hits_cannon": hits,
            "cannon_lethal_hit": cannon_lethal,
            "cannon_death": cannon_death,
            "hog_death": hog_death,
            "context_injected": context_injected,
            "context_error": context_error,
        }
        row = score(ref, obs)
        row["observed"] = obs
        row["strict"] = not ref["id"].endswith("PRIMARY") or context_injected
        results.append(row)

    unit_meta = {}
    for label, key in [("hog", hk), ("cannon", ck)]:
        u = cards[key].unit
        unit_meta[label] = {
            "key": key, "hp": u.hitpoints, "damage": u.damage,
            "hit_speed_ms": u.hit_speed_ms, "load_time_ms": u.load_time_ms,
            "range_mt": u.range_mt, "sight_range_mt": u.sight_range_mt,
            "speed_raw": u.speed_mt_per_sec, "collision_radius_mt": u.collision_radius_mt,
            "mass": u.mass, "deploy_time_ms": u.deploy_time_ms,
        }
    return {
        "engine": "Hasty-CR",
        "mode": mode,
        "commit": "913608b4dc7772008402493b27dc29020fe51718",
        "data_source": "smlbiobot/cr-csv historical public snapshot + Hasty bundled public tower tables",
        "unit_meta": unit_meta,
        "results": results,
    }


def run_crforge() -> dict:
    repo = ROOT / "third_party/crforge"
    sys.path.insert(0, str(repo / "python"))
    from crforge_gym.jpype_bridge import InProcessBridge

    refs = load_refs()
    bridge = InProcessBridge()
    bridge.connect()

    results = []
    tick_dt_samples = []
    for ref in refs:
        # duplicate cards make slot 0 deterministic regardless of deck shuffle
        bridge.init(["hogrider"] * 8, ["cannon"] * 8, level=11, ticks_per_step=1, seed=1)
        sess = bridge._session
        obs0 = sess.observe()
        t_prev = float(obs0.gameTimeSeconds())

        def step(blue=None, red=None):
            nonlocal t_prev
            ja = None if blue is None else bridge._StepAction(int(blue[0]), float(blue[1]), float(blue[2]))
            ra = None if red is None else bridge._StepAction(int(red[0]), float(red[1]), float(red[2]))
            res = sess.step(ja, ra)
            ob = res.observation()
            t = float(ob.gameTimeSeconds())
            if t > t_prev:
                tick_dt_samples.append(t - t_prev)
            t_prev = t
            return ob

        def cf_point(cell):
            # reference coordinates are top-left/y-down tile cells; CRForge is y-up.
            return (float(cell[0]) + 0.5, 31.5 - float(cell[1]))

        hxy = cf_point(ref["placements"]["hog"]["anchor_cell"])
        cxy = cf_point(ref["placements"]["cannon"]["anchor_cell"])
        delay = float(ref["events_relative_to_hog_play_s"]["cannon_play"])

        if delay < 0:
            action_time = float(sess.observe().gameTimeSeconds())
            step(red=(0, *cxy))
            while float(sess.observe().gameTimeSeconds()) + 1e-6 < action_time - delay:
                step()
            t0 = float(sess.observe().gameTimeSeconds())
            step(blue=(0, *hxy))
        else:
            t0 = float(sess.observe().gameTimeSeconds())
            step(blue=(0, *hxy))
            target_t = t0 + delay
            while float(sess.observe().gameTimeSeconds()) + 1e-6 < target_t:
                step()
            step(red=(0, *cxy))

        def entities(ob):
            return list(ob.entities())

        def is_hog(e):
            return norm(str(e.name())) in {"hogrider", "hog"}

        def is_cannon(e):
            return norm(str(e.name())) == "cannon"

        hog_id = None
        cannon_id = None
        last_cannon_hp = None
        hits = []
        cannon_death = None
        hog_death = None
        hog_seen = False
        cannon_seen = False

        for _ in range(500):
            ob = step()
            t = float(ob.gameTimeSeconds()) - t0
            es = entities(ob)
            hogs = [e for e in es if str(e.team()).upper() == "BLUE" and is_hog(e)]
            cannons = [e for e in es if str(e.team()).upper() == "RED" and is_cannon(e)]
            if hog_id is None and hogs:
                hog_id = int(hogs[0].id())
            if cannon_id is None and cannons:
                cannon_id = int(cannons[0].id())
            hog = next((e for e in hogs if hog_id is None or int(e.id()) == hog_id), None)
            cannon = next((e for e in cannons if cannon_id is None or int(e.id()) == cannon_id), None)
            if hog is not None:
                hog_seen = True
            if cannon is not None:
                cannon_seen = True
                hp = int(cannon.hp())
                if last_cannon_hp is not None:
                    drop = last_cannon_hp - hp
                    # Lifetime decay may be gradual; Hog hits are large discrete drops.
                    if drop >= 100:
                        hits.append(round(t, 3))
                last_cannon_hp = hp

            if cannon_death is None and cannon_seen and (cannon is None or int(cannon.hp()) <= 0):
                cannon_death = round(t, 3)
            if hog_death is None and hog_seen and (hog is None or int(hog.hp()) <= 0):
                hog_death = round(t, 3)
            if cannon_death is not None and hog_death is not None:
                break

        obs_out = {
            "hog_hits_cannon": hits,
            "cannon_lethal_hit": hits[-1] if hits and cannon_death is not None else None,
            "cannon_death": cannon_death,
            "hog_death": hog_death,
            "context_injected": False,
        }
        row = score(ref, obs_out)
        row["observed"] = obs_out
        # PRIMARY needs pre-existing Ice Golem+Hunter state; this bridge does not expose injection.
        row["strict"] = not ref["id"].endswith("PRIMARY")
        if ref["id"].endswith("PRIMARY"):
            row["note"] = "PRIMARY not strict: GameSession bridge cannot seed already-live Ice Golem/Hunter context."
        results.append(row)

    bridge.close()
    dt = sum(tick_dt_samples) / len(tick_dt_samples) if tick_dt_samples else None
    return {
        "engine": "CRForge",
        "commit": "b41cf9b6276945152ec4c869ce56f98a5fa3f513",
        "data_source": "CRForge bundled community card JSON",
        "measured_tick_s": dt,
        "results": results,
    }


def print_summary(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\n=== EXTERNAL ENGINE BENCHMARK SUMMARY ===")
    print(f"engine={payload['engine']} mode={payload.get('mode','raw')}")
    for row in payload["results"]:
        mark = "PASS" if row["pass"] else "FAIL"
        strict = "strict" if row.get("strict") else "informational"
        print(f"{row['reference_id']}: {mark} ({strict}) max_err={row['max_abs_error_s']}")
        for m in row["metrics"]:
            print(
                f"  {m['metric']:<22} real={m['real_s']} sim={m['sim_s']} "
                f"err={m['error_s']} pass={m['pass']}"
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["hasty", "crforge"], required=True)
    ap.add_argument("--mode", choices=["raw", "normalized"], default="raw")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    payload = run_hasty(args.mode) if args.engine == "hasty" else run_crforge()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(payload)


if __name__ == "__main__":
    main()
