#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"
lib = ROOT / "lib.rs"

text = lib.read_text(encoding="utf-8")
old = '''            dict.set_item(
                "kind",
                match &e.kind {
                    EntityKind::Troop(_) => "troop",
                    EntityKind::Building(_) => "building",
                    EntityKind::Projectile(_) => "projectile",
                    EntityKind::SpellZone(_) => "spell_zone",
                },
            )?;
            // Phase 3: Buff/evo/hero state
'''
new = '''            dict.set_item(
                "kind",
                match &e.kind {
                    EntityKind::Troop(_) => "troop",
                    EntityKind::Building(_) => "building",
                    EntityKind::Projectile(_) => "projectile",
                    EntityKind::SpellZone(_) => "spell_zone",
                },
            )?;
            dict.set_item("target_id", e.target.map(|id| id.0))?;
            match &e.kind {
                EntityKind::Building(b) => {
                    dict.set_item("attack_cooldown", b.attack_cooldown)?;
                    dict.set_item("hit_speed", b.hit_speed)?;
                    dict.set_item("range_sq", b.range_sq)?;
                    dict.set_item("is_ranged", b.is_ranged)?;
                    dict.set_item("projectile_key", b.projectile_key.as_deref())?;
                    dict.set_item("lifetime_remaining", b.lifetime_remaining)?;
                }
                EntityKind::Projectile(p) => {
                    dict.set_item("projectile_speed", p.speed)?;
                    dict.set_item("projectile_target_id", p.target_id.0)?;
                    dict.set_item("projectile_target_x", p.target_x)?;
                    dict.set_item("projectile_target_y", p.target_y)?;
                    dict.set_item("projectile_impact_damage", p.impact_damage)?;
                    dict.set_item("projectile_source_id", p.source_id.0)?;
                    dict.set_item("projectile_homing", p.homing)?;
                }
                _ => {}
            }
            // Phase 3: Buff/evo/hero state
'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"debug snapshot insertion: expected 1 get_entities block, found {count}")
lib.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Rudy patched: expose building cooldown/ranged state and projectile flight fields to Python diagnostics.")
