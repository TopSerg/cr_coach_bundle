from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass(frozen=True, slots=True)
class ReplayGridAdapter:
    """Initial hypothesis for RoyaleAPI/Cochon mtile -> 18x32 action grid.

    Replay coordinates are treated as approximately 1000 units per tile.
    Calibration against known bridge/tower placements MUST happen before
    accepting this mapping as authoritative.
    """
    cols: int = 18
    rows: int = 32
    mtile_per_cell: int = 1000

    def to_cell(self, x_mtile: int, y_mtile: int, *, flip_y: bool = False) -> tuple[int, int]:
        col = math.floor(x_mtile / self.mtile_per_cell)
        row = math.floor(y_mtile / self.mtile_per_cell)
        if flip_y:
            row = self.rows - 1 - row
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            raise ValueError(f"coordinate outside grid: x={x_mtile} y={y_mtile} -> ({col},{row})")
        return col, row

    def cell_center_mtile(self, col: int, row: int, *, flip_y: bool = False) -> tuple[int, int]:
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            raise ValueError("cell outside grid")
        if flip_y:
            row = self.rows - 1 - row
        half = self.mtile_per_cell // 2
        return col * self.mtile_per_cell + half, row * self.mtile_per_cell + half
