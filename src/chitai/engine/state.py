"""Authoritative game state (§3A.1, §5A). M2: initial claim phase. M3: passing.
M4: false-claim round completion, multi-round progression, terminal state.
M5: valid-win reactions and scoring. M6: anti-stall streaks (`pass_streaks`).

`GameState` is immutable. The engine produces a new state for every accepted
action and leaves the old one untouched, so a rejected action cannot change
anything. Hands are indexed by seat.

Milestone 2 stopping points
---------------------------
`WIN_DECLARED` (a valid claim fixed the winner; reactions and scoring are M5)
and `FALSE_CLAIM` (an eligible claim failed matching; the penalty and round
completion are M4) are *holding* phases. Through M3 no scores are applied and
`completed_rounds` is not incremented in either of them. A claim made during
ordinary passing (M3) ends in the same holding phases as an initial claim.

Milestone 4 changes
-------------------
A false claim now completes the round inside the same `apply_action` call: the
penalty is applied, `completed_rounds` increases by one, and the engine either
deals the next round (`INITIAL_CLAIMS`, attempt 1, rotated initiator, scores
carried over) or, after the last configured round, returns `GAME_OVER`.
`FALSE_CLAIM` is therefore a *transient* phase: the engine builds and validates
it internally but never returns it, so callers never see it. It stays in the
enum so the claim-consistency invariants keep a state to check. `WIN_DECLARED`
is still a holding phase (valid-win scoring and completion are M5).

`GAME_OVER` has `completed_rounds == config.num_rounds`, attempt 1, no decision
point and no outcome fields. It keeps the hands of the final claim (the board
as it ended), so chit conservation still holds. Its `initiator` is the rotation
value `completed_rounds % num_players`, which is seat 0 because the round count
is a multiple of N.

Milestone 5 changes
-------------------
`WIN_DECLARED` is now the *reaction* phase rather than a holding phase: the
winner is fixed, there is no single decision point (every non-winner who has not
yet reacted may react), and `reaction_order` lists the seats that have reacted,
in the engine's accepted-action order. Scores and `completed_rounds` are
unchanged while reactions are pending. The reaction that makes `reaction_order`
complete (N-1 seats) completes the round inside the same `apply_action` call,
exactly like a false claim in M4: win scores are applied once, `completed_rounds`
rises by one, and the engine deals the next round or returns `GAME_OVER`. A
`WIN_DECLARED` state with all N-1 reactions is transient and never returned.

Hand sizes (§3A.4): chit delivery is atomic, so no chit is ever "in transit"
between states. While the initiator's chit is being passed around, the
initiator holds three chits and the current non-initiator receiver holds five.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .chits import Chit
from .config import GameConfig


class Phase(Enum):
    INITIAL_CLAIMS = "initial_claims"  # §3A.3: one claim opportunity per seat
    PASSING = "passing"  # ordinary sequential passing (M3)
    WIN_DECLARED = "win_declared"  # M5: winner fixed; non-winners react (reaction phase)
    FALSE_CLAIM = "false_claim"  # transient since M4: validated internally, never returned by the engine
    GAME_OVER = "game_over"  # M4: terminal; every configured round is complete


class DecisionKind(Enum):
    """Kinds of decision point (§5A, §3A.4 table)."""

    INITIAL_CLAIM = "initial_claim"
    INITIATOR_FIRST_PASS = "initiator_first_pass"  # initiator holds 4; no claim opportunity
    NON_INITIATOR_RECEIVE = "non_initiator_receive"  # receiver holds 5, initiator 3; may claim
    INITIATOR_RETURN = "initiator_return"  # chit returned, initiator holds 4; may claim


# Decision kinds at which an eligible player may claim (§3A.4).
CLAIM_KINDS = frozenset(
    {
        DecisionKind.INITIAL_CLAIM,
        DecisionKind.NON_INITIATOR_RECEIVE,
        DecisionKind.INITIATOR_RETURN,
    }
)


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
    scores: per-seat totals. Changed only when a round completes: by a
        false-claim penalty (M4) or by valid-win scoring (M5).
    winner / false_claimant: set only in WIN_DECLARED / FALSE_CLAIM.
    next_seq: sequence number of the next event (single authoritative order).
    claim_decision_kind: the decision kind at which the claim was made; set
        only in WIN_DECLARED / FALSE_CLAIM. It tells the invariant checker
        which hand shape and matching rule apply to the claimant (M3).
    reaction_order: seats that have reacted to the win, in accepted-action
        order (M5). Non-empty only in WIN_DECLARED; never contains the winner
        or a repeated seat.
    pass_streaks: anti-stall tracking (M6, §3A.6). Sparse, sorted by seat:
        `(seat, chit_name, count)` means that seat's most recent `count`
        passes (1..9) all used `chit_name`. Seats that have not passed in this
        attempt have no entry. Names, not physical copies, are tracked. A
        tenth consecutive pass never rests in state: it ends the attempt as a
        draw. Reset (empty) by every new deal and at `GAME_OVER`.
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
    claim_decision_kind: DecisionKind | None = None
    reaction_order: tuple[int, ...] = ()
    pass_streaks: tuple[tuple[int, str, int], ...] = ()
