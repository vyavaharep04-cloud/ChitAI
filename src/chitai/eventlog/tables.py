"""CSV tables of results (M8 Stage 4, PROJECT_CONTEXT.md §6: "export summaries to CSV").

Three tidy tables, one row per game, per seat of a game and per completed round. Columns and
their order are fixed, values are plain text, lists are space-separated, booleans are
`true`/`false` and an undefined value (for example the rank of a truncated game) is an empty
cell. Files are UTF-8 with `\\n` line endings on every platform. These are host-side records:
they carry the game seed, which agents and the public event log never see.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

from ..simulation import GameResult

GAME_COLUMNS = (
    "game_index", "game_seed", "status", "num_players", "num_rounds", "completed_rounds",
    "stopped_attempt", "draw_restarts", "actions", "tie_for_first", "winning_seats",
)  # fmt: skip
SEAT_COLUMNS = (
    "game_index", "status", "seat", "lineup_index", "agent_type", "agent_version",
    "agent_config_json", "score", "rank", "tied", "rounds_won", "false_claims", "timeouts",
    "agent_faults",
)  # fmt: skip
ROUND_COLUMNS = (
    "game_index", "round_index", "outcome", "initiator", "claimant", "attempts",
    "draw_restarts", "reaction_order", "score_changes",
)  # fmt: skip


def cell(value: object) -> str:
    """The text of one cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (tuple, list)):
        return " ".join(str(item) for item in value)
    return str(value)


def game_row(result: GameResult) -> list[str]:
    return [
        cell(v)
        for v in (
            result.game_index, result.game_seed, result.status, result.num_players, result.num_rounds,
            result.completed_rounds, result.stopped_attempt, result.draw_restarts, result.actions,
            result.tie_for_first, result.winning_seats,
        )
    ]  # fmt: skip


def seat_rows(result: GameResult) -> list[list[str]]:
    return [
        [
            cell(v)
            for v in (
                result.game_index, result.status, s.seat, s.lineup_index, s.agent_type, s.agent_version,
                s.agent_config_json, s.score, s.rank, s.tied, s.rounds_won, s.false_claims, s.timeouts,
                s.agent_faults,
            )
        ]
        for s in result.seats
    ]  # fmt: skip


def round_rows(result: GameResult) -> list[list[str]]:
    return [
        [
            cell(v)
            for v in (
                result.game_index, r.round_index, r.outcome, r.initiator, r.claimant, r.attempts,
                r.attempts - 1, r.reaction_order, r.score_changes,
            )
        ]
        for r in result.rounds
    ]  # fmt: skip


class CsvWriter:
    """Writes one table: header first, then rows; closes its file on exit."""

    def __init__(self, path: Path, columns: Sequence[str]) -> None:
        self._handle = open(path, "w", encoding="utf-8", newline="")
        self._writer = csv.writer(self._handle, lineterminator="\n")
        self._width = len(columns)
        self._writer.writerow(columns)

    def writerow(self, row: Sequence[str]) -> None:
        if len(row) != self._width:
            raise ValueError(f"expected {self._width} cells, got {len(row)}")
        self._writer.writerow(row)

    def writerows(self, rows: Iterable[Sequence[str]]) -> None:
        for row in rows:
            self.writerow(row)

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> CsvWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_csv(path: Path) -> list[dict[str, str]]:
    """The rows of a table written by this module, as dicts of text."""
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


__all__ = [
    "GAME_COLUMNS", "ROUND_COLUMNS", "SEAT_COLUMNS", "CsvWriter", "cell", "game_row", "read_csv",
    "round_rows", "seat_rows",
]  # fmt: skip
