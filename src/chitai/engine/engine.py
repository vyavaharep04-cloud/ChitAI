"""The single authoritative engine (§5A). M2: initial claim phase. M3: sequential passing.

`apply_action` validates every request itself; the caller (UI, agent,
simulator) is never trusted. A rejected action returns `Rejected` and the
previous state is untouched. Accepted actions return the new state and the
sequenced events. No random choices occur through M3 (timeouts are M6).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .actions import Action, ClaimAction, DeclineAction, PassAction
from .chits import Chit
from .config import GameConfig
from .deal import FIRST_ATTEMPT, Deal, deal_round
from .events import (
    ChitPassed,
    ClaimMade,
    DealEvent,
    Event,
    InitialClaimDeclined,
    InitialClaimMade,
    InitialClaimsResolved,
)
from .invariants import check_invariants
from .rules import (
    initial_claim_order,
    is_valid_claim,
    is_valid_initial_claim,
    is_valid_seat,
    next_seat,
)
from .state import CLAIM_KINDS, DecisionKind, GameState, Phase


class RejectionReason(Enum):
    UNKNOWN_ACTION = "unknown_action"  # not a recognized action object
    INVALID_SEAT = "invalid_seat"  # seat is not an integer in [0, N)
    PHASE_NOT_ACCEPTING = "phase_not_accepting"  # engine accepts no actions in this phase yet
    NOT_DECISION_POINT = "not_decision_point"  # ineligible: it is not this seat's opportunity
    ACTION_NOT_AVAILABLE = "action_not_available"  # right seat, but this action kind does not exist here
    NO_CLAIM_OPPORTUNITY = "no_claim_opportunity"  # claim while holding no claim opportunity (e.g. first pass)
    CHIT_NOT_HELD = "chit_not_held"  # pass of a chit the seat does not hold


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
    seat, phase accepts actions, seat is the current decision point, then the
    checks specific to the action kind. Every rejection leaves state and
    scores untouched and applies no penalty (§3A.5)."""
    if not isinstance(state, GameState):
        raise TypeError(f"state must be a GameState, got {type(state).__name__}")

    if not isinstance(action, (ClaimAction, DeclineAction, PassAction)):
        return Rejected(RejectionReason.UNKNOWN_ACTION, f"unrecognized action {action!r}")
    if not is_valid_seat(state.config, action.seat):
        return Rejected(RejectionReason.INVALID_SEAT, f"invalid seat {action.seat!r}")
    if state.phase not in (Phase.INITIAL_CLAIMS, Phase.PASSING):
        return Rejected(
            RejectionReason.PHASE_NOT_ACCEPTING,
            f"no action is accepted in phase {state.phase.value}",
        )
    if action.seat != state.decision_seat:
        what = "pass" if isinstance(action, PassAction) else "claim opportunity"
        return Rejected(
            RejectionReason.NOT_DECISION_POINT,
            f"seat {action.seat} has no {what} now (waiting for seat {state.decision_seat})",
        )

    if state.phase is Phase.INITIAL_CLAIMS:
        if isinstance(action, PassAction):
            return Rejected(
                RejectionReason.ACTION_NOT_AVAILABLE,
                "passing begins only after every initial claim opportunity is resolved",
            )
        if isinstance(action, ClaimAction):
            return _apply_initial_claim(state, action.seat)
        return _apply_initial_decline(state, action.seat)

    # Phase.PASSING
    if isinstance(action, DeclineAction):
        return Rejected(
            RejectionReason.ACTION_NOT_AVAILABLE,
            "declining exists only in the initial claim phase; during passing, passing forfeits the opportunity",
        )
    if isinstance(action, ClaimAction):
        if state.decision_kind not in CLAIM_KINDS:
            return Rejected(
                RejectionReason.NO_CLAIM_OPPORTUNITY,
                f"seat {action.seat} has no claim opportunity at {state.decision_kind.value}",
            )
        return _apply_ordinary_claim(state, action.seat)
    if not isinstance(action.chit, Chit) or action.chit not in state.hands[action.seat]:
        return Rejected(
            RejectionReason.CHIT_NOT_HELD,
            f"seat {action.seat} does not hold {action.chit!r}",
        )
    return _apply_pass(state, action.seat, action.chit)


def _apply_pass(state: GameState, seat: int, chit: Chit) -> Accepted:
    """Atomic delivery: the chit leaves `seat`'s hand and enters the next
    seat's hand in one step (§3A.4). If the receiver is the initiator the chit
    has returned and the initiator holds four again."""
    n = state.config.num_players
    receiver = next_seat(n, seat)
    hands = list(state.hands)
    hands[seat] = tuple(c for c in state.hands[seat] if c != chit)
    hands[receiver] = state.hands[receiver] + (chit,)
    kind = (
        DecisionKind.INITIATOR_RETURN
        if receiver == state.initiator
        else DecisionKind.NON_INITIATOR_RECEIVE
    )
    event = ChitPassed(
        seq=state.next_seq,
        completed_round=state.completed_rounds,
        attempt=state.attempt,
        from_seat=seat,
        to_seat=receiver,
        chit=chit,
    )
    new_state = replace(
        state,
        hands=tuple(hands),
        decision_seat=receiver,
        decision_kind=kind,
        next_seq=state.next_seq + 1,
    )
    check_invariants(new_state)
    return Accepted(new_state, (event,))


def _apply_ordinary_claim(state: GameState, seat: int) -> Accepted:
    """A claim at a receive or return opportunity. Valid claims and false claims
    end in the same M2 holding phases as initial claims (§9 question 8)."""
    hand = state.hands[seat]
    valid = is_valid_claim(state.decision_kind, hand)
    event = ClaimMade(
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
        winner=seat if valid else None,
        false_claimant=None if valid else seat,
        claim_decision_kind=state.decision_kind,
        next_seq=state.next_seq + 1,
    )
    check_invariants(new_state)
    return Accepted(new_state, (event,))


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
        claim_decision_kind=DecisionKind.INITIAL_CLAIM,
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
