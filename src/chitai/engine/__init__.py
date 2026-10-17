"""Pure game engine. Milestone 1: configuration, deck, seeded deal, rotation."""

from .chits import CHIT_NAMES, CHITS_PER_HAND, COPIES_PER_NAME, Chit, build_deck, chit_names_for
from .config import (
    MAX_PASS_TIMEOUT_SECONDS,
    MAX_PLAYERS,
    MIN_PLAYERS,
    ConfigError,
    GameConfig,
)
from .deal import FIRST_ATTEMPT, Deal, deal_round, initiator_for_round
from .rng import derive_seed, make_rng

__all__ = [
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
]
