"""The single authoritative engine (§5A). M2: initial claim phase. M3: sequential passing.
M4: false-claim round completion and multi-round progression.

`apply_action` validates every request itself; the caller (UI, agent,
simulator) is never trusted. A rejected action returns `Rejected` and the
previous state is untouched. Accepted actions return the new state and the
sequenced events. No random choices occur through M4: next-round deals are a
pure function of (master seed, completed-round index, attempt), so nothing
stateful is consumed (timeouts are M6).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .actions import Action, ClaimAction, DeclineAction, PassAction
from .chits import Chit
from .config import GameConfig
from .deal import FIRST_ATTEMPT, Deal, deal_round, rotation_initiator
from .events import (
    ChitPassed,
    ClaimMade,
    ROUND_OUTCOME_FALSE_CLAIM,
    DealEvent,
    Event,
    FalseClaimPenalized,
    GameCompleted,
    InitialClaimDeclined,
    InitialClaimMade,
    InitialClaimsResolved,
    RoundCompleted,
)
from .invariants import check_invariants
from .rules import (
    initial_claim_order,
    is_valid_claim,
    is_valid_initial_claim,
    is_valid_seat,
    next_seat,
)
from .scoring import false_claim_penalty, false_claim_score_changes
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
    """Begin an attempt from a given `Deal` with zero scores and sequence 0.

    This is how round 0, a crafted deal, or a game resumed at a later round is
    started. Rounds after a false claim are started by the engine itself and
    carry scores and the event sequence forward. Raises `InvariantViolation` if
    the deal is inconsistent with the config (wrong initiator, bad deck, wrong
    hand sizes).
    """
    if not isinstance(deal, Deal):
        raise TypeError(f"deal must be a Deal, got {type(deal).__name__}")
    state, event = _start_round(config, deal, (0,) * config.num_players, 0)
    return Accepted(state, (event,))


def _start_round(
    config: GameConfig, deal: Deal, scores: tuple[int, ...], seq: int
) -> tuple[GameState, DealEvent]:
    """The state at the start of an attempt, plus its `DealEvent` numbered `seq`."""
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
        scores=scores,
        winner=None,
        false_claimant=None,
        next_seq=seq + 1,
    )
    check_invariants(state)
    event = DealEvent(
        seq=seq,
        completed_round=deal.completed_round,
        attempt=deal.attempt,
        initiator=deal.initiator,
        hands=deal.hands,
    )
    return state, event


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
        what = "the game is over" if state.phase is Phase.GAME_OVER else f"phase {state.phase.value}"
        return Rejected(
            RejectionReason.PHASE_NOT_ACCEPTING,
            f"no action is accepted: {what}",
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
    """A claim at a receive or return opportunity. A valid claim ends in the
    WIN_DECLARED holding phase (M5 resolves it, §9 question 8); a false claim
    completes the round (M4)."""
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
    if not valid:
        return _complete_false_claim(new_state, (event,))
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
    if not valid:
        return _complete_false_claim(new_state, (event,))
    return Accepted(new_state, (event,))


def _complete_false_claim(claim_state: GameState, events: tuple[Event, ...]) -> Accepted:
    """Finish a round that ended in a false claim (§3A.5, §3A.6).

    `claim_state` is the transient, already-validated FALSE_CLAIM state and
    `events` holds the claim event just produced. The claimant loses N-1
    points, every other seat scores 0, `completed_rounds` rises by exactly one,
    and the engine then either deals the next round or ends the game. Scores
    are carried over; attempt numbering restarts at 1; the next round's deal
    depends only on (master seed, completed-round index, attempt 1).
    """
    config = claim_state.config
    n = config.num_players
    claimant = claim_state.false_claimant
    round_index, attempt = claim_state.completed_rounds, claim_state.attempt
    rounds_completed = round_index + 1

    changes = false_claim_score_changes(n, claimant)
    scores = tuple(total + change for total, change in zip(claim_state.scores, changes))
    seq = claim_state.next_seq
    out: list[Event] = list(events)
    out.append(
        FalseClaimPenalized(
            seq=seq,
            completed_round=round_index,
            attempt=attempt,
            seat=claimant,
            penalty=false_claim_penalty(n),
            score_changes=changes,
            scores=scores,
        )
    )
    out.append(
        RoundCompleted(
            seq=seq + 1,
            completed_round=round_index,
            attempt=attempt,
            outcome=ROUND_OUTCOME_FALSE_CLAIM,
            claimant=claimant,
            rounds_completed=rounds_completed,
        )
    )
    seq += 2

    if rounds_completed < config.num_rounds:
        new_state, deal_event = _start_round(
            config, deal_round(config, rounds_completed, FIRST_ATTEMPT), scores, seq
        )
        out.append(deal_event)
    else:
        new_state = replace(
            claim_state,
            completed_rounds=rounds_completed,
            attempt=FIRST_ATTEMPT,
            initiator=rotation_initiator(n, rounds_completed),
            phase=Phase.GAME_OVER,
            initial_claims_resolved=0,
            scores=scores,
            winner=None,
            false_claimant=None,
            claim_decision_kind=None,
            next_seq=seq + 1,
        )
        check_invariants(new_state)
        out.append(
            GameCompleted(
                seq=seq,
                completed_round=rounds_completed,
                attempt=FIRST_ATTEMPT,
                rounds_completed=rounds_completed,
                final_scores=scores,
            )
        )
    return Accepted(new_state, tuple(out))


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
