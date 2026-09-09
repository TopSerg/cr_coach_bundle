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
text = text.replace(old, new, 1)

marker = '''    /// Spawn a troop for a player at (x, y). Player: 1 or 2.
'''
seed_method = '''    /// Seed an already-deployed NORMAL troop at an observed world position.
    /// Diagnostic/snapshot helper for video regressions: no elixir, no card cycle,
    /// no deploy animation, no automatic hero/evolution semantics.
    #[pyo3(signature = (player, card_key, x, y, level=11, hp_percent=100))]
    fn seed_troop_state(
        &mut self,
        player: i32,
        card_key: &str,
        x: i32,
        y: i32,
        level: usize,
        hp_percent: i32,
    ) -> PyResult<u32> {
        let team = match player {
            1 => Team::Player1,
            2 => Team::Player2,
            _ => return Err(pyo3::exceptions::PyValueError::new_err("player must be 1 or 2")),
        };
        let stats = self.data.characters.get(card_key).ok_or_else(|| {
            pyo3::exceptions::PyKeyError::new_err(format!("Unknown character: {}", card_key))
        })?;
        let id = self.state.alloc_id();
        let mut entity = Entity::new_troop(id, team, stats, x, y, level, false);
        if entity.card_key.is_empty() {
            entity.card_key = card_key.to_string();
        }
        entity.deploy_timer = 0;
        let pct = hp_percent.clamp(1, 100) as i64;
        entity.hp = ((entity.max_hp as i64 * pct + 99) / 100) as i32;
        self.state.entities.push(entity);
        Ok(id.0)
    }

'''
count = text.count(marker)
if count != 1:
    raise RuntimeError(f"seed_troop_state insertion: expected 1 spawn_troop marker, found {count}")
text = text.replace(marker, seed_method + marker, 1)

lib.write_text(text, encoding="utf-8")
print("Rudy patched: expose combat snapshots + seed_troop_state() for observed video context.")
