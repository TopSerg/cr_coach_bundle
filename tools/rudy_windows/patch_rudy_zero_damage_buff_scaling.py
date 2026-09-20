#!/usr/bin/env python3
"""Keep buff/DOT spell scaling neutral when the spell has no direct damage.

Rudy derives buff DOT/heal level scaling from SpellStats.damage_per_level.
Utility spells such as Goblin Curse can legitimately have zero direct damage
while their buff carries all DOT. A populated all-zero damage array therefore
must mean a neutral 1:1 scaling ratio, not 0:1 (which silently erases the DOT).
"""
from pathlib import Path


ROOT = (
    Path(__file__).resolve().parents[2]
    / "third_party"
    / "clash-royale-suite"
    / "cr-rudy-sim"
    / "simulator"
    / "engine"
    / "src"
)
LIB = ROOT / "lib.rs"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one level-scaling block in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


old = '''                    let level_scale_num: i64 = if !spell_stats.damage_per_level.is_empty() && level > 0 {
                        let idx = (level - 1).min(spell_stats.damage_per_level.len() - 1);
                        spell_stats.damage_per_level[idx] as i64
                    } else {
                        1
                    };
                    let level_scale_den: i64 = if !spell_stats.damage_per_level.is_empty() {
                        spell_stats.damage_per_level[0].max(1) as i64
                    } else {
                        1
                    };
'''

new = '''                    let level_scale_num: i64 = if !spell_stats.damage_per_level.is_empty() && level > 0 {
                        let idx = (level - 1).min(spell_stats.damage_per_level.len() - 1);
                        let level_damage = spell_stats.damage_per_level[idx] as i64;
                        let base_damage = spell_stats.damage_per_level[0] as i64;
                        // Utility spells can carry their effect entirely in BuffStats
                        // (Goblin Curse DOT/slow, for example) and therefore have zero
                        // direct spell damage at every level. Treat that as neutral
                        // scaling instead of multiplying the buff DOT by zero.
                        if level_damage > 0 && base_damage > 0 {
                            level_damage
                        } else {
                            1
                        }
                    } else {
                        1
                    };
                    let level_scale_den: i64 = if !spell_stats.damage_per_level.is_empty()
                        && spell_stats.damage_per_level[0] > 0
                    {
                        spell_stats.damage_per_level[0] as i64
                    } else {
                        1
                    };
'''

replace_once(LIB, old, new)
print("Rudy patched: zero-direct-damage buff spells keep neutral DOT/heal scaling.")
