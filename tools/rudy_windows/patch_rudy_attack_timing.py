#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "third_party" / "clash-royale-suite" / "cr-rudy-sim" / "simulator" / "engine" / "src"


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {label}")


entities = ROOT / "entities.rs"
combat = ROOT / "combat.rs"

# Clash Royale's public "First Hit Speed" is not an extra cooldown added before
# the regular attack windup. For the standard data model it is the shortened first
# attack period obtained from Hit Speed and hidden Load Time:
#
#     first_hit_speed = hit_speed - load_time
#
# Example: Hog Rider 1.6 s hit speed - 1.0 s load time = 0.6 s first hit.
# Rudy previously used load_first_hit as an ADDITIONAL cooldown and then ran the
# normal windup, which double-counted first-hit timing. Store the derived first
# windup explicitly and use it only until the troop has actually fired once.

replace_once(
    entities,
    """    /// Windup duration in ticks (from load_time). Damage is dealt when this expires.
    pub windup_ticks: i32,
    /// Backswing duration in ticks (hit_speed - load_time). Recovery after hit.
    pub backswing_ticks: i32,""",
    """    /// Regular pre-hit windup duration in ticks (from load_time).
    pub windup_ticks: i32,
    /// First pre-hit windup after deployment. For standard CR data this is
    /// hit_speed - load_time (the public First Hit Speed).
    pub first_windup_ticks: i32,
    /// Backswing duration in ticks (hit_speed - load_time). Recovery after hit.
    pub backswing_ticks: i32,""",
    "first windup field",
)

replace_once(
    entities,
    """                // Initial attack cooldown: load_first_hit from data gives the delay
                // before the very first attack after deployment. This value is consumed
                // once (counted down in tick_combat) and never needs to be re-read,
                // so we don't store load_first_hit as a separate TroopData field.
                attack_cooldown: ms_to_ticks(stats.load_first_hit),
                load_after_retarget: ms_to_ticks(stats.load_after_retarget),""",
    """                // First-hit timing is handled by first_windup_ticks below.
                // Do NOT add load_first_hit as a separate cooldown before the windup:
                // that double-counts the first attack period.
                attack_cooldown: 0,
                load_after_retarget: ms_to_ticks(stats.load_after_retarget),""",
    "remove additive first-hit cooldown",
)

replace_once(
    entities,
    """                phase_timer: 0,
                windup_ticks: ms_to_ticks(stats.load_time),
                backswing_ticks: {""",
    """                phase_timer: 0,
                windup_ticks: ms_to_ticks(stats.load_time),
                first_windup_ticks: {
                    // Public First Hit Speed = Hit Speed - Load Time for the normal
                    // troop attack model (Hog: 1600 - 1000 = 600 ms).
                    let first_ms = (stats.hit_speed - stats.load_time).max(0);
                    ms_to_ticks(first_ms)
                },
                backswing_ticks: {""",
    "derive first-hit speed from hit/load time",
)

# Select the shortened first windup only until the first real attack event has fired.
replace_once(
    combat,
    """                        // Start windup if in range and ready
                        if dist_sq <= effective_attack_range_sq && troop.attack_cooldown <= 0 {
                            if troop.windup_ticks > 0 {
                                troop.attack_phase = AttackPhase::Windup;
                                // Scale windup duration by hit speed buff.
                                // Rage (135%) → windup takes 100/135 = 74% of normal time.
                                // Slow (50%) → windup takes 100/50 = 200% of normal time.
                                let scaled_windup = (troop.windup_ticks as i64 * 100 / hitspeed_mult as i64) as i32;
                                troop.phase_timer = scaled_windup.max(1);
                                troop.windup_target = Some(target_id);
                            } else {""",
    """                        // Start windup if in range and ready. The first attack has
                        // its own public First Hit Speed; later attacks use load_time.
                        if dist_sq <= effective_attack_range_sq && troop.attack_cooldown <= 0 {
                            let base_windup_ticks = if !troop.has_fired_first {
                                troop.first_windup_ticks
                            } else {
                                troop.windup_ticks
                            };
                            if base_windup_ticks > 0 {
                                troop.attack_phase = AttackPhase::Windup;
                                // Scale windup duration by hit speed buff.
                                // Rage (135%) → windup takes 100/135 = 74% of normal time.
                                // Slow (50%) → windup takes 100/50 = 200% of normal time.
                                let scaled_windup = (base_windup_ticks as i64 * 100 / hitspeed_mult as i64) as i32;
                                troop.phase_timer = scaled_windup.max(1);
                                troop.windup_target = Some(target_id);
                            } else {""",
    "use first-hit windup before first attack",
)

# `has_fired_first` used to be updated only for troops that had a custom first
# projectile. Make it a general attack-state flag so First Hit Speed applies once
# to every troop, while preserving custom-first-projectile behaviour.
replace_once(
    combat,
    """    // ─── Fix #10: Mark has_fired_first for custom_first_projectile ───
    // After collecting attacks, mark troops that fired their first shot.
    for atk in &attacks {
        if atk.custom_first_projectile.is_some() {
            if atk.attacker_idx < state.entities.len() {
                if let EntityKind::Troop(ref mut t) = state.entities[atk.attacker_idx].kind {
                    t.has_fired_first = true;
                }
            }
        }
    }""",
    """    // Mark every troop after its first actual attack event. This flag drives
    // both First Hit Speed and custom_first_projectile selection.
    for atk in &attacks {
        if atk.attacker_idx < state.entities.len() {
            if let EntityKind::Troop(ref mut t) = state.entities[atk.attacker_idx].kind {
                t.has_fired_first = true;
            }
        }
    }""",
    "general first-attack fired flag",
)

print("Rudy attack timing patched: First Hit Speed is distinct from regular load time.")
