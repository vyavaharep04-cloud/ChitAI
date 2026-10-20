"""Event logs and CSV summaries (M8 Stage 4).

This package sits *above* the simulation package: it serialises results and engine events and
never changes how a game is played. Public event lines go through `observations.observe_event`;
the only reader of an event's private `debug_view()` is `diagnostics`, which feeds an opt-in,
separate file.
"""

from .diagnostics import fault_line, private_event_line
from .jsonl import game_end_line, public_event_line
from .recorder import GameRecorder
from .summary import SUMMARY_COLUMNS, summarize
from .tables import (
    AGENT_DIAGNOSTIC_COLUMNS,
    AGENT_DIAGNOSTIC_KEYS,
    GAME_COLUMNS,
    ROUND_COLUMNS,
    SEAT_COLUMNS,
    CsvWriter,
    agent_diagnostic_rows,
    game_row,
    read_csv,
    round_rows,
    seat_rows,
)

__all__ = [
    "AGENT_DIAGNOSTIC_COLUMNS",
    "AGENT_DIAGNOSTIC_KEYS",
    "GAME_COLUMNS",
    "ROUND_COLUMNS",
    "SEAT_COLUMNS",
    "SUMMARY_COLUMNS",
    "CsvWriter",
    "GameRecorder",
    "agent_diagnostic_rows",
    "fault_line",
    "game_end_line",
    "game_row",
    "private_event_line",
    "public_event_line",
    "read_csv",
    "round_rows",
    "seat_rows",
    "summarize",
]
