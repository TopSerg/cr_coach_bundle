#!/usr/bin/env python3
"""Expose a narrow Rudy API for placements already accepted by the real game."""

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

text = LIB.read_text(encoding="utf-8")
marker = '''    /// Play a card from hand. Player: 1 or 2, hand_index: 0-3, (x, y) placement.
'''
method = r'''    /// Play a placement already observed in a real match.
    ///
    /// This uses the normal play_card spawn path, including deployment, spell,
    /// formation and evolution semantics, but deliberately bypasses economic
    /// validation. It is intended for replay reconstruction when the source
    /// proves that the server accepted the placement. The card still has to be
    /// one of the player's eight inferred/declared deck cards.
    #[pyo3(signature = (player, card_key, x, y, level=11))]
    fn play_observed_card(
        &mut self,
        player: i32,
        card_key: &str,
        x: i32,
        y: i32,
        level: usize,
    ) -> PyResult<u32> {
        let team = match player {
            1 => Team::Player1,
            2 => Team::Player2,
            _ => return Err(pyo3::exceptions::PyValueError::new_err("player must be 1 or 2")),
        };

        let hand_index = {
            let ps = self.state.player_mut(team);
            let deck_index = ps.deck.iter().position(|key| key == card_key).ok_or_else(|| {
                pyo3::exceptions::PyKeyError::new_err(format!(
                    "Observed card '{}' is not in the inferred/declared deck",
                    card_key
                ))
            })?;
            let slot = ps.hand.iter().position(|&index| index == deck_index).unwrap_or(0);
            if ps.hand[slot] != deck_index {
                ps.hand[slot] = deck_index;
            }
            ps.elixir = crate::game_state::MAX_ELIXIR;
            slot
        };

        self.play_card(player, hand_index, x, y, level)
    }

'''

if "fn play_observed_card(" in text:
    raise RuntimeError("Rudy observed-placement API is already present")
if text.count(marker) != 1:
    raise RuntimeError(f"expected one play_card marker, found {text.count(marker)}")

LIB.write_text(text.replace(marker, method + marker, 1), encoding="utf-8")
print("Rudy patched: play_observed_card() reuses the normal card spawn path.")
