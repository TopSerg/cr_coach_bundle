#!/usr/bin/env python3
"""Bring the ordinary Goblins card to the current four-unit deployment.

The pinned Rudy code groups Goblins with old three-unit triangle cards and
hard-caps the formation at three. Current public card data says four Goblins.
Keep the existing triangle branch for true three-unit cards and give Goblins a
compact four-unit diamond. Exact sub-tile spacing remains video-calibratable;
the unit count itself is public game data.
"""
from pathlib import Path

ROOT=(
    Path(__file__).resolve().parents[2]
    / "third_party" / "clash-royale-suite" / "cr-rudy-sim"
    / "simulator" / "engine" / "src"
)
LIB=ROOT/"lib.rs"
text=LIB.read_text(encoding="utf-8")

old_cond='''                } else if card_key == "skeletons" || card_key == "guards"
                    || card_key == "goblins" || card_key == "spear-goblins" || card_key == "minions" {
'''
new_cond='''                } else if card_key == "goblins" {
                // ── Compact diamond (current 4-Goblin card) ──
                let cr = unit_stats.collision_radius.max(200);
                let fwd = team.forward_y();
                let offsets: [(i32, i32); 4] = [
                    (0, cr * fwd),
                    (-cr, 0),
                    (cr, 0),
                    (0, -cr * fwd),
                ];
                for i in 0..spawn_count.min(4) {
                    let uid = if i == 0 { id } else { self.state.alloc_id() };
                    let (ox, oy) = offsets[i as usize];
                    let mut entity = Entity::new_troop(
                        uid, team, unit_stats, x + ox, y + oy, level, is_evo,
                    );
                    if i > 0 && unit_stats.deploy_delay > 0 {
                        let stagger = entities::ms_to_ticks(unit_stats.deploy_delay) * i as i32;
                        entity.deploy_timer += stagger;
                    }
                    if is_evo {
                        evo_system::apply_evo_stat_modifiers(&mut entity, &self.data);
                    }
                    if is_hero {
                        hero_system::setup_hero_state(&mut entity, &card_key);
                    }
                    self.state.entities.push(entity);
                }
                } else if card_key == "skeletons" || card_key == "guards"
                    || card_key == "spear-goblins" || card_key == "minions" {
'''
count=text.count(old_cond)
if count!=1:
    raise RuntimeError(f"expected one old Goblins/triangle branch, found {count}")
text=text.replace(old_cond,new_cond,1)

# Skeletons are one simultaneous three-unit card deployment. The old generic
# triangle code additionally staggered unit 2/3 using the component Skeleton's
# deploy_delay, producing 1.0/1.4/1.8s activation in the replay. Current game
# data carries a 1.0s deploy time but no per-Skeleton stagger for this card.
triangle_marker="// ── Triangle formation (3-unit cards) ──"
triangle_pos=text.index(triangle_marker)
stagger='''                    if i > 0 && unit_stats.deploy_delay > 0 {
                        let stagger = entities::ms_to_ticks(unit_stats.deploy_delay) * i as i32;
                        entity.deploy_timer += stagger;
                    }
'''
stagger_pos=text.index(stagger,triangle_pos)
replacement='''                    if card_key != "skeletons" && i > 0 && unit_stats.deploy_delay > 0 {
                        let stagger = entities::ms_to_ticks(unit_stats.deploy_delay) * i as i32;
                        entity.deploy_timer += stagger;
                    }
'''
text=text[:stagger_pos]+replacement+text[stagger_pos+len(stagger):]

LIB.write_text(text,encoding="utf-8")
print("Rudy patched: current four-Goblin deployment + simultaneous Skeletons card deploy.")
