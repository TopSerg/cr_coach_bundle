#!/usr/bin/env python3
"""M17/M18 controlled synthetic projectiles against the real patched Rust engine.

Uses explicit between-tick test operations; production targeting, projectile
movement, splash and cleanup still execute via Match.step_trace().
"""
from __future__ import annotations

import json
from pathlib import Path
import cr_engine  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "rudy_tournament11_data"
DECK = ["musketeer", "wizard", "princess", "knight", "giant",
        "hog-rider", "cannon", "fireball"]


def match_new():
    data = cr_engine.load_data(str(DATA))
    return cr_engine.new_match(data, DECK, DECK)


def tick(m):
    t = dict(m.step_trace())
    t["entities"] = [dict(x) for x in t["entities"]]
    t["events"] = [dict(x) for x in t["events"]]
    return t


def entity(frame, uid):
    return next((x for x in frame["entities"] if x["uid"] == uid), None)


def projectiles(frame, source):
    return [
        x for x in frame["entities"]
        if x["kind"] == "projectile" and x.get("projectile_source_uid") == source
    ]


def await_projectile(m, source, steps=160):
    for _ in range(steps):
        frame = tick(m)
        shots = projectiles(frame, source)
        if shots:
            shot = shots[0]
            return frame, shot
    raise AssertionError(f"no in-flight projectile from source UID {source}")


def assert_homing_direct_hit():
    """M17: an in-flight Musketeer shot tracks target UID after displacement."""
    m = match_new()
    src = m.spawn_troop(1, "musketeer", 0, -4600, 11, False)
    target = m.spawn_troop(2, "giant", 0, 1100, 11, False)
    before, shot = await_projectile(m, src)
    uid = shot["uid"]
    assert shot["projectile_guidance"] == "target_uid", shot
    assert shot["projectile_target_uid"] == target, shot
    initial_destination = (shot["projectile_destination_x"], shot["projectile_destination_y"])
    victim = entity(before, target)
    assert victim is not None
    original_hp = victim["hp"]
    assert m.debug_relocate_entity(target, victim["x"] + 2500, victim["y"]), (
        "test-only displacement API unavailable"
    )
    paths = []
    hit_events = []
    last = None
    for _ in range(65):
        frame = tick(m)
        p = entity(frame, uid)
        if p:
            paths.append((p["projectile_destination_x"], p["projectile_destination_y"]))
            assert p["projectile_source_uid"] == src
            assert p["projectile_target_uid"] == target
        hit_events.extend(e for e in frame["events"]
                          if e["type"] == "PROJECTILE_HIT" and e["uid"] == uid)
        last = frame
        if hit_events:
            break
    assert paths, "Projectile vanished before re-targeting after displacement"
    assert any(abs(x - initial_destination[0]) > 1000 for x, _ in paths), (
        "M17: direct-hit projectile remained at old fixed coordinate"
    )
    assert hit_events, "Displaced Giant was never hit by its own guided projectile"
    assert entity(last, target)["hp"] < original_hp, "Guided projectile hit event without damage"
    return {"M17_homing": "synthetic_pass"}


def assert_fixed_splash(shooter_card="wizard"):
    """M17: splash center stays at launch point even if target moves away."""
    m = match_new()
    src = m.spawn_troop(1, shooter_card, 0, -4600, 11, False)
    first = m.spawn_troop(2, "giant", 0, 100, 11, False)
    second = m.spawn_troop(2, "knight", 200, 150, 11, False)
    frame, shot = await_projectile(m, src)
    uid = shot["uid"]
    assert shot["projectile_splash_radius"] > 0, shot
    assert shot["projectile_guidance"] == "fixed_point", shot
    start = (shot["projectile_destination_x"], shot["projectile_destination_y"])
    target = shot["projectile_target_uid"]
    assert target in (first, second), "Unexpected splash primary target UID"
    assert m.debug_relocate_entity(target, 3400, 100), "Cannot displace splash target"
    before_other = entity(frame, second if target == first else first)
    assert before_other
    other = second if target == first else first
    # Stop the other ground troop from walking away, so this test isolates the
    # splash location, not the independent movement AI.
    assert m.debug_relocate_entity(other, start[0] + 250, start[1]), (
        "Cannot place synthetic stationary splash bystander"
    )
    seen_shot = False
    impact = None
    for _ in range(75):
        f = tick(m)
        p = entity(f, uid)
        if p:
            seen_shot = True
            assert p["projectile_guidance"] == "fixed_point"
            assert (p["projectile_destination_x"], p["projectile_destination_y"]) == start, (
                "M17: splash projectile tracked the displaced target instead of launch point"
            )
        else:
            impact = f
            break
    assert seen_shot and impact is not None, "Splash projectile did not complete its flight"
    # The surviving bystander must be damaged by splash around the original point,
    # rather than around the relocated primary target.
    after_other = entity(impact, other)
    assert after_other is None or after_other["hp"] < before_other["hp"] - 20, (
        "Fixed point splash did not hit the bystander at the original aim point"
    )
    return {f"M17_fixed_{shooter_card}": "synthetic_pass"}


def assert_persists_after_shooter_death():
    """M18: projectile remains until it impacts despite early shooter death."""
    m = match_new()
    shooter = m.spawn_troop(1, "musketeer", 0, -4600, 11, False)
    target = m.spawn_troop(2, "giant", 0, 1100, 11, False)
    before, projectile = await_projectile(m, shooter)
    uid = projectile["uid"]
    target_hp = entity(before, target)["hp"]
    assert m.debug_eliminate_entity(shooter), "Cannot eliminate shooter in synthetic M18"
    next_frame = tick(m)
    assert entity(next_frame, shooter) is None, "Dead shooter must be cleaned up"
    p = entity(next_frame, uid)
    assert p is not None, "Projectile was wrongly removed with its shooter"
    assert p["projectile_source_uid"] == shooter, "Projectile source UID must survive owner cleanup"

    impact_tick = None
    hit = []
    for _ in range(70):
        frame = tick(m)
        hit.extend(e for e in frame["events"]
                   if e["type"] == "PROJECTILE_HIT" and e["uid"] == uid)
        if hit:
            impact_tick = frame["tick"]
            assert entity(frame, uid) is None, "Projectile must clean up after impact"
            assert entity(frame, target)["hp"] < target_hp, "Target did not take impact damage"
            break
        assert entity(frame, uid) is not None, (
            "In-flight projectile disappeared before impacting the target"
        )
    assert impact_tick is not None, "Released projectile never reached target after shooter death"
    return {"M18": "synthetic_pass"}


def main():
    result = {}
    for probe in (assert_homing_direct_hit, assert_fixed_splash,
                  assert_persists_after_shooter_death):
        result.update(probe())
    print(json.dumps({"gates": result, "physical_verified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
