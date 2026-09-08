#!/usr/bin/env python3
"""Canonical Clash Royale placement coordinates for fidelity tests.

The video annotation grid uses the visible 18x32 arena tiles with a top-left
origin.  A single integer cell is not sufficient for every card: ordinary
single troops and 3x3 buildings have their entity center at a tile center,
while even-footprint buildings (Tesla/Goblin Drill: 2x2) have their geometric
center between four tile centers.

To avoid floats and ambiguous `10.5` coordinates, `grid2` stores coordinates
in half-tile units measured from the arena's top-left *boundary*:

  tile (col, row) center -> grid2 = (2*col + 1, 2*row + 1)  [odd, odd]
  tile intersection      -> grid2 = (even, even)

Rudy uses a center-origin Cartesian frame where +X is right, +Y is toward P2.
With TILE_SIZE=1000 this converts exactly in 500-unit increments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

ARENA_COLS = 18
ARENA_ROWS = 32
TILE_SIZE = 1000
HALF_TILE = TILE_SIZE // 2


@dataclass(frozen=True)
class PlacementProfile:
    card_key: str
    kind: str
    footprint_tiles: tuple[int, int]
    selected_anchor: str
    notes: str = ""

    @property
    def center_phase(self) -> str:
        w, h = self.footprint_tiles
        if w % 2 == 1 and h % 2 == 1:
            return "tile_center"
        if w % 2 == 0 and h % 2 == 0:
            return "tile_intersection"
        return "mixed"


# Current deployable exceptions that matter to the simulator.  Cannon and the
# other ordinary buildings are 3x3; Tesla and Goblin Drill are 2x2.  Keep this
# separate from collision_radius: footprint controls legal placement/anchor,
# collision radius controls targeting/pathing.
CARD_PROFILES: dict[str, PlacementProfile] = {
    "hog-rider": PlacementProfile("hog-rider", "troop", (1, 1), "tile_center"),
    "cannon": PlacementProfile("cannon", "building", (3, 3), "center_tile"),
    "tesla": PlacementProfile(
        "tesla",
        "building",
        (2, 2),
        "true_side_corner",
        "2x2 has no center tile; selected tile and geometric center differ by 0.5 tile.",
    ),
    "goblin-drill": PlacementProfile(
        "goblin-drill",
        "building",
        (2, 2),
        "true_side_corner",
        "2x2 building; can deploy across the arena via its burrow mechanic.",
    ),
}


def profile_for(card_key: str, kind: str | None = None) -> PlacementProfile:
    key = card_key.lower()
    if key in CARD_PROFILES:
        return CARD_PROFILES[key]
    if kind == "building":
        return PlacementProfile(key, "building", (3, 3), "center_tile")
    return PlacementProfile(key, kind or "troop", (1, 1), "tile_center")


def _pair(value: Sequence[int] | Iterable[int]) -> tuple[int, int]:
    a, b = value
    return int(a), int(b)


def cell_center_to_grid2(cell: Sequence[int]) -> tuple[int, int]:
    """Top-left-origin tile index -> exact tile-center grid2 coordinate."""
    col, row = _pair(cell)
    if not (0 <= col < ARENA_COLS and 0 <= row < ARENA_ROWS):
        raise ValueError(f"cell outside {ARENA_COLS}x{ARENA_ROWS} arena: {cell}")
    return 2 * col + 1, 2 * row + 1


def grid2_to_rudy(grid2: Sequence[int]) -> tuple[int, int]:
    """Half-tile top-left-boundary coordinate -> Rudy center-origin units."""
    gx2, gy2 = _pair(grid2)
    if not (0 <= gx2 <= 2 * ARENA_COLS and 0 <= gy2 <= 2 * ARENA_ROWS):
        raise ValueError(f"grid2 outside arena boundary: {grid2}")
    x = (gx2 - ARENA_COLS) * HALF_TILE
    y = (ARENA_ROWS - gy2) * HALF_TILE
    return x, y


def cell_center_to_rudy(cell: Sequence[int]) -> tuple[int, int]:
    return grid2_to_rudy(cell_center_to_grid2(cell))


def phase_of(grid2: Sequence[int]) -> str:
    gx2, gy2 = _pair(grid2)
    if gx2 % 2 == 1 and gy2 % 2 == 1:
        return "tile_center"
    if gx2 % 2 == 0 and gy2 % 2 == 0:
        return "tile_intersection"
    return "half_tile_mixed"


def validate_center_phase(card_key: str, grid2: Sequence[int], kind: str | None = None) -> bool:
    """Check only lattice phase, not deploy-zone legality/overlap."""
    return phase_of(grid2) == profile_for(card_key, kind).center_phase


def even_footprint_center_from_selected_tile(
    selected_cell: Sequence[int], *, selected_corner: str
) -> tuple[int, int]:
    """Resolve a 2x2 building center from the tile under the placement cursor.

    Historical/current Tesla placement can use different selected corners for
    True Blue vs True Red.  We deliberately take the corner explicitly rather
    than baking an unverified screen-orientation assumption into the engine.

    `top_left` means the selected tile is the top-left tile of the 2x2 footprint;
    `bottom_right` means it is the bottom-right tile.  Result is always even/even.
    """
    gx2, gy2 = cell_center_to_grid2(selected_cell)
    if selected_corner == "top_left":
        return gx2 + 1, gy2 + 1
    if selected_corner == "bottom_right":
        return gx2 - 1, gy2 - 1
    if selected_corner == "top_right":
        return gx2 - 1, gy2 + 1
    if selected_corner == "bottom_left":
        return gx2 + 1, gy2 - 1
    raise ValueError(f"unknown selected_corner: {selected_corner}")


def placement_spec_to_rudy(spec: dict) -> tuple[int, int]:
    """Resolve the explicit reference schema used by video regression files."""
    if "center_grid2" in spec:
        return grid2_to_rudy(spec["center_grid2"])
    if "anchor_cell" in spec:
        return cell_center_to_rudy(spec["anchor_cell"])
    raise KeyError("placement spec needs center_grid2 or anchor_cell")
