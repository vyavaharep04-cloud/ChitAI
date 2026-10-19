"""Result records, termination statuses and ranking (M8 Stage 2).

These are plain, immutable records of primitives (ints, strings, bools, None and
tuples of those), so a later writer can serialise them without knowing anything
about the engine. This module computes nothing about a game by itself; the runner
(Stage 3) fills the records in and these classes check that they are consistent.

Rules recorded here:

* D7 ranking. Equal scores share a rank and the next rank is skipped (shared
  competition ranking, "1,2,2,4"). Raw scores are always kept and ties are recorded
  explicitly. No tie is ever broken to manufacture a unique winner.
* D1 / D8 truncated games. A game whose status is not `completed` carries **no**
  final rank, no tie flag and no winners, and is never treated as completed. Scores
  of such a game are the engine's unaltered totals from the rounds completed before
  the stop (scores only change when a round closes), kept for diagnosis only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..engine import ROUND_OUTCOME_FALSE_CLAIM, ROUND_OUTCOME_VALID_WIN

STATUS_COMPLETED = "completed"
STATUS_DRAW_CAP_REACHED = "draw_cap_reached"
STATUS_ACTION_CAP_REACHED = "action_cap_reached"
STATUS_AGENT_FAULT_UNRESOLVABLE = "agent_fault_unresolvable"

TERMINATION_STATUSES = (
    STATUS_COMPLETED,
    STATUS_DRAW_CAP_REACHED,
    STATUS_ACTION_CAP_REACHED,
    STATUS_AGENT_FAULT_UNRESOLVABLE,
)
STOPPED_STATUSES = TERMINATION_STATUSES[1:]  # every status except `completed`

ROUND_OUTCOMES = (ROUND_OUTCOME_VALID_WIN, ROUND_OUTCOME_FALSE_CLAIM)


class ResultError(ValueError):
    """Raised when a result record is inconsistent."""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int(name: str, value: object, minimum: int | None = None) -> int:
    if not _is_int(value):
        raise ResultError(f"{name} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:  # type: ignore[operator]
        raise ResultError(f"{name} must be at least {minimum}, got {value}")
    return value  # type: ignore[return-value]


def _int_tuple(name: str, value: object) -> tuple[int, ...]:
    if not isinstance(value, tuple) or not all(_is_int(item) for item in value):
        raise ResultError(f"{name} must be a tuple of integers, got {value!r}")
    return value


# --- ranking ------------------------------------------------------------------------------


def competition_ranks(scores: Sequence[int]) -> tuple[int, ...]:
    """Shared competition ranks, higher score first: `rank = 1 + (number of
    strictly higher scores)`. Ties share a rank and the following ranks are
    skipped: scores (10, 5, 5, 1) give (1, 2, 2, 4). The result is in seat order.
    """
    values = tuple(scores)
    for score in values:
        if not _is_int(score):
            raise ResultError(f"scores must be integers, got {score!r}")
    return tuple(1 + sum(other > score for other in values) for score in values)


def final_ranks(status: str, scores: Sequence[int]) -> tuple[int | None, ...]:
    """Ranks to record for a game: `competition_ranks` when the game is
    `completed`, otherwise `None` for every seat (a stopped game has no final
    ranking, D1/D8)."""
    if status not in TERMINATION_STATUSES:
        raise ResultError(f"unknown termination status {status!r}")
    if status == STATUS_COMPLETED:
        return competition_ranks(scores)
    return (None,) * len(tuple(scores))


def tie_flags(ranks: Sequence[int | None]) -> tuple[bool | None, ...]:
    """For each seat: True when another seat shares its rank, False when it is alone,
    None when there is no rank (a stopped game)."""
    values = tuple(ranks)
    return tuple(None if rank is None else values.count(rank) > 1 for rank in values)


# --- records ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeatResult:
    """One seat of one game.

    seat: the seat index. lineup_index: which lineup entry sat there (it changes
        with seat rotation). agent_config_json: the agent's canonical JSON config.
    score: the engine's raw total (never altered). rank / tied: from `final_ranks` /
        `tie_flags`; both None unless the game completed.
    rounds_won / false_claims: completed rounds this seat ended by a valid win / a
        false claim. timeouts: host-issued timeouts accepted for this seat. agent_faults:
        choices the host refused (D4); counted apart from the timeouts they may cause.
    """

    seat: int
    lineup_index: int
    agent_type: str
    agent_version: str
    agent_config_json: str
    score: int
    rank: int | None
    tied: bool | None
    rounds_won: int = 0
    false_claims: int = 0
    timeouts: int = 0
    agent_faults: int = 0

    def __post_init__(self) -> None:
        _int("seat", self.seat, 0)
        _int("lineup_index", self.lineup_index, 0)
        for name in ("agent_type", "agent_version", "agent_config_json"):
            if not isinstance(getattr(self, name), str):
                raise ResultError(f"{name} must be a string, got {getattr(self, name)!r}")
        _int("score", self.score)
        if (self.rank is None) != (self.tied is None):
            raise ResultError("rank and tied must both be set or both be None")
        if self.rank is not None:
            _int("rank", self.rank, 1)
            if not isinstance(self.tied, bool):
                raise ResultError(f"tied must be a bool, got {self.tied!r}")
        for name in ("rounds_won", "false_claims", "timeouts", "agent_faults"):
            _int(name, getattr(self, name), 0)


@dataclass(frozen=True)
class RoundResult:
    """One completed round (a valid win or a false claim).

    round_index: the completed-round index. attempts: attempts the round took
        (1 plus its draw restarts). reaction_order: the seats that reacted, in the
        order the engine accepted them (empty for a false claim). score_changes: the
        points each seat gained or lost in this round, by seat.
    """

    round_index: int
    outcome: str
    initiator: int
    claimant: int
    attempts: int
    reaction_order: tuple[int, ...]
    score_changes: tuple[int, ...]

    def __post_init__(self) -> None:
        _int("round_index", self.round_index, 0)
        if self.outcome not in ROUND_OUTCOMES:
            raise ResultError(f"unknown round outcome {self.outcome!r}")
        players = len(_int_tuple("score_changes", self.score_changes))
        for name in ("initiator", "claimant"):
            seat = _int(name, getattr(self, name), 0)
            if seat >= players:
                raise ResultError(f"{name} {seat} is not a seat of a {players}-player game")
        _int("attempts", self.attempts, 1)
        order = _int_tuple("reaction_order", self.reaction_order)
        if self.outcome == ROUND_OUTCOME_FALSE_CLAIM:
            if order:
                raise ResultError("a false-claim round has no reactions")
        else:
            expected = set(range(players)) - {self.claimant}
            if len(order) != len(expected) or set(order) != expected:
                raise ResultError(
                    f"reaction_order must list every non-winner exactly once, got {order!r}"
                )

    @property
    def draw_restarts(self) -> int:
        return self.attempts - 1


@dataclass(frozen=True)
class GameResult:
    """One game, completed or stopped.

    status: one of `TERMINATION_STATUSES`. completed_rounds: rounds the engine had
    completed when the game ended (equal to `num_rounds` exactly when completed).
    stopped_attempt: the attempt in progress when a stopped game ended (None when
    completed). draw_restarts: every anti-stall redeal in the game, including the one
    that hit a draw cap. actions: accepted engine actions in the game.
    winning_seats: the seats with rank 1 (several on a tie; empty unless completed).
    """

    game_index: int
    game_seed: int
    status: str
    num_players: int
    num_rounds: int
    completed_rounds: int
    stopped_attempt: int | None
    draw_restarts: int
    actions: int
    seats: tuple[SeatResult, ...]
    rounds: tuple[RoundResult, ...]
    winning_seats: tuple[int, ...]

    def __post_init__(self) -> None:
        _int("game_index", self.game_index, 0)
        _int("game_seed", self.game_seed)
        if self.status not in TERMINATION_STATUSES:
            raise ResultError(f"unknown termination status {self.status!r}")
        players = _int("num_players", self.num_players, 1)
        _int("num_rounds", self.num_rounds, 1)
        _int("completed_rounds", self.completed_rounds, 0)
        _int("draw_restarts", self.draw_restarts, 0)
        _int("actions", self.actions, 0)
        if not isinstance(self.seats, tuple) or not all(isinstance(s, SeatResult) for s in self.seats):
            raise ResultError("seats must be a tuple of SeatResult")
        if not isinstance(self.rounds, tuple) or not all(isinstance(r, RoundResult) for r in self.rounds):
            raise ResultError("rounds must be a tuple of RoundResult")
        winners = _int_tuple("winning_seats", self.winning_seats)

        if tuple(s.seat for s in self.seats) != tuple(range(players)):
            raise ResultError(f"seats must be seats 0..{players - 1} in order")
        if sorted(s.lineup_index for s in self.seats) != list(range(players)):
            raise ResultError("lineup_index must use every lineup entry exactly once")
        if len(self.rounds) != self.completed_rounds:
            raise ResultError("there must be one round record per completed round")
        for index, record in enumerate(self.rounds):
            if record.round_index != index or len(record.score_changes) != players:
                raise ResultError(f"round record {index} does not fit this game")

        # Scores change only when a round closes, so they reconcile with the rounds.
        for seat in self.seats:
            if seat.score != sum(r.score_changes[seat.seat] for r in self.rounds):
                raise ResultError(f"score of seat {seat.seat} does not match its rounds")
            if seat.rounds_won != sum(
                r.outcome == ROUND_OUTCOME_VALID_WIN and r.claimant == seat.seat for r in self.rounds
            ) or seat.false_claims != sum(
                r.outcome == ROUND_OUTCOME_FALSE_CLAIM and r.claimant == seat.seat for r in self.rounds
            ):
                raise ResultError(f"win/false-claim counts of seat {seat.seat} do not match its rounds")

        if self.status == STATUS_COMPLETED:
            if self.completed_rounds != self.num_rounds or self.stopped_attempt is not None:
                raise ResultError("a completed game has all its rounds and no stopped attempt")
            ranks = competition_ranks([s.score for s in self.seats])
            if tuple(s.rank for s in self.seats) != ranks:
                raise ResultError("ranks must be the shared competition ranks of the scores")
            if tuple(s.tied for s in self.seats) != tie_flags(ranks):
                raise ResultError("tie flags must match the ranks")
            if winners != tuple(s.seat for s in self.seats if s.rank == 1):
                raise ResultError("winning_seats must be the seats ranked 1")
            extra = 0
        else:
            if self.completed_rounds >= self.num_rounds:
                raise ResultError("a stopped game has fewer completed rounds than configured")
            attempt = _int("stopped_attempt", self.stopped_attempt, 1)
            if any(s.rank is not None or s.tied is not None for s in self.seats) or winners:
                raise ResultError("a game that did not complete carries no ranks, ties or winners")
            extra = attempt - 1
        if self.draw_restarts != sum(r.draw_restarts for r in self.rounds) + extra:
            raise ResultError("draw_restarts does not match the round attempts")

    @property
    def completed(self) -> bool:
        return self.status == STATUS_COMPLETED

    @property
    def tie_for_first(self) -> bool | None:
        """True when several seats share rank 1; None if the game did not complete."""
        return len(self.winning_seats) > 1 if self.completed else None


__all__ = [
    "ROUND_OUTCOMES",
    "STATUS_ACTION_CAP_REACHED",
    "STATUS_AGENT_FAULT_UNRESOLVABLE",
    "STATUS_COMPLETED",
    "STATUS_DRAW_CAP_REACHED",
    "STOPPED_STATUSES",
    "TERMINATION_STATUSES",
    "GameResult",
    "ResultError",
    "RoundResult",
    "SeatResult",
    "competition_ranks",
    "final_ranks",
    "tie_flags",
]
