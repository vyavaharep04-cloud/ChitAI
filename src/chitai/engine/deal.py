"""Seeded dealing and starting-player (initiator) rotation (§3A.1, §3A.3, §3A.6)."""

from __future__ import annotations

from dataclasses import dataclass

from .chits import CHITS_PER_HAND, Chit, build_deck
from .config import GameConfig
from .rng import DEAL, make_rng

FIRST_ATTEMPT = 1


@dataclass(frozen=True)
class Deal:
    """The result of one shuffle-and-deal: hands[seat] is that seat's four chits."""

    completed_round: int
    attempt: int
    initiator: int
    hands: tuple[tuple[Chit, ...], ...]


def initiator_for_round(config: GameConfig, completed_round: int) -> int:
    """Initiator seat for a completed-round index (0-based).

    Seat 0 starts; the initiator rotates one seat clockwise (increasing seat
    index, wrapping N-1 -> 0) after each completed round. The result depends
    only on the completed-round index, so an anti-stall draw (which does not
    consume a completed round) necessarily keeps the same initiator.
    """
    _check_round(config, completed_round)
    return completed_round % config.num_players


def deal_round(config: GameConfig, completed_round: int, attempt: int = FIRST_ATTEMPT) -> Deal:
    """Shuffle a fresh deck and deal four chits to every seat.

    The shuffle is seeded from (config.seed, completed_round, attempt) only, so
    it is reproducible, differs between rounds and attempts, and is unaffected
    by any other random stream. Attempts are numbered from 1.
    """
    _check_round(config, completed_round)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < FIRST_ATTEMPT:
        raise ValueError(f"attempt must be an integer >= {FIRST_ATTEMPT}, got {attempt!r}")

    cards = list(build_deck(config.num_players))
    make_rng(config.seed, DEAL, completed_round, attempt).shuffle(cards)

    hands = tuple(
        tuple(cards[seat * CHITS_PER_HAND : (seat + 1) * CHITS_PER_HAND])
        for seat in range(config.num_players)
    )
    return Deal(
        completed_round=completed_round,
        attempt=attempt,
        initiator=initiator_for_round(config, completed_round),
        hands=hands,
    )


def _check_round(config: GameConfig, completed_round: int) -> None:
    if (
        not isinstance(completed_round, int)
        or isinstance(completed_round, bool)
        or not 0 <= completed_round < config.num_rounds
    ):
        raise ValueError(
            f"completed_round must be an integer in [0, {config.num_rounds}), "
            f"got {completed_round!r}"
        )
