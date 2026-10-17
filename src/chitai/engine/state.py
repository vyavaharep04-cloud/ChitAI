"""Authoritative game state (§3A.1, §5A). Milestone 2: the initial claim phase.

`GameState` is immutable. The engine produces a new state for every accepted
action and leaves the old one untouched, so a rejected action cannot change
anything. Hands are indexed by seat.

Milestone 2 stopping points
---------------------------
`WIN_DECLARED` (a valid claim fixed the winner; reactions and scoring are M5)
and `FALSE_CLAIM` (an eligible claim failed matching; the penalty and round
completion are M4) are *holding* phases. In M2 no scores are applied and
`completed_rounds` is not incremented in either of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .chits import Chit
from .config import GameConfig


class Phase(Enum):
    INITIAL_CLAIMS = "initial_claims"  # §3A.3: one claim opportunity per seat
    PASSING = "passing"  # ordinary passing begins; the pass cycle itself is M3
    WIN_DECLARED = "win_declared"  # holding phase until M5
    FALSE_CLAIM = "false_claim"  # holding phase until M4


class DecisionKind(Enum):
    """Kinds of decision point reachable so far (§5A). M3 adds the receive/return kinds."""

    INITIAL_CLAIM = "initial_claim"
    INITIATOR_FIRST_PASS = "initiator_first_pass"


@dataclass(frozen=True)
class GameState:
    """One resting state of the authoritative engine.

    completed_rounds: number of completed rounds so far (== index of the round
        being played; same meaning as `deal_round`'s `completed_round`).
    attempt: shuffle-and-deal number within the round, from 1. Tracked
        separately from completed_rounds (§3A.1).
    decision_seat / decision_kind: the single decision point, or None when the
        engine is not waiting for any player.
    initial_claims_resolved: how many seats' initial opportunities are
        resolved (a claim counts as resolving its own opportunity).
    scores: per-seat totals. Not modified in M2.
    winner / false_claimant: set only in WIN_DECLARED / FALSE_CLAIM.
    next_seq: sequence number of the next event (single authoritative order).
    """

    config: GameConfig
    completed_rounds: int
    attempt: int
    initiator: int
    phase: Phase
    decision_seat: int | None
    decision_kind: DecisionKind | None
    hands: tuple[tuple[Chit, ...], ...]
    initial_claims_resolved: int
    scores: tuple[int, ...]
    winner: int | None
    false_claimant: int | None
    next_seq: int
