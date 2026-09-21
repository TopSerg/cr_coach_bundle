#!/usr/bin/env python3
"""Make crown-tower target retention follow the shared CR targeting rule.

Princess/King towers keep their acquired troop target until that target dies or
leaves the tower's effective range.  Re-selecting the nearest troop every tick
lets a newly arriving Bat steal the target from Night Witch before Night Witch
dies, which changes both the tower damage timing and the Bat survival sequence.

This is deliberately a global tower rule: it applies to every troop/building
targeted by every crown tower, not to a card-specific replay case.
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
COMBAT = ROOT / "combat.rs"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


old = """        for (tx, ty, range, damage, tower_radius, tower_id) in &tower_infos {
            let mut best_idx: Option<usize> = None;
            let mut best_dist = i64::MAX;

            for (_, team, ex, ey, target_radius, _, alive, entity_idx) in &targets {
                if !alive || *team != enemy_team {
                    continue;
                }
                let dx = (*tx - ex) as i64;
                let dy = (*ty - ey) as i64;
                let center_dist_sq = dx * dx + dy * dy;
                let effective_range = *range as i64 + *tower_radius + *target_radius;
                if center_dist_sq <= effective_range * effective_range && center_dist_sq < best_dist {
                    best_dist = center_dist_sq;
                    best_idx = Some(*entity_idx);
                }
            }

            // Snapshot target data before borrowing the tower mutably.
            let best_target = best_idx.map(|idx| {
                let target = &state.entities[idx];
                (target.id, target.x, target.y)
            });
"""

new = """        for (tx, ty, range, damage, tower_radius, tower_id) in &tower_infos {
            // Crown towers retain a valid acquired target.  Only acquire a new
            // target when the old one is dead, untargetable, or outside the
            // effective range.  This is the shared tower rule for all troops;
            // nearest-target selection is only used for a fresh acquisition.
            let tracked_target = {
                let player = state.player(player_team);
                let tower = match *tower_id {
                    0 => &player.princess_left,
                    1 => &player.princess_right,
                    2 => &player.king,
                    _ => continue,
                };
                tower.attack_target.and_then(|target_id| {
                    targets.iter().find_map(|(id, team, ex, ey, target_radius, _, alive, entity_idx)| {
                        if *id != target_id || !*alive || *team != enemy_team {
                            return None;
                        }
                        let dx = (*tx - ex) as i64;
                        let dy = (*ty - ey) as i64;
                        let center_dist_sq = dx * dx + dy * dy;
                        let effective_range = *range as i64 + *tower_radius + *target_radius;
                        if center_dist_sq <= effective_range * effective_range {
                            Some(*entity_idx)
                        } else {
                            None
                        }
                    })
                })
            };

            let best_idx = tracked_target.or_else(|| {
                let mut nearest: Option<usize> = None;
                let mut best_dist = i64::MAX;
                for (_, team, ex, ey, target_radius, _, alive, entity_idx) in &targets {
                    if !alive || *team != enemy_team {
                        continue;
                    }
                    let dx = (*tx - ex) as i64;
                    let dy = (*ty - ey) as i64;
                    let center_dist_sq = dx * dx + dy * dy;
                    let effective_range = *range as i64 + *tower_radius + *target_radius;
                    if center_dist_sq <= effective_range * effective_range && center_dist_sq < best_dist {
                        best_dist = center_dist_sq;
                        nearest = Some(*entity_idx);
                    }
                }
                nearest
            });

            // Snapshot target data before borrowing the tower mutably.
            let best_target = best_idx.map(|idx| {
                let target = &state.entities[idx];
                (target.id, target.x, target.y)
            });
"""

replace_once(COMBAT, old, new, "global crown-tower target retention")
print("Rudy patched: crown towers retain a valid target until death or range loss.")

