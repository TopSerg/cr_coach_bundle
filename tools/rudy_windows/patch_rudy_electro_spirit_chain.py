#!/usr/bin/env python3
"""Preserve projectile chain data when a kamikaze troop resolves.

Electro Spirit is modelled as a kamikaze troop in Rudy.  Its projectile record contains the chain count/radius, but the kamikaze event
previously kept only damage/radius/buff and silently discarded both chain
fields. The current-card data overlay owns the patch-sensitive values (9 targets
and a 3-tile chain radius as of the August 26, 2026 balance).  This patch performs nearest-target sequential bounces, damaging and
stunning each entity once and allowing Crown Towers to participate in the
chain.
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
combat = ROOT / "combat.rs"


def replace_once(old: str, new: str, label: str) -> None:
    text = combat.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    combat.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


replace_once(
'''        buff_key: Option<String>,
        buff_time: i32,
    }
''',
'''        buff_key: Option<String>,
        buff_time: i32,
        target_id: EntityId,
        chained_hit_radius: i32,
        chained_hit_count: i32,
    }
''',
    "kamikaze chain event fields",
)


replace_once(
'''                    let (kz_damage, kz_radius, kz_buff, kz_buff_time) = if let Some(ref proj_key) = troop.projectile_key {
''',
'''                    let (
                        kz_damage,
                        kz_radius,
                        kz_buff,
                        kz_buff_time,
                        kz_chain_radius,
                        kz_chain_count,
                    ) = if let Some(ref proj_key) = troop.projectile_key {
''',
    "resolve kamikaze chain payload",
)


replace_once(
'''                            (pdmg, pradius, pbuff, pbuff_time)
''',
'''                            (
                                pdmg,
                                pradius,
                                pbuff,
                                pbuff_time,
                                ps.chained_hit_radius,
                                ps.chained_hit_count,
                            )
''',
    "projectile chain stats into kamikaze payload",
)


replace_once(
'''                            (fallback_dmg, troop.kamikaze_damage_radius, troop.kamikaze_buff.clone(), troop.kamikaze_buff_time)
''',
'''                            (
                                fallback_dmg,
                                troop.kamikaze_damage_radius,
                                troop.kamikaze_buff.clone(),
                                troop.kamikaze_buff_time,
                                0,
                                0,
                            )
''',
    "missing projectile chain fallback",
)


replace_once(
'''                        (fallback_dmg, troop.kamikaze_damage_radius, troop.kamikaze_buff.clone(), troop.kamikaze_buff_time)
''',
'''                        (
                            fallback_dmg,
                            troop.kamikaze_damage_radius,
                            troop.kamikaze_buff.clone(),
                            troop.kamikaze_buff_time,
                            0,
                            0,
                        )
''',
    "no projectile chain fallback",
)


replace_once(
'''                        buff_key: kz_buff,
                        buff_time: kz_buff_time,
                    });
''',
'''                        buff_key: kz_buff,
                        buff_time: kz_buff_time,
                        target_id: target_snap.id,
                        chained_hit_radius: kz_chain_radius,
                        chained_hit_count: kz_chain_count,
                    });
''',
    "populate kamikaze chain event",
)


replace_once(
'''        }
    }

    // FIX: spawn_area_effect_object — create spell zone on kamikaze impact.
''',
'''        }

        // Sequential nearest-target chain (Electro Spirit). The primary target
        // was resolved by the normal kamikaze splash block above; each bounce
        // starts from the previous hit and may select a troop, building, or tower.
        if kz.chained_hit_count > 1 && kz.chained_hit_radius > 0 {
            let mut bounce_x = kz.impact_x;
            let mut bounce_y = kz.impact_y;
            let mut hit_ids: Vec<EntityId> = vec![kz.target_id];
            let chain_sq = (kz.chained_hit_radius as i64) * (kz.chained_hit_radius as i64);

            for _ in 0..(kz.chained_hit_count - 1) {
                let mut best_id: Option<EntityId> = None;
                let mut best_x = 0;
                let mut best_y = 0;
                let mut best_is_tower = false;
                let mut best_dist = i64::MAX;

                for entity in &state.entities {
                    if !entity.alive || entity.team == kz.team || hit_ids.contains(&entity.id) {
                        continue;
                    }
                    if matches!(entity.kind, EntityKind::SpellZone(_) | EntityKind::Projectile(_)) {
                        continue;
                    }
                    let dx = (entity.x - bounce_x) as i64;
                    let dy = (entity.y - bounce_y) as i64;
                    let dist = dx * dx + dy * dy;
                    if dist <= chain_sq && dist < best_dist {
                        best_id = Some(entity.id);
                        best_x = entity.x;
                        best_y = entity.y;
                        best_is_tower = false;
                        best_dist = dist;
                    }
                }

                for tower_id in enemy_tower_ids(kz.team) {
                    if hit_ids.contains(&tower_id) {
                        continue;
                    }
                    if let Some((tx, ty)) = tower_pos(state, tower_id) {
                        let dx = (tx - bounce_x) as i64;
                        let dy = (ty - bounce_y) as i64;
                        let dist = dx * dx + dy * dy;
                        if dist <= chain_sq && dist < best_dist {
                            best_id = Some(tower_id);
                            best_x = tx;
                            best_y = ty;
                            best_is_tower = true;
                            best_dist = dist;
                        }
                    }
                }

                let target_id = match best_id {
                    Some(id) => id,
                    None => break,
                };
                hit_ids.push(target_id);
                bounce_x = best_x;
                bounce_y = best_y;

                if best_is_tower {
                    apply_damage_to_tower(
                        state,
                        target_id,
                        apply_ct_reduction(kz.damage, kz.crown_tower_damage_percent),
                    );
                } else if let Some(target) = state.entities.iter_mut()
                    .find(|entity| entity.id == target_id && entity.alive)
                {
                    apply_damage_to_entity(target, kz.damage);
                    if let Some(ref buff_key) = kz.buff_key {
                        if let Some(buff_stats) = data.buffs.get(buff_key) {
                            target.add_buff(crate::entities::ActiveBuff::from_buff_stats(
                                buff_key.clone(),
                                kz.buff_time,
                                buff_stats,
                            ));
                        }
                    }
                }
            }
        }
    }

    // FIX: spawn_area_effect_object — create spell zone on kamikaze impact.
''',
    "Electro Spirit sequential chain resolution",
)


print(
    "Rudy patched: Electro Spirit preserves its data-driven nearest-target "
    "damage/stun chain; count/radius come from the current data overlay."
)
