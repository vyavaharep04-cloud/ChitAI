"""The runner's host-side observer: collects one game's log lines in memory (Stage 4).

Implements the three-method recorder protocol of `simulation.runner` (`opening`, `accepted`,
`fault`). It only reads what it is given and never talks to an agent. The batch writer takes
the finished lines and appends them to the files.
"""

from __future__ import annotations

from .diagnostics import fault_line, private_event_line
from .jsonl import public_event_line


class GameRecorder:
    def __init__(self, game_index: int, *, public: bool = True, private: bool = False) -> None:
        self.game_index = game_index
        self.public = public
        self.private = private
        self.public_lines: list[str] = []
        self.private_lines: list[str] = []

    def opening(self, events) -> None:
        self._events(events)

    def accepted(self, events) -> None:
        self._events(events)

    def fault(self, seat: int, kind: str, completed_round: int, attempt: int) -> None:
        if self.private:
            self.private_lines.append(fault_line(self.game_index, seat, kind, completed_round, attempt))

    def _events(self, events) -> None:
        for event in events:
            if self.public:
                self.public_lines.append(public_event_line(self.game_index, event))
            if self.private:
                self.private_lines.append(private_event_line(self.game_index, event))


__all__ = ["GameRecorder"]
