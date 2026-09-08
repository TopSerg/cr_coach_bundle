# Clash Royale placement model used by CR Coach fidelity tests

## Why one `[col,row]` is not enough

There are three different spatial concepts and they must not be conflated:

1. **Selected tile / player-action anchor** — the arena tile under the placement cursor.
2. **Resolved entity center** — the point used by simulation movement/range/collision.
3. **Deployment footprint** — how many arena tiles the placed object occupies for placement/overlap purposes.

`collision_radius` is a fourth, separate concept.  It is not the deployment footprint.

## Canonical coordinate: `grid2`

The arena is 18x32 tiles. `grid2` uses integer half-tile coordinates from the top-left arena boundary.

- tile `(col,row)` center = `(2*col+1, 2*row+1)` -> odd/odd
- tile intersection = even/even
- one `grid2` unit = 0.5 tile = 500 Rudy units with the current 1000-units/tile arena

Conversion to Rudy center-origin coordinates:

```text
x_rudy = (grid2_x - 18) * 500
y_rudy = (32 - grid2_y) * 500
```

This avoids ambiguous float coordinates such as `10.5`.

## Card classes

| Card class | Example | Deploy footprint | Resolved center phase |
|---|---|---:|---|
| ordinary troop | Hog Rider | 1x1 anchor | tile center (odd/odd) |
| ordinary building | Cannon | 3x3 | tile center (odd/odd) |
| even-footprint building | Tesla | 2x2 | tile intersection (even/even) |
| even-footprint burrow building | Goblin Drill | 2x2 | tile intersection (even/even) |

For a 3x3 building the selected tile is the central tile, so selected tile center and entity center are the same point.

For a 2x2 building there is no central tile. The selected tile is one corner of the footprint and the geometric center is shifted by half a tile. Tesla has a True Red / True Blue placement asymmetry in the live game, so the corner choice must be preserved or inferred; it must not be silently collapsed to the selected tile center.

## Reference JSON

Video references should keep both the human-readable tile anchor and the unambiguous resolved center:

```json
"placements": {
  "hog": {
    "card": "hog-rider",
    "kind": "troop",
    "anchor_cell": [14, 17],
    "center_grid2": [29, 35],
    "footprint_tiles": [1, 1],
    "center_phase": "tile_center"
  },
  "cannon": {
    "card": "cannon",
    "kind": "building",
    "anchor_cell": [10, 10],
    "center_grid2": [21, 21],
    "footprint_tiles": [3, 3],
    "center_phase": "tile_center"
  }
}
```

For 2x2 cards `center_grid2` is authoritative. `anchor_cell` may also be stored when the selected cursor tile / True Red-True Blue corner is known.

## Current Rudy caveats

The pinned Rudy build currently has two placement limitations that the diagnostic probe tracks:

- `play_card()` accepts continuous coordinates for ordinary troops instead of resolving the player action to the tile lattice.
- the current CR Coach building-grid patch snaps every building center to the same tile-center lattice; that is correct for Cannon/ordinary 3x3 buildings but cannot represent the geometric center of Tesla/Goblin Drill 2x2.

Do not fix these by changing movement speed, attack range, or video timestamps. Placement resolution belongs in the player-action/placement layer.

Spells, Miner-style burrow deployment and unusual future cards need their own verified profiles before quantization is imposed on them.
