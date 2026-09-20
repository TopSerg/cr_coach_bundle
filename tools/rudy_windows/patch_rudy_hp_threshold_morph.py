#!/usr/bin/env python3
"""Add a generic HP-threshold morph trigger to Rudy.

Current Clash Royale data uses this for Goblin Demolisher: below 50% HP it
transforms into a faster building-targeting kamikaze form. Rudy already has a
morph pipeline, but its trigger is shield-break only. This patch makes the
trigger data-driven instead of hardcoding the card name.
"""
from pathlib import Path

ROOT=(
    Path(__file__).resolve().parents[2]
    / "third_party" / "clash-royale-suite" / "cr-rudy-sim"
    / "simulator" / "engine" / "src"
)

def replace_once(path: Path, old: str, new: str) -> None:
    text=path.read_text(encoding="utf-8")
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f"{path}: expected one target block, found {count}")
    path.write_text(text.replace(old,new,1),encoding="utf-8")

data=ROOT/"data_types.rs"
replace_once(
    data,
'''    #[serde(default, deserialize_with = "null_or_i32")]
    pub morph_after_hits_count: i32,
    /// Time in ms for the morph transition. During this period the entity
''',
'''    #[serde(default, deserialize_with = "null_or_i32")]
    pub morph_after_hits_count: i32,
    /// HP percentage threshold for morphing. 0 = disabled.
    /// Goblin Demolisher uses 50: once current HP is <= 50% of max HP,
    /// it transforms into its kamikaze form.
    #[serde(default, deserialize_with = "null_or_i32")]
    pub morph_at_hp_percent: i32,
    /// Time in ms for the morph transition. During this period the entity
'''
)

entities=ROOT/"entities.rs"
replace_once(
    entities,
'''    pub morph_character: Option<String>,
    /// If true, heal to full HP on morph.
''',
'''    pub morph_character: Option<String>,
    /// HP percentage threshold for this morph. 0 = disabled.
    pub morph_at_hp_percent: i32,
    /// If true, heal to full HP on morph.
'''
)
replace_once(
    entities,
'''                morph_character: stats.morph_character.clone(),
                morph_heal: stats.heal_on_morph,
''',
'''                morph_character: stats.morph_character.clone(),
                morph_at_hp_percent: stats.morph_at_hp_percent,
                morph_heal: stats.heal_on_morph,
'''
)

combat=ROOT/"combat.rs"
replace_once(
    combat,
'''                let shield_broken = originally_had_shield && entity.shield_hp <= 0;

                if shield_broken {
''',
'''                let shield_broken = originally_had_shield && entity.shield_hp <= 0;
                let hp_threshold_reached = t.morph_at_hp_percent > 0
                    && entity.max_hp > 0
                    && (entity.hp as i64) * 100
                        <= (entity.max_hp as i64) * (t.morph_at_hp_percent as i64);

                if shield_broken || hp_threshold_reached {
'''
)

print("Rudy patched: morphs can trigger at a data-driven HP percentage.")
