"""The single authoritative engine (§5A). Milestone 2: the initial claim phase.

`apply_action` validates every request itself; the caller (UI, agent,
simulator) is never trusted. A rejected action returns `Rejected` and the
previous state is untouched. Accepted actions return the new state and the
sequenced events. Random choices do not occur in M2.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .actions import Action, ClaimAction, DeclineAction
from .config import GameConfig
from .deal import FIRST_ATTEMPT, Deal, deal_round
from .events import (
    DealEvent,
    Event,
    InitialClaimDeclined,
    InitialClaimMade,
    InitialClaimsResolved,
)
from .invariants import check_invariants
from .rules import initial_claim_order, is_valid_initial_claim, is_valid_seat
from .state import DecisionKind, GameState, Phase


class RejectionReason(Enum):
    UNKNOWN_ACTION = "unknown_action"  # not a recognized action object
    INVALID_SEAT = "invalid_seat"  # seat is not an integer in [0, N)
    PHASE_NOT_ACCEPTING = "phase_not_accepting"  # engine accepts no actions in this phase yet
    NOT_DECISION_POINT = "not_decision_point"  # ineligible: it is not this seat's opportunity


@dataclass(frozen=True)
class Accepted:
    state: GameState
    events: tuple[Event, ...]


@dataclass(frozen=True)
class Rejected:
    """The action was refused. No state, score, or sequence number changed and
    no penalty is applied (§3A.5)."""

    reason: RejectionReason
    message: str


def new_game(config: GameConfig) -> Accepted:
    """Start round 0, attempt 1 with the seeded deal for `config`."""
    return start_from_deal(config, deal_round(config, 0, FIRST_ATTEMPT))


def start_from_deal(config: GameConfig, deal: Deal) -> Accepted:
    """Begin an attempt from a given `Deal`.

    M2 does not carry state between rounds (scores are zero; round
    progression is M4), so this is also how a later round's initial phase, or
    a hand-crafted deal, is started. Raises `InvariantViolation` if the deal is
    inconsistent with the config (wrong initiator, bad deck, wrong hand sizes).
    """
    if not isinstance(deal, Deal):
        raise TypeError(f"deal must be a Deal, got {type(deal).__name__}")
    n = config.num_players
    state = GameState(
        config=config,
        completed_rounds=deal.completed_round,
        attempt=deal.attempt,
        initiator=deal.initiator,
        phase=Phase.INITIAL_CLAIMS,
        decision_seat=deal.initiator,
        decision_kind=DecisionKind.INITIAL_CLAIM,
        hands=deal.hands,
        initial_claims_resolved=0,
        scores=(0,) * n,
        winner=None,
        false_claimant=None,
        next_seq=1,
    )
    check_invariants(state)
    event = DealEvent(
        seq=0,
        completed_round=deal.completed_round,
        attempt=deal.attempt,
        initiator=deal.initiator,
        hands=deal.hands,
    )
    return Accepted(state, (event,))


def apply_action(state: GameState, action: object) -> Accepted | Rejected:
    """Validate and apply one action. Check order: recognized action, valid
    seat, phase accepts actions, seat is the current decision point."""
    if not isinstance(state, GameState):
        raise TypeError(f"state must be a GameState, got {type(state).__name__}")

    if not isinstance(action, (ClaimAction, DeclineAction)):
        return Rejected(RejectionReason.UNKNOWN_ACTION, f"unrecognized action {action!r}")
    if not is_valid_seat(state.config, action.seat):
        return Rejected(RejectionReason.INVALID_SEAT, f"invalid seat {action.seat!r}")
    if state.phase is not Phase.INITIAL_CLAIMS:
        return Rejected(
            RejectionReason.PHASE_NOT_ACCEPTING,
            f"no claim opportunity exists in phase {state.phase.value}",
        )
    if action.seat != state.decision_seat:
        return Rejected(
            RejectionReason.NOT_DECISION_POINT,
            f"seat {action.seat} has no claim opportunity now (waiting for seat {state.decision_seat})",
        )

    if isinstance(action, ClaimAction):
        return _apply_initial_claim(state, action.seat)
    return _apply_initial_decline(state, action.seat)


def _apply_initial_claim(state: GameState, seat: int) -> Accepted:
    hand = state.hands[seat]
    valid = is_valid_initial_claim(hand)
    event = InitialClaimMade(
        seq=state.next_seq,
        completed_round=state.completed_rounds,
        attempt=state.attempt,
        seat=seat,
        valid=valid,
        hand=hand,
    )
    new_state = replace(
        state,
        phase=Phase.WIN_DECLARED if valid else Phase.FALSE_CLAIM,
        decision_seat=None,
        decision_kind=None,
        initial_claims_resolved=state.initial_claims_resolved + 1,
        winner=seat if valid else None,
        false_claimant=None if valid else seat,
        next_seq=state.next_seq + 1,
    )
    check_invariants(new_state)
    return Accepted(new_state, (event,))


def _apply_initial_decline(state: GameState, seat: int) -> Accepted:
    n = state.config.num_players
    resolved = state.initial_claims_resolved + 1
    events: list[Event] = [
        InitialClaimDeclined(
            seq=state.next_seq,
            completed_round=state.completed_rounds,
            attempt=state.attempt,
            seat=seat,
        )
    ]
    if resolved < n:
        new_state = replace(
            state,
            decision_seat=initial_claim_order(n, state.initiator)[resolved],
            initial_claims_resolved=resolved,
        )
    else:
        # Every opportunity ended without a valid claim: ordinary passing
        # begins and the initiator makes the first pass (no further claim).
        events.append(
            InitialClaimsResolved(
                seq=state.next_seq + 1,
                completed_round=state.completed_rounds,
                attempt=state.attempt,
                initiator=state.initiator,
            )
        )
        new_state = replace(
            state,
            phase=Phase.PASSING,
            decision_seat=state.initiator,
            decision_kind=DecisionKind.INITIATOR_FIRST_PASS,
            initial_claims_resolved=resolved,
        )
    new_state = replace(new_state, next_seq=state.next_seq + len(events))
    check_invariants(new_state)
    return Accepted(new_state, tuple(events))
