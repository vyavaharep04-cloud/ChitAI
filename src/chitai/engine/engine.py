"""The single authoritative engine (§5A). M2: initial claim phase. M3: sequential passing.
M4: false-claim round completion and multi-round progression. M5: valid-win
reactions, scoring and round completion. M6: host-issued timeouts and
anti-stall draws.

`apply_action` validates every request itself; the caller (UI, agent,
simulator) is never trusted. A rejected action returns `Rejected` and the
previous state is untouched. Accepted actions return the new state and the
sequenced events. Randomness is never stateful: deals are a pure function of
(master seed, completed-round index, attempt) and a forced pass is a pure
function of (master seed, round, attempt, next sequence number) on a separate
"timeout" stream, so a rejected action consumes nothing and a timeout cannot
change any later deal. There is no clock: a timeout is an action the host
issues when its own timer expires (`TimeoutAction`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .actions import Action, ClaimAction, DeclineAction, PassAction, ReactAction, TimeoutAction
from .chits import Chit
from .config import GameConfig
from .deal import FIRST_ATTEMPT, Deal, deal_round, rotation_initiator
from .events import (
    TIMEOUT_KIND_FINAL_REACTION,
    AttemptDrawn,
    ChitPassed,
    ClaimMade,
    ROUND_OUTCOME_FALSE_CLAIM,
    ROUND_OUTCOME_VALID_WIN,
    DealEvent,
    DecisionTimedOut,
    Event,
    FalseClaimPenalized,
    GameCompleted,
    InitialClaimDeclined,
    InitialClaimMade,
    InitialClaimsResolved,
    PlayerReacted,
    RoundCompleted,
    ValidWinScored,
)
from .invariants import InvariantViolation, check_invariants
from .rng import TIMEOUT, make_rng
from .rules import (
    CONSECUTIVE_PASS_LIMIT,
    initial_claim_order,
    is_valid_claim,
    is_valid_initial_claim,
    is_valid_seat,
    next_seat,
    pending_reactors,
    update_pass_streaks,
)
from .scoring import false_claim_penalty, false_claim_score_changes, valid_win_score_changes
from .state import CLAIM_KINDS, DecisionKind, GameState, Phase


class RejectionReason(Enum):
    UNKNOWN_ACTION = "unknown_action"  # not a recognized action object
    INVALID_SEAT = "invalid_seat"  # seat is not an integer in [0, N)
    PHASE_NOT_ACCEPTING = "phase_not_accepting"  # engine accepts no actions in this phase yet
    NOT_DECISION_POINT = "not_decision_point"  # ineligible: it is not this seat's opportunity
    ACTION_NOT_AVAILABLE = "action_not_available"  # right seat, but this action kind does not exist here
    NO_CLAIM_OPPORTUNITY = "no_claim_opportunity"  # claim while holding no claim opportunity (e.g. first pass)
    CHIT_NOT_HELD = "chit_not_held"  # pass of a chit the seat does not hold
    WINNER_CANNOT_REACT = "winner_cannot_react"  # M5: the winner never reacts to its own win
    ALREADY_REACTED = "already_reacted"  # M5: each non-winner reacts at most once
    TIMEOUT_NOT_AVAILABLE = "timeout_not_available"  # M6: no timeout exists here (e.g. several reactors pending)


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

    if not isinstance(action, (ClaimAction, DeclineAction, PassAction, ReactAction, TimeoutAction)):
        return Rejected(RejectionReason.UNKNOWN_ACTION, f"unrecognized action {action!r}")
    if not is_valid_seat(state.config, action.seat):
        return Rejected(RejectionReason.INVALID_SEAT, f"invalid seat {action.seat!r}")
    if isinstance(action, ReactAction):
        return _apply_react(state, action.seat)
    if isinstance(action, TimeoutAction):
        return _apply_timeout(state, action.seat)
    if state.phase not in (Phase.INITIAL_CLAIMS, Phase.PASSING):
        if state.phase is Phase.GAME_OVER:
            what = "the game is over"
        elif state.phase is Phase.WIN_DECLARED:
            what = "the round was won and only reactions are accepted"
        else:
            what = f"phase {state.phase.value}"
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
    streaks, count = update_pass_streaks(state.pass_streaks, seat, chit.name)
    if count >= CONSECUTIVE_PASS_LIMIT:
        return _draw_attempt(state, seat, chit, count)  # the tenth chit is not delivered
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
        pass_streaks=streaks,
        next_seq=state.next_seq + 1,
    )
    check_invariants(new_state)
    return Accepted(new_state, (event,))


def _draw_attempt(state: GameState, seat: int, chit: Chit, consecutive: int) -> Accepted:
    """End the attempt as an anti-stall draw (§3A.6) and redeal.

    `chit` is the tenth consecutive same-name pass by `seat`; it is *not*
    delivered, so no receiver ever gets a claim opportunity from it. No score
    changes and `completed_rounds` is untouched. The new attempt is the seeded
    deal for (same completed round, attempt + 1): same initiator by
    construction, fresh hands, anti-stall streaks cleared (a new `GameState`
    starts with none), event sequence continuing.
    """
    drawn = AttemptDrawn(
        seq=state.next_seq,
        completed_round=state.completed_rounds,
        attempt=state.attempt,
        seat=seat,
        consecutive_passes=consecutive,
        chit=chit,
    )
    deal = deal_round(state.config, state.completed_rounds, state.attempt + 1)
    new_state, deal_event = _start_round(state.config, deal, state.scores, state.next_seq + 1)
    return Accepted(new_state, (drawn, deal_event))


def timeout_chit(state: GameState) -> Chit:
    """The chit a forced pass would choose right now (M6, §3A.7).

    Uniform over the decision seat's physical chit instances (four for the
    initiator, five for a receiver), drawn from the dedicated "timeout" stream
    seeded by (master seed, completed round, attempt, next sequence number).
    The hand is sorted first, so the choice depends on the set of chits held,
    not on the order in which they arrived. Stateless: calling it repeatedly
    returns the same chit and consumes nothing.
    """
    if state.phase is not Phase.PASSING or state.decision_seat is None:
        raise ValueError("a forced pass exists only at a passing decision point")
    rng = make_rng(state.config.seed, TIMEOUT, state.completed_rounds, state.attempt, state.next_seq)
    return rng.choice(sorted(state.hands[state.decision_seat]))


def _apply_timeout(state: GameState, seat: int) -> Accepted | Rejected:
    """Resolve an expired decision timer through the ordinary transition (M6).

    The timeout is validated like the action it stands for: only the single
    decision point may time out, and in the reaction phase only the last
    remaining non-winner. A `DecisionTimedOut` marker takes the next sequence
    number and the ordinary events follow, so a timeout cannot bypass claim,
    pass, reaction, scoring or anti-stall logic and never produces a claim.
    """
    if state.phase is Phase.GAME_OVER:
        return Rejected(RejectionReason.PHASE_NOT_ACCEPTING, "no action is accepted: the game is over")
    if state.phase is Phase.WIN_DECLARED:
        pending = pending_reactors(state)
        if len(pending) != 1:
            return Rejected(
                RejectionReason.TIMEOUT_NOT_AVAILABLE,
                f"no reaction timeout applies while {len(pending)} non-winners still need to react",
            )
        if seat != pending[0]:
            if seat == state.winner:
                return Rejected(RejectionReason.WINNER_CANNOT_REACT, f"seat {seat} won the round and does not react")
            return Rejected(RejectionReason.ALREADY_REACTED, f"seat {seat} has already reacted")
        kind = TIMEOUT_KIND_FINAL_REACTION
    elif state.phase in (Phase.INITIAL_CLAIMS, Phase.PASSING):
        if seat != state.decision_seat:
            return Rejected(
                RejectionReason.NOT_DECISION_POINT,
                f"seat {seat} has no decision to time out now (waiting for seat {state.decision_seat})",
            )
        kind = state.decision_kind.value
    else:
        return Rejected(RejectionReason.PHASE_NOT_ACCEPTING, f"no action is accepted: phase {state.phase.value}")

    # Everything above only validated; choose the forced chit before the
    # sequence number moves, so the choice is a function of the state the host saw.
    chit = timeout_chit(state) if state.phase is Phase.PASSING else None
    marker = DecisionTimedOut(
        seq=state.next_seq,
        completed_round=state.completed_rounds,
        attempt=state.attempt,
        seat=seat,
        decision_kind=kind,
    )
    shifted = replace(state, next_seq=state.next_seq + 1)
    if state.phase is Phase.WIN_DECLARED:
        result = _apply_react(shifted, seat)
    elif state.phase is Phase.INITIAL_CLAIMS:
        result = _apply_initial_decline(shifted, seat)
    else:
        result = _apply_pass(shifted, seat, chit)
    if not isinstance(result, Accepted):  # pre-validated above, so this is an engine bug
        raise InvariantViolation(f"a validated timeout was rejected: {result!r}")
    return Accepted(result.state, (marker,) + result.events)


def _apply_ordinary_claim(state: GameState, seat: int) -> Accepted:
    """A claim at a receive or return opportunity. A valid claim ends in the
    WIN_DECLARED reaction phase (M5, §9 question 8); a false claim completes
    the round (M4)."""
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


def _apply_react(state: GameState, seat: int) -> Accepted | Rejected:
    """A non-winner reacts to a valid win (M5, §3A.5).

    Reaction order is the order in which the authoritative engine accepts these
    actions; there is no clock. Check order: the game is not over, the phase is
    the reaction phase, the seat is not the winner, the seat has not reacted.
    The reaction that completes the set of N-1 non-winners scores the round and
    advances it inside this same call, so the win is scored exactly once.
    """
    if state.phase is Phase.GAME_OVER:
        return Rejected(RejectionReason.PHASE_NOT_ACCEPTING, "no action is accepted: the game is over")
    if state.phase is not Phase.WIN_DECLARED:
        return Rejected(
            RejectionReason.ACTION_NOT_AVAILABLE,
            f"reactions exist only after a valid win (phase {state.phase.value})",
        )
    if seat == state.winner:
        return Rejected(RejectionReason.WINNER_CANNOT_REACT, f"seat {seat} won the round and does not react")
    if seat in state.reaction_order:
        return Rejected(RejectionReason.ALREADY_REACTED, f"seat {seat} has already reacted")

    order = state.reaction_order + (seat,)
    event = PlayerReacted(
        seq=state.next_seq,
        completed_round=state.completed_rounds,
        attempt=state.attempt,
        seat=seat,
        position=len(order),
        winner=state.winner,
    )
    new_state = replace(state, reaction_order=order, next_seq=state.next_seq + 1)
    check_invariants(new_state)  # at full length this is the transient, never-returned state
    if len(order) < state.config.num_players - 1:
        return Accepted(new_state, (event,))
    return _complete_valid_win(new_state, (event,))


def _complete_valid_win(win_state: GameState, events: tuple[Event, ...]) -> Accepted:
    """Finish a round that ended in a valid win (§3A.5, §3A.6).

    `win_state` is the transient WIN_DECLARED state in which every non-winner has
    reacted and `events` holds the final reaction event. The winner scores N and
    the non-winners N-1, ..., 1 in reaction order, added to the carried scores.
    """
    n = win_state.config.num_players
    winner, order = win_state.winner, win_state.reaction_order
    changes = valid_win_score_changes(n, winner, order)
    scores = tuple(total + change for total, change in zip(win_state.scores, changes))
    scored = ValidWinScored(
        seq=win_state.next_seq,
        completed_round=win_state.completed_rounds,
        attempt=win_state.attempt,
        winner=winner,
        reaction_order=order,
        score_changes=changes,
        scores=scores,
    )
    return _close_round(win_state, events, scored, scores, ROUND_OUTCOME_VALID_WIN, winner)


def _complete_false_claim(claim_state: GameState, events: tuple[Event, ...]) -> Accepted:
    """Finish a round that ended in a false claim (§3A.5, §3A.6).

    `claim_state` is the transient, already-validated FALSE_CLAIM state and
    `events` holds the claim event just produced. The claimant loses N-1
    points, every other seat scores 0, `completed_rounds` rises by exactly one,
    and the engine then either deals the next round or ends the game. Scores
    are carried over; attempt numbering restarts at 1; the next round's deal
    depends only on (master seed, completed-round index, attempt 1).
    """
    n = claim_state.config.num_players
    claimant = claim_state.false_claimant
    changes = false_claim_score_changes(n, claimant)
    scores = tuple(total + change for total, change in zip(claim_state.scores, changes))
    penalized = FalseClaimPenalized(
        seq=claim_state.next_seq,
        completed_round=claim_state.completed_rounds,
        attempt=claim_state.attempt,
        seat=claimant,
        penalty=false_claim_penalty(n),
        score_changes=changes,
        scores=scores,
    )
    return _close_round(claim_state, events, penalized, scores, ROUND_OUTCOME_FALSE_CLAIM, claimant)


def _close_round(
    round_state: GameState,
    events: tuple[Event, ...],
    score_event: Event,
    scores: tuple[int, ...],
    outcome: str,
    claimant: int,
) -> Accepted:
    """The tail shared by both ways a round completes (M4 false claim, M5 valid win).

    Appends the already-built score event (numbered `round_state.next_seq`) and
    `RoundCompleted`, increments `completed_rounds` exactly once, then deals the
    next round (fresh seeded deal for the new completed-round index, attempt 1,
    rotated initiator, scores carried over) or, after the last configured round,
    returns `GAME_OVER`.
    """
    config = round_state.config
    n = config.num_players
    round_index, attempt = round_state.completed_rounds, round_state.attempt
    rounds_completed = round_index + 1

    seq = score_event.seq
    out: list[Event] = list(events)
    out.append(score_event)
    out.append(
        RoundCompleted(
            seq=seq + 1,
            completed_round=round_index,
            attempt=attempt,
            outcome=outcome,
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
            round_state,
            completed_rounds=rounds_completed,
            attempt=FIRST_ATTEMPT,
            initiator=rotation_initiator(n, rounds_completed),
            phase=Phase.GAME_OVER,
            initial_claims_resolved=0,
            scores=scores,
            winner=None,
            false_claimant=None,
            claim_decision_kind=None,
            reaction_order=(),
            pass_streaks=(),
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
