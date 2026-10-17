"""Scoring rules (§3A.5). M4: false-claim penalties only.

Pure functions; no state, no randomness. Win scores and reaction-order scores
belong to M5 and are deliberately absent.
"""

from __future__ import annotations

from .config import MAX_PLAYERS, MIN_PLAYERS


def false_claim_penalty(num_players: int) -> int:
    """Points deducted from a false claimant: N - 1 (a positive number; the
    claimant's score changes by its negation, §3A.5)."""
    _check_player_count(num_players)
    return num_players - 1


def false_claim_score_changes(num_players: int, claimant: int) -> tuple[int, ...]:
    """Per-seat score change for a false-claim round: the claimant receives
    -(N-1) and every other seat receives 0. No winner or reaction score exists."""
    penalty = false_claim_penalty(num_players)
    if (
        not isinstance(claimant, int)
        or isinstance(claimant, bool)
        or not 0 <= claimant < num_players
    ):
        raise ValueError(f"claimant must be an integer seat in [0, {num_players}), got {claimant!r}")
    return tuple(-penalty if seat == claimant else 0 for seat in range(num_players))


def _check_player_count(num_players: int) -> None:
    if (
        not isinstance(num_players, int)
        or isinstance(num_players, bool)
        or not MIN_PLAYERS <= num_players <= MAX_PLAYERS
    ):
        raise ValueError(
            f"num_players must be an integer between {MIN_PLAYERS} and {MAX_PLAYERS}, "
            f"got {num_players!r}"
        )
