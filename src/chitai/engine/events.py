"""Sequenced engine events with separate public and debug views (§5A, §4, §6, §3A.8).
M4 adds FalseClaimPenalized, RoundCompleted and GameCompleted; the next round's
start is an ordinary DealEvent. M5 adds PlayerReacted and ValidWinScored and a
"valid_win" RoundCompleted outcome.

Every event carries a `seq` from the single authoritative sequence, plus the
completed-round index and attempt number (§6).

* `public_view()` is what any participant may see. It never contains chit
  identities. It states *that* a claim was valid or false but does not reveal
  the claimant's hand (whether a hand is revealed at round end is open
  question 6, decided at M7).
* `debug_view()` is the full private record, for the private debugging log
  only. It must never be passed to an agent or a client.

Both views are JSON-serializable dicts. Per-player observation views (a player
seeing their own hand) belong to M7 and are not provided here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from .chits import Chit


def _chit_json(chit: Chit) -> dict[str, Any]:
    return {"name": chit.name, "copy": chit.copy}


@dataclass(frozen=True)
class Event:
    seq: int
    completed_round: int
    attempt: int

    type: ClassVar[str] = "event"

    def _base(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "seq": self.seq,
            "completed_round": self.completed_round,
            "attempt": self.attempt,
        }

    def public_view(self) -> dict[str, Any]:
        return self._base()

    def debug_view(self) -> dict[str, Any]:
        return self.public_view()


@dataclass(frozen=True)
class DealEvent(Event):
    """A shuffle-and-deal. Public: initiator and player count. Hands are private."""

    initiator: int
    hands: tuple[tuple[Chit, ...], ...]

    type: ClassVar[str] = "deal"

    def public_view(self) -> dict[str, Any]:
        return {**self._base(), "initiator": self.initiator, "num_players": len(self.hands)}

    def debug_view(self) -> dict[str, Any]:
        return {
            **self.public_view(),
            "hands": [[_chit_json(c) for c in hand] for hand in self.hands],
        }


@dataclass(frozen=True)
class InitialClaimDeclined(Event):
    seat: int

    type: ClassVar[str] = "initial_claim_declined"

    def public_view(self) -> dict[str, Any]:
        return {**self._base(), "seat": self.seat}


@dataclass(frozen=True)
class InitialClaimMade(Event):
    """An eligible initial claim. `valid` False means a false claim (§3A.5)."""

    seat: int
    valid: bool
    hand: tuple[Chit, ...]

    type: ClassVar[str] = "initial_claim_made"

    def public_view(self) -> dict[str, Any]:
        return {**self._base(), "seat": self.seat, "valid": self.valid}

    def debug_view(self) -> dict[str, Any]:
        return {**self.public_view(), "hand": [_chit_json(c) for c in self.hand]}


@dataclass(frozen=True)
class InitialClaimsResolved(Event):
    """Every initial opportunity ended without a valid claim; passing begins."""

    initiator: int

    type: ClassVar[str] = "initial_claims_resolved"

    def public_view(self) -> dict[str, Any]:
        return {**self._base(), "initiator": self.initiator}


@dataclass(frozen=True)
class ChitPassed(Event):
    """One atomic chit delivery (§3A.4). Public: sender and receiver only; the
    chit's identity is known only to those two players (§3A.8), so it appears
    only in the private debug view."""

    from_seat: int
    to_seat: int
    chit: Chit

    type: ClassVar[str] = "chit_passed"

    def public_view(self) -> dict[str, Any]:
        return {**self._base(), "from_seat": self.from_seat, "to_seat": self.to_seat}

    def debug_view(self) -> dict[str, Any]:
        return {**self.public_view(), "chit": _chit_json(self.chit)}


@dataclass(frozen=True)
class ClaimMade(Event):
    """An eligible claim during ordinary passing. `valid` False means a false
    claim (§3A.5). Public view states validity but not the hand (§9 question 9)."""

    seat: int
    valid: bool
    hand: tuple[Chit, ...]

    type: ClassVar[str] = "claim_made"

    def public_view(self) -> dict[str, Any]:
        return {**self._base(), "seat": self.seat, "valid": self.valid}

    def debug_view(self) -> dict[str, Any]:
        return {**self.public_view(), "hand": [_chit_json(c) for c in self.hand]}


ROUND_OUTCOME_FALSE_CLAIM = "false_claim"
ROUND_OUTCOME_VALID_WIN = "valid_win"


@dataclass(frozen=True)
class FalseClaimPenalized(Event):
    """The score effect of a false claim (§3A.5). Scores are public information;
    no chit identity appears. `completed_round` is the round being penalized.

    seat: the false claimant. penalty: points deducted, N-1 (positive).
    score_changes: per-seat change this round. scores: per-seat totals after.
    """

    seat: int
    penalty: int
    score_changes: tuple[int, ...]
    scores: tuple[int, ...]

    type: ClassVar[str] = "false_claim_penalized"

    def public_view(self) -> dict[str, Any]:
        return {
            **self._base(),
            "seat": self.seat,
            "penalty": self.penalty,
            "score_changes": list(self.score_changes),
            "scores": list(self.scores),
        }


@dataclass(frozen=True)
class PlayerReacted(Event):
    """A non-winner reacted to a valid win (M5). `position` is the 1-based place
    in the authoritative reaction order (the accepted-action order); it is
    public, since reactions are public. No chit identity appears.

    winner: the seat that won the round.
    """

    seat: int
    position: int
    winner: int

    type: ClassVar[str] = "player_reacted"

    def public_view(self) -> dict[str, Any]:
        return {
            **self._base(),
            "seat": self.seat,
            "position": self.position,
            "winner": self.winner,
        }


@dataclass(frozen=True)
class ValidWinScored(Event):
    """The score effect of a valid win, emitted exactly once per won round (M5).
    `completed_round` is the round being scored.

    winner: the winning seat (scores N). reaction_order: the non-winners in
    authoritative reaction order (first scores N-1, ..., last scores 1).
    score_changes: per-seat change this round. scores: per-seat totals after.
    """

    winner: int
    reaction_order: tuple[int, ...]
    score_changes: tuple[int, ...]
    scores: tuple[int, ...]

    type: ClassVar[str] = "valid_win_scored"

    def public_view(self) -> dict[str, Any]:
        return {
            **self._base(),
            "winner": self.winner,
            "reaction_order": list(self.reaction_order),
            "score_changes": list(self.score_changes),
            "scores": list(self.scores),
        }


@dataclass(frozen=True)
class RoundCompleted(Event):
    """A round ended and counted toward the configured total (§3A.6).
    `completed_round` is the index of the round that just ended;
    `rounds_completed` is the running total after it. `claimant` is the seat
    whose claim ended the round: the false claimant for outcome "false_claim"
    and the winner for outcome "valid_win"."""

    outcome: str
    claimant: int
    rounds_completed: int

    type: ClassVar[str] = "round_completed"

    def public_view(self) -> dict[str, Any]:
        return {
            **self._base(),
            "outcome": self.outcome,
            "claimant": self.claimant,
            "rounds_completed": self.rounds_completed,
        }


@dataclass(frozen=True)
class GameCompleted(Event):
    """Every configured round is complete; no further action is accepted.
    `completed_round` equals the configured round count and `attempt` is 1."""

    rounds_completed: int
    final_scores: tuple[int, ...]

    type: ClassVar[str] = "game_completed"

    def public_view(self) -> dict[str, Any]:
        return {
            **self._base(),
            "rounds_completed": self.rounds_completed,
            "final_scores": list(self.final_scores),
        }
