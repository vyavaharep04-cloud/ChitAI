"""Public event log lines (M8 Stage 4, PROJECT_CONTEXT.md §6, §3A.8, M8 decision D9).

One JSON object per line, canonical (sorted keys, compact, ASCII). Each event line is the
engine event's *public view* obtained through `observations.observe_event(event, None)`: the
stream a spectator could see. It contains no hand, no chit name, no timeout chit, no seed and
no copy id. Seeds and diagnostics live only in the host-side tables and the opt-in private
diagnostics file.
"""

from __future__ import annotations

from ..observations import observe_event
from ..simulation import GameResult, canonical_json


def public_event_line(game_index: int, event: object) -> str:
    """The public line for one engine event of game `game_index`."""
    return canonical_json({"record": "event", "game_index": game_index, "event": observe_event(event, None)})


def game_end_line(result: GameResult) -> str:
    """The closing line of a game: how it ended. Truncated games say so explicitly."""
    return canonical_json(
        {
            "record": "game_end",
            "game_index": result.game_index,
            "status": result.status,
            "completed_rounds": result.completed_rounds,
            "stopped_attempt": result.stopped_attempt,
            "actions": result.actions,
        }
    )


__all__ = ["game_end_line", "public_event_line"]
