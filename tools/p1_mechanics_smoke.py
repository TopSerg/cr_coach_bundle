#!/usr/bin/env python3
"""P1 synthetic mechanics gates against the actual patched cr_engine wheel.

No physical video truth is implied: results here are SYNTHETIC only.
"""
from __future__ import annotations

import json
from pathlib import Path

import cr_engine  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "rudy_tournament11_data"
DECK = ["hog-rider", "cannon", "knight", "archers",
        "fireball", "giant", "valkyrie", "musketeer"]


def new_match():
    return cr_engine.new_match(cr_engine.load_data(str(DATA)), DECK, DECK)


def step(match):
    value = dict(match.step_trace())
    value["entities"] = [dict(row) for row in value["entities"]]
    value["events"] = [dict(row) for row in value["events"]]
    return value


def row(frame, uid):
    return next((e for e in frame["entities"] if e["uid"] == uid), None)


def all_frames(match, count):
    return [step(match) for _ in range(count)]


def events(frames, uid=None):
    return [
        e for frame in frames for e in frame["events"]
        if uid is None or e.get("uid") == uid
    ]


def assert_air_and_building_only():
    """M03/M05: air crosses open river and Balloon ignores troop targets."""
    match = new_match()
    balloon = match.spawn_troop(1, "balloon", 0, -2200, 11, False)
    troop = match.spawn_troop(2, "knight", 300, 1500, 11, False)
    cannon = match.spawn_building(2, "cannon", 0, 5000, 11)
    frames = all_frames(match, 70)
    positions = [row(f, balloon) for f in frames]
    positions = [p for p in positions if p]
    assert positions and positions[-1]["y"] > positions[0]["y"], "Balloon must advance"
    assert max(abs(p["x"]) for p in positions) < 1250, "Air route must not divert to bridge"
    acquired = [e for e in events(frames, balloon) if e["type"] == "TARGET_ACQUIRED"]
    assert acquired, "Balloon must acquire building"
    assert acquired[0].get("target_uid") == cannon, "Balloon must prefer Cannon to nearby Knight"
    assert all(p["target_uid"] != troop for p in positions), "Building-only target violated"
    return {"M03": "synthetic_pass", "M05": "synthetic_pass"}


def assert_jump_and_planes():
    """M11/M12: phase transitions are Rust-owned; airborne counts as air target."""
    match = new_match()
    hog = match.spawn_troop(1, "hog-rider", 0, -1450, 11, False)
    match.spawn_building(2, "cannon", 0, 5500, 11)
    knight = match.spawn_troop(2, "knight", 450, 1400, 11, False)
    musketeer = match.spawn_troop(2, "musketeer", -450, 1400, 11, False)
    frames = all_frames(match, 95)
    states = [(f["tick"], row(f, hog)) for f in frames]
    states = [(t, p) for t, p in states if p]
    types = [(e["type"], e) for e in events(frames, hog)]
    starts = [e for t, e in types if t == "JUMP_STARTED"]
    lands = [e for t, e in types if t == "JUMP_LANDED"]
    assert len(starts) == len(lands) == 1, f"Jump must start and land once: {types}"
    assert starts[0]["tick"] < lands[0]["tick"], "Jump ordering"
    assert -1000 < starts[0]["y"] < 1000, "Jump must start over open river"
    assert abs(starts[0]["x"]) < 4000, "This test must cross over open water"
    assert any(p.get("jump_state") == "airborne" for _, p in states), "Missing persistent airborne phase"
    assert any(p.get("jump_state") == "landing" for _, p in states), "Missing landing phase"
    assert any(p.get("jump_start_tick") == starts[0]["tick"] for _, p in states)
    assert any(p.get("jump_land_tick") == lands[0]["tick"] for _, p in states)
    # Targeting is evaluated before movement, so check a frame AFTER airborne starts.
    mid = [f for f in frames if starts[0]["tick"] < f["tick"] < lands[0]["tick"]]
    if len(mid) > 1:
        actual = [(row(f, knight), row(f, musketeer)) for f in mid]
        assert all(k is None or k["target_uid"] != hog for k, _ in actual), (
            "Ground-only Knight cannot lock an airborne Hog"
        )
        assert any(m is not None and m["target_uid"] == hog for _, m in actual), (
            "Air-capable Musketeer should be able to target airborne Hog"
        )
    return {"M11": "synthetic_pass", "M12": "synthetic_pass"}


def assert_melee_and_projectiles():
    """M14-M16: independent release, impact, damage ticks when scenario permits."""
    match = new_match()
    hog = match.spawn_troop(1, "hog-rider", 5500, -2500, 11, False)
    cannon = match.spawn_building(2, "cannon", 5500, 1800, 11)
    frames = all_frames(match, 150)
    hog_events = events(frames, hog)
    started = [e for e in hog_events if e["type"] == "ATTACK_WINDUP_STARTED"]
    hits = [e for e in hog_events if e["type"] == "MELEE_HIT"]
    assert started and hits, "Hog must wind up and make at least one melee hit"
    assert started[0]["tick"] <= hits[0]["tick"], "Melee damage precedes windup"
    cannon_damage = [e for e in events(frames, cannon) if e["type"] == "DAMAGE"]
    assert cannon_damage, "Cannon must receive melee damage"
    assert cannon_damage[0]["tick"] >= started[0]["tick"]
    for e in hits:
        assert e.get("target_uid") is not None, "Melee needs target UID"

    match = new_match()
    shooter = match.spawn_troop(1, "musketeer", 0, -4000, 11, False)
    victim = match.spawn_troop(2, "giant", 0, -1000, 11, False)
    frames = all_frames(match, 115)
    shooter_ev = events(frames, shooter)
    fired = [e for f in frames for e in f["events"] if e["type"] == "PROJECTILE_SPAWN"
             and row(f, shooter) is not None
             and e.get("uid") in row(f, shooter)["active_projectiles"]]
    hits = [e for e in events(frames) if e["type"] == "PROJECTILE_HIT"
            and e.get("source_uid") == shooter]
    damages = [e for e in events(frames, victim) if e["type"] == "DAMAGE"
               and e.get("source_uid") == shooter]
    assert any(e["type"] == "ATTACK_WINDUP_STARTED" for e in shooter_ev)
    assert fired and hits and damages, "Musketeer projectile lifecycle must complete"
    assert min(e["tick"] for e in fired) <= min(e["tick"] for e in hits), "Projectile impact before launch"
    assert min(e["tick"] for e in hits) <= min(e["tick"] for e in damages), "Damage ordering"
    return {"M14": "synthetic_pass", "M15": "synthetic_pass", "M16": "synthetic_pass"}


