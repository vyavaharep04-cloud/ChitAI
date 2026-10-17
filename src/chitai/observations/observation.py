"""Player-specific, privacy-safe observations (M7, PROJECT_CONTEXT.md §3A.8, §4).

`observe(state, seat)` is the *only* thing an agent (or a client) learns about a
`GameState`. It is built field by field from an explicit allowlist; the state
itself, `state.config` (which holds the master seed and so determines every
past and future deal), other seats' hands and anti-stall streaks, physical
copy ids and timeout machinery never appear. An `Observation` holds only
primitives and tuples of primitives, so it is immutable, deterministic and
JSON-serializable through `to_dict()`.

Public fields are the same for every seat. Private fields are `my_seat`,
`my_hand` (chit *names*, sorted, with repeats) and `my_pass_streak_*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..engine import GameState, chit_names_for, is_valid_seat, pending_reactors
from .legal import legal_actions_for


@dataclass(frozen=True)
class Observation:
    """What `my_seat` may know. All fields are primitives or tuples of them.

    Public: num_players, num_rounds, pass_timeout_seconds, chit_names (the names
    in play; each appears four times), completed_rounds, attempt, initiator,
    phase and decision_kind (their `.value` strings), decision_seat, scores,
    hand_sizes, winner, reaction_order, pending_reactors, my_turn.

    Private to the observer: my_seat, my_hand (names only, sorted), and the
    observer's own anti-stall streak (`my_pass_streak_name` is None and
    `my_pass_streak_count` is 0 when it has none). Other seats' streaks are
    never read.

    In the terminal `game_over` state the hands are those of the final claim
    (§9 Q14); `my_hand` and `hand_sizes` report them as they stand.
    """

    my_seat: int
    num_players: int
    num_rounds: int
    pass_timeout_seconds: float
    chit_names: tuple[str, ...]
    completed_rounds: int
    attempt: int
    initiator: int
    phase: str
    decision_seat: int | None
    decision_kind: str | None
    scores: tuple[int, ...]
    hand_sizes: tuple[int, ...]
    my_hand: tuple[str, ...]
    my_pass_streak_name: str | None
    my_pass_streak_count: int
    winner: int | None
    reaction_order: tuple[int, ...]
    pending_reactors: tuple[int, ...]
    my_turn: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict (tuples become lists), deterministic key order."""
        return {
            "my_seat": self.my_seat,
            "num_players": self.num_players,
            "num_rounds": self.num_rounds,
            "pass_timeout_seconds": self.pass_timeout_seconds,
            "chit_names": list(self.chit_names),
            "completed_rounds": self.completed_rounds,
            "attempt": self.attempt,
            "initiator": self.initiator,
            "phase": self.phase,
            "decision_seat": self.decision_seat,
            "decision_kind": self.decision_kind,
            "scores": list(self.scores),
            "hand_sizes": list(self.hand_sizes),
            "my_hand": list(self.my_hand),
            "my_pass_streak_name": self.my_pass_streak_name,
            "my_pass_streak_count": self.my_pass_streak_count,
            "winner": self.winner,
            "reaction_order": list(self.reaction_order),
            "pending_reactors": list(self.pending_reactors),
            "my_turn": self.my_turn,
        }


def observe(state: GameState, seat: int) -> Observation:
    """The observation of `seat` for `state`. Raises `ValueError` for a seat that
    is not an integer in [0, num_players); the host, not an agent, supplies it."""
    if not is_valid_seat(state.config, seat):
        raise ValueError("seat must be an integer in [0, num_players)")
    config = state.config
    own_streak = next(
        ((name, count) for streak_seat, name, count in state.pass_streaks if streak_seat == seat),
        (None, 0),
    )
    return Observation(
        my_seat=seat,
        num_players=config.num_players,
        num_rounds=config.num_rounds,
        pass_timeout_seconds=float(config.pass_timeout_seconds),
        chit_names=tuple(chit_names_for(config.num_players)),
        completed_rounds=state.completed_rounds,
        attempt=state.attempt,
        initiator=state.initiator,
        phase=state.phase.value,
        decision_seat=state.decision_seat,
        decision_kind=None if state.decision_kind is None else state.decision_kind.value,
        scores=tuple(state.scores),
        hand_sizes=tuple(len(hand) for hand in state.hands),
        my_hand=tuple(sorted(chit.name for chit in state.hands[seat])),
        my_pass_streak_name=own_streak[0],
        my_pass_streak_count=own_streak[1],
        winner=state.winner,
        reaction_order=tuple(state.reaction_order),
        pending_reactors=tuple(pending_reactors(state)),
        my_turn=bool(legal_actions_for(state, seat)),
    )
