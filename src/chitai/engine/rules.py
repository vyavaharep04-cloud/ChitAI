"""Pure rule functions (§3A.3, §5A). Milestone 2: initial-phase rules only.

No function here mutates anything or consults randomness. Matching uses chit
names only (§3A.2).
"""

from __future__ import annotations

from .actions import Action, ClaimAction, DeclineAction
from .chits import CHITS_PER_HAND, Chit
from .config import GameConfig
from .state import GameState, Phase


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


def is_valid_seat(config: GameConfig, seat: object) -> bool:
    """True for an integer (not bool) seat in [0, N)."""
    return isinstance(seat, int) and not isinstance(seat, bool) and 0 <= seat < config.num_players


def legal_actions(state: GameState) -> tuple[Action, ...]:
    """Actions the engine would accept right now.

    In the initial claim phase only the decision-point seat may act, and may
    claim or decline whether or not its hand matches. In every other M2 phase
    the engine accepts nothing yet (passing is M3; reactions are M5).
    """
    if state.phase is Phase.INITIAL_CLAIMS and state.decision_seat is not None:
        seat = state.decision_seat
        return (ClaimAction(seat), DeclineAction(seat))
    return ()
