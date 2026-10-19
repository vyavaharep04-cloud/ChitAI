"""Private diagnostics lines (M8 Stage 4, opt-in; PROJECT_CONTEXT.md §6: "Keep any private
debugging log separate from observations").

This is the only module of the package that reads an event's `debug_view()`, which is the
private record of the whole table (hands, the chit of a draw, ...). Its output goes to a
separate file that is written only when `OutputOptions.private_diagnostics` is true and must
never be shown to an agent or a client. A fault line carries the runner's internal category
(`exception`, `illegal`, ...) and the round and attempt; it never carries exception text or
the offending object.
"""

from __future__ import annotations

from ..simulation import canonical_json


def private_event_line(game_index: int, event: object) -> str:
    return canonical_json({"record": "event", "game_index": game_index, "event": event.debug_view()})


def fault_line(game_index: int, seat: int, kind: str, completed_round: int, attempt: int) -> str:
    return canonical_json(
        {
            "record": "fault",
            "game_index": game_index,
            "seat": seat,
            "kind": kind,
            "completed_round": completed_round,
            "attempt": attempt,
        }
    )


__all__ = ["fault_line", "private_event_line"]
