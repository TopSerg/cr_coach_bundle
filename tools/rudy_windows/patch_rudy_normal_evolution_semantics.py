#!/usr/bin/env python3
"""Keep normal `play_card()` deployments normal unless evolution state says otherwise.

Pinned Rudy currently treats `data.evolutions.contains_key(card)` as equivalent to
"this play is evolved". That makes every normal Cannon an Evo Cannon and leaks
its deploy ability into ordinary fidelity tests. The engine does not yet model
real deck evolution-cycle state in PlayerState, so the safe baseline for the
standard play API is a normal card. Evo-specific tests stay separate until an
explicit cycle/evolved-play API is implemented.
"""
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2]
    / "third_party" / "clash-royale-suite" / "cr-rudy-sim"
    / "simulator" / "engine" / "src"
)
LIB = ROOT / "lib.rs"

text = LIB.read_text(encoding="utf-8")

old_building = """            // Phase 3: Buildings can be evolved too (e.g., Furnace, Cannon, Tesla)
            let is_evo = self.data.evolutions.contains_key(&card_key);
            if is_evo {"""
new_building = """            // Standard play_card() means the normal card. Evolution availability
            // in GameData is NOT the same as the current deck cycle being evolved.
            // Real evolution-cycle state is not modeled here yet, so do not leak
            // Evo abilities into ordinary building deployments.
            let is_evo = false;
            if is_evo {"""

old_character = """            // Phase 3: Check if this card has an evolution or hero variant
            let is_evo = self.data.evolutions.contains_key(&card_key);
            let is_hero = hero_system::is_hero_card(&self.data, &card_key);"""
new_character = """            // Standard play_card() means the normal card. Merely having an Evo
            // definition in GameData must not make every deployment evolved.
            let is_evo = false;
            let is_hero = hero_system::is_hero_card(&self.data, &card_key);"""

for label, old, new in [
    ("building auto-evo", old_building, new_building),
    ("character auto-evo", old_character, new_character),
]:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {LIB}, found {count}")
    text = text.replace(old, new, 1)

LIB.write_text(text, encoding="utf-8")
print("patched normal evolution semantics: ordinary play_card() no longer auto-evolves")
