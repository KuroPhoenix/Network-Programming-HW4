from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MoveResult:
    valid: bool
    row: Optional[int] = None
    col: Optional[int] = None
    winner: Optional[int] = None
    draw: bool = False


class ConnectFourBoard:
    """
    Minimal Connect Four board logic.
    Rows are indexed from top (0) to bottom; columns from left (0) to right.
    """

    def __init__(self, rows: int = 6, cols: int = 7, connect: int = 4):
        self.rows = rows
        self.cols = cols
        self.connect = connect
        self.grid: List[List[int]] = [[0 for _ in range(cols)] for _ in range(rows)]
        self.turn: int = 1  # 1 or 2
        self.last_move: tuple[int, int] | None = None

    def reset(self) -> None:
        self.grid = [[0 for _ in range(self.cols)] for _ in range(self.rows)]
        self.turn = 1
        self.last_move = None

    def valid_moves(self) -> List[int]:
        return [c for c in range(self.cols) if self.grid[0][c] == 0]

    def is_full(self) -> bool:
        return all(cell != 0 for cell in self.grid[0])

    def drop(self, col: int, player: int) -> MoveResult:
        """
        Drop a piece for `player` (1 or 2) into column `col`.
        Returns MoveResult describing the outcome.
        """
        if player not in (1, 2):
            return MoveResult(valid=False)
        if col < 0 or col >= self.cols:
            return MoveResult(valid=False)
        if self.grid[0][col] != 0:
            return MoveResult(valid=False)

        row_to_fill = None
        for r in range(self.rows - 1, -1, -1):
            if self.grid[r][col] == 0:
                self.grid[r][col] = player
                row_to_fill = r
                break

        if row_to_fill is None:
            return MoveResult(valid=False)

        self.last_move = (row_to_fill, col)
        winner = player if self._check_win_from(row_to_fill, col, player) else None
        draw = winner is None and self.is_full()
        self.turn = 1 if player == 2 else 2
        return MoveResult(valid=True, row=row_to_fill, col=col, winner=winner, draw=draw)

    def _check_direction(self, row: int, col: int, dr: int, dc: int, player: int) -> int:
        count = 0
        r, c = row, col
        while 0 <= r < self.rows and 0 <= c < self.cols and self.grid[r][c] == player:
            count += 1
            r += dr
            c += dc
        return count

    def _check_win_from(self, row: int, col: int, player: int) -> bool:
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        for dr, dc in directions:
            total = self._check_direction(row, col, dr, dc, player) + self._check_direction(row, col, -dr, -dc, player) - 1
            if total >= self.connect:
                return True
        return False

    def to_state(self) -> dict:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "grid": self.grid,
            "turn": self.turn,
            "last_move": self.last_move,
            "valid_moves": self.valid_moves(),
        }
