#!/usr/bin/env python3
"""Model Clash Royale building HP loss over lifetime.

CR buildings visibly lose HP continuously and published card tables expose
`Hitpoints lost/sec` (for Cannon Lv11 roughly max_hp / 30 s). Pinned Rudy only
counted lifetime_remaining and kept HP flat until sudden expiry.

Use an integer remainder accumulator so total passive HP loss over `lifetime`
ticks is exactly max_hp, without float drift. Damage from attacks stacks on top
of this passive decay.
"""
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2]
    / "third_party" / "clash-royale-suite" / "cr-rudy-sim"
    / "simulator" / "engine" / "src"
)
ENT = ROOT / "entities.rs"
ENG = ROOT / "engine.rs"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")

replace_once(
    ENT,
    """    /// Ticks remaining before building expires.
    pub lifetime_remaining: i32,
    /// Attack fields (some buildings attack, e.g., Tesla, Inferno Tower).""",
    """    /// Ticks remaining before building expires.
    pub lifetime_remaining: i32,
    /// Fractional accumulator for passive lifetime HP decay. Each tick adds
    /// max_hp; division by lifetime yields the integer HP to remove this tick.
    pub lifetime_hp_decay_accum: i64,
    /// Attack fields (some buildings attack, e.g., Tesla, Inferno Tower).""",
    "building decay accumulator field",
)

replace_once(
    ENT,
    """                lifetime: lifetime_ticks,
                lifetime_remaining: lifetime_ticks,
                hit_speed: ms_to_ticks(stats.hit_speed),""",
    """                lifetime: lifetime_ticks,
                lifetime_remaining: lifetime_ticks,
                lifetime_hp_decay_accum: 0,
                hit_speed: ms_to_ticks(stats.hit_speed),""",
    "building decay accumulator init",
)

replace_once(
    ENG,
    """        if let EntityKind::Building(ref mut bld) = entity.kind {
            // Decay lifetime
            bld.lifetime_remaining -= 1;
            if bld.lifetime_remaining <= 0 {
                entity.alive = false;
                // Set hp to 0 so tick_deaths recognizes this as a fresh death
                // and fires death_damage (GiantSkeletonBomb, BalloonBomb, etc.).
                entity.hp = 0;
                continue;
            }""",
    """        if let EntityKind::Building(ref mut bld) = entity.kind {
            // Buildings lose HP continuously throughout their lifetime in real CR.
            // Accumulate max_hp/lifetime in fixed-point remainder form so the
            // total passive loss equals exactly max_hp by natural expiry.
            if bld.lifetime > 0 {
                bld.lifetime_hp_decay_accum += entity.max_hp.max(0) as i64;
                let passive_loss = bld.lifetime_hp_decay_accum / bld.lifetime as i64;
                bld.lifetime_hp_decay_accum %= bld.lifetime as i64;
                if passive_loss > 0 {
                    entity.hp = (entity.hp - passive_loss as i32).max(0);
                    if entity.hp <= 0 {
                        entity.alive = false;
                    }
                }
            }

            // Decay lifetime
            bld.lifetime_remaining -= 1;
            if bld.lifetime_remaining <= 0 || !entity.alive {
                entity.alive = false;
                // Set hp to 0 so tick_deaths recognizes this as a fresh death
                // and fires death_damage (GiantSkeletonBomb, BalloonBomb, etc.).
                entity.hp = 0;
                continue;
            }""",
    "continuous building HP decay",
)

print("Rudy patched: continuous building HP decay across lifetime")
