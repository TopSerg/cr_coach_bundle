#!/usr/bin/env python3
"""Fix Rudy building snapping after switching the arena to 1000 units/tile.

The arena is 18 tiles wide with its origin between the two centre columns, so
actual tile centres lie on half-tile coordinates: ..., -1500, -500, +500,
+1500, ... . Upstream Rudy's building snap rounds to integer multiples of
TILE_SIZE, which moves a requested (+500,+5500) Cannon to (+1000,+6000).

That is inconsistent with the patched arena/tower geometry and adds artificial
path length to Hog-vs-Cannon fidelity probes.
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

old = """            if is_building_deploy {
                let tile = game_state::TILE_SIZE;
                if tile > 0 {
                    // Snap to nearest tile center: round to nearest multiple of tile_size,
                    // then offset by half a tile to center within the tile.
                    let half = tile / 2;
                    cx = ((cx + half) / tile) * tile;
                    cy = ((cy + half) / tile) * tile;
                }
            }"""

new = """            if is_building_deploy {
                let tile = game_state::TILE_SIZE;
                if tile > 0 {
                    // Odd footprints have a centre tile; even footprints have
                    // their geometric centre at an intersection of four tiles.
                    // Placement footprint is independent of collision radius.
                    let even_footprint = card_key == "tesla" || card_key == "goblin-drill";
                    if even_footprint {
                        let half = tile / 2;
                        cx = cx.div_euclid(tile) * tile + if cx.rem_euclid(tile) >= half { tile } else { 0 };
                        cy = cy.div_euclid(tile) * tile + if cy.rem_euclid(tile) >= half { tile } else { 0 };
                    } else {
                        // The 18x32 arena origin lies on a grid intersection, so
                        // odd-footprint centres are half a tile from the origin.
                        let half = tile / 2;
                        cx = cx.div_euclid(tile) * tile + half;
                        cy = cy.div_euclid(tile) * tile + half;
                    }
                }
            }"""

text = LIB.read_text(encoding="utf-8")
count = text.count(old)
if count != 1:
    raise RuntimeError(f"building grid snap: expected exactly one match in {LIB}, found {count}")
LIB.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched building grid: footprint-aware lattice for 18x32 arena")
