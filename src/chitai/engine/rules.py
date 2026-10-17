"""Pure rule functions (§3A.3-§3A.4, §5A). M2: initial phase. M3: passing and claims.

No function here mutates anything or consults randomness. Matching uses chit
names only (§3A.2).
"""

from __future__ import annotations

from collections import Counter

from .actions import Action, ClaimAction, DeclineAction, PassAction
from .chits import CHITS_PER_HAND, Chit
from .config import GameConfig
from .state import CLAIM_KINDS, DecisionKind, GameState, Phase

RECEIVER_HAND_SIZE = CHITS_PER_HAND + 1  # a non-initiator holds five while deciding (§3A.4)
INITIATOR_IN_TRANSIT_HAND_SIZE = CHITS_PER_HAND - 1  # the initiator holds three mid-cycle


def initial_claim_order(num_players: int, initiator: int) -> tuple[int, ...]:
    """Seats in the order their initial opportunities are processed (§3A.3):
    the initiator first, then clockwise (increasing seat index, wrapping)."""
    return tuple((initiator + offset) % num_players for offset in range(num_players))


def is_valid_initial_claim(hand: tuple[Chit, ...]) -> bool:
    """An initial (or initiator-return) claim is valid only when all four chits
    share one name. Matching decides validity only, never eligibility."""
    if len(hand) != CHITS_PER_HAND:
        raise ValueError(f"an initial claim is judged on {CHITS_PER_HAND} chits, got {len(hand)}")
    return len({chit.name for chit in hand}) == 1


def is_valid_receiver_claim(hand: tuple[Chit, ...]) -> bool:
    """A non-initiator's claim is judged on five chits and is valid when at
    least four share one name (§3A.4). Each name has exactly four copies, so
    "at least four" can only mean exactly four of the same name."""
    if len(hand) != RECEIVER_HAND_SIZE:
        raise ValueError(f"a receiver claim is judged on {RECEIVER_HAND_SIZE} chits, got {len(hand)}")
    return max(Counter(chit.name for chit in hand).values()) >= CHITS_PER_HAND


def is_valid_claim(kind: DecisionKind, hand: tuple[Chit, ...]) -> bool:
    """Whether a claim made at decision point `kind` succeeds. Matching decides
    validity only; whether a claim is *allowed* depends on `kind` alone."""
    if kind in (DecisionKind.INITIAL_CLAIM, DecisionKind.INITIATOR_RETURN):
        return is_valid_initial_claim(hand)  # all four chits share a name
    if kind is DecisionKind.NON_INITIATOR_RECEIVE:
        return is_valid_receiver_claim(hand)
    raise ValueError(f"no claim opportunity exists at decision kind {kind!r}")


def next_seat(num_players: int, seat: int) -> int:
    """The next seat clockwise (increasing index, wrapping)."""
    return (seat + 1) % num_players


def has_claim_opportunity(state: GameState) -> bool:
    """True when the decision-point player may claim. Determined by phase and
    position in the passing sequence only, never by the hand (§3A.4)."""
    return (
        state.phase in (Phase.INITIAL_CLAIMS, Phase.PASSING)
        and state.decision_seat is not None
        and state.decision_kind in CLAIM_KINDS
    )


def is_valid_seat(config: GameConfig, seat: object) -> bool:
    """True for an integer (not bool) seat in [0, N)."""
    return isinstance(seat, int) and not isinstance(seat, bool) and 0 <= seat < config.num_players


def legal_actions(state: GameState) -> tuple[Action, ...]:
    """Actions the engine would accept right now.

    Initial claim phase: the decision-point seat may claim or decline whether
    or not its hand matches. Passing: the decision-point seat may pass any one
    chit it holds (four for the initiator, five for a receiver), and may also
    claim when it has a claim opportunity (§3A.4); there is no decline, because
    passing forfeits the opportunity. Holding phases accept nothing yet
    (reactions are M5).
    """
    seat = state.decision_seat
    if seat is None:
        return ()
    if state.phase is Phase.INITIAL_CLAIMS:
        return (ClaimAction(seat), DeclineAction(seat))
    if state.phase is Phase.PASSING and state.decision_kind in (
        DecisionKind.INITIATOR_FIRST_PASS,
        DecisionKind.NON_INITIATOR_RECEIVE,
        DecisionKind.INITIATOR_RETURN,
    ):
        passes = tuple(PassAction(seat, chit) for chit in state.hands[seat])
        if state.decision_kind in CLAIM_KINDS:
            return (ClaimAction(seat),) + passes
        return passes
    return ()
