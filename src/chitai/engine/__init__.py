"""Pure game engine. M1: configuration, deck, seeded deal, rotation.
M2: state, actions, events, invariants, and the initial claim phase.
M3: sequential passing and ordinary claim opportunities."""

from .actions import Action, ClaimAction, DeclineAction, PassAction
from .chits import CHIT_NAMES, CHITS_PER_HAND, COPIES_PER_NAME, Chit, build_deck, chit_names_for
from .config import (
    MAX_PASS_TIMEOUT_SECONDS,
    MAX_PLAYERS,
    MIN_PLAYERS,
    ConfigError,
    GameConfig,
)
from .deal import FIRST_ATTEMPT, Deal, deal_round, initiator_for_round
from .engine import Accepted, RejectionReason, Rejected, apply_action, new_game, start_from_deal
from .events import (
    ChitPassed,
    ClaimMade,
    DealEvent,
    Event,
    InitialClaimDeclined,
    InitialClaimMade,
    InitialClaimsResolved,
)
from .invariants import InvariantViolation, check_invariants
from .rng import derive_seed, make_rng
from .rules import (
    has_claim_opportunity,
    initial_claim_order,
    is_valid_claim,
    is_valid_initial_claim,
    is_valid_receiver_claim,
    is_valid_seat,
    legal_actions,
    next_seat,
)
from .state import CLAIM_KINDS, DecisionKind, GameState, Phase

__all__ = [
    "Action",
    "ClaimAction",
    "DeclineAction",
    "PassAction",
    "CHIT_NAMES",
    "CHITS_PER_HAND",
    "COPIES_PER_NAME",
    "Chit",
    "build_deck",
    "chit_names_for",
    "MAX_PASS_TIMEOUT_SECONDS",
    "MAX_PLAYERS",
    "MIN_PLAYERS",
    "ConfigError",
    "GameConfig",
    "FIRST_ATTEMPT",
    "Deal",
    "deal_round",
    "initiator_for_round",
    "derive_seed",
    "make_rng",
    "Accepted",
    "Rejected",
    "RejectionReason",
    "apply_action",
    "new_game",
    "start_from_deal",
    "ChitPassed",
    "ClaimMade",
    "DealEvent",
    "Event",
    "InitialClaimDeclined",
    "InitialClaimMade",
    "InitialClaimsResolved",
    "InvariantViolation",
    "check_invariants",
    "has_claim_opportunity",
    "initial_claim_order",
    "is_valid_claim",
    "is_valid_initial_claim",
    "is_valid_receiver_claim",
    "next_seat",
    "is_valid_seat",
    "legal_actions",
    "CLAIM_KINDS",
    "DecisionKind",
    "GameState",
    "Phase",
]