def assert_stun():
    """M21: tracked stun starts and expires; existing combat hook handles resets."""
    deck = ["zap", "hog-rider", "cannon", "knight",
            "archers", "giant", "valkyrie", "musketeer"]
    data = cr_engine.load_data(str(DATA))
    match = cr_engine.new_match(data, deck, deck)
    match.set_elixir(1, 10)
    victim = match.spawn_troop(2, "knight", 0, 0, 11, False)
    match.play_card(1, 0, 0, 0, 11)
    frames = all_frames(match, 55)
    types = [e["type"] for e in events(frames, victim)]
    assert "STUN_APPLIED" in types, "Zap must stun Knight"
    assert "STUN_EXPIRED" in types, "Stun must expire"
    assert types.index("STUN_APPLIED") < types.index("STUN_EXPIRED")
    return {"M21": "synthetic_pass"}



def assert_stun_retarget():
    """M22: stun breaks sticky lock; shared targeting reacquires after expiry."""
    deck = ["zap", "hog-rider", "cannon", "knight",
            "archers", "giant", "valkyrie", "musketeer"]
    data = cr_engine.load_data(str(DATA))
    match = cr_engine.new_match(data, deck, deck)
    match.set_elixir(2, 10)
    musket = match.spawn_troop(1, "musketeer", 0, -4500, 11, False)
    giant = match.spawn_troop(2, "giant", 0, -1600, 11, False)
    warmup = all_frames(match, 27)
    assert any(row(f, musket) and row(f, musket)["target_uid"] == giant for f in warmup), (
        "Musketeer must acquire Giant before stun"
    )
    knight = match.spawn_troop(2, "knight", 0, -3000, 11, False)
    before = step(match)
    assert row(before, musket)["target_uid"] == giant, "Pre-stun sticky lock must hold"
    match.play_card(2, 0, 0, -4500, 11)
    after = all_frames(match, 35)
    observed = events(after, musket)
    stuns = [e for e in observed if e["type"] == "STUN_APPLIED"]
    drops = [e for e in observed if e["type"] == "TARGET_DROPPED"]
    expiry = [e for e in observed if e["type"] == "STUN_EXPIRED"]
    acquired = [e for e in observed if e["type"] == "TARGET_ACQUIRED"]
    assert stuns and drops and expiry and acquired, f"Missing stun/retarget lifecycle: {observed}"
    assert drops[0]["tick"] >= stuns[0]["tick"], "Dropped before stunned"
    assert acquired[-1]["tick"] >= expiry[-1]["tick"], "Reacquired while still stunned"
    assert acquired[-1].get("target_uid") in {knight, giant}, "Invalid post-stun target"
    return {"M22": "synthetic_pass"}


def assert_special_reset():
    """M23: data-driven Inferno ramp resets on stun, without card-name branches."""
    deck = ["zap", "hog-rider", "cannon", "knight",
            "archers", "giant", "valkyrie", "musketeer"]
    data = cr_engine.load_data(str(DATA))
    match = cr_engine.new_match(data, deck, deck)
    match.set_elixir(2, 10)
    inferno = match.spawn_building(1, "inferno-tower", 0, -1500, 11)
    match.spawn_troop(2, "giant", 0, 1000, 11, False)
    before = all_frames(match, 65)
    ramp = [row(f, inferno)["ramp_ticks"] for f in before if row(f, inferno)]
    assert any(x > 0 for x in ramp), "Inferno must establish ramp before Zap"
    match.play_card(2, 0, 0, -1500, 11)
    after = all_frames(match, 12)
    stun = [e for e in events(after, inferno) if e["type"] == "STUN_APPLIED"]
    assert stun, "Inferno must receive Zap stun"
    resets = [row(f, inferno) for f in after if row(f, inferno)
              and f["tick"] >= stun[0]["tick"]]
    assert resets and resets[0]["ramp_ticks"] == 0, "Stun must clear ramp ticks"
    assert resets[0]["ramp_target_uid"] is None, "Stun must clear Inferno ramp lock"
    return {"M23": "synthetic_pass"}


def main():
    results = {}
    for run in (assert_air_and_building_only, assert_jump_and_planes,
                assert_melee_and_projectiles, assert_stun,
                assert_stun_retarget, assert_special_reset):
        results.update(run())
    for gate in ("M17", "M18"):
        results[gate] = "pending_controlled_synthetic_and_physical_reference"
    print(json.dumps({"p1": results, "physical_verified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
