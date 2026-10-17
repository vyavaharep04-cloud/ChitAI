"""Scoring rules (§3A.5). M4: false-claim penalties. M5: valid-win and reaction-order scores.

Pure functions; no state, no randomness.
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


def winner_score(num_players: int) -> int:
    """Points the winner of a valid win receives: N. Independent of reaction order."""
    _check_player_count(num_players)
    return num_players


def reaction_score(num_players: int, position: int) -> int:
    """Points for the non-winner who reacted `position`-th (1-based): N - position,
    so the first reactor scores N-1 and the last of the N-1 non-winners scores 1."""
    _check_player_count(num_players)
    if not _is_int(position) or not 1 <= position <= num_players - 1:
        raise ValueError(f"position must be an integer in [1, {num_players - 1}], got {position!r}")
    return num_players - position


def valid_win_round_total(num_players: int) -> int:
    """Sum of all score changes in one valid-win round: N + (N-1) + ... + 1."""
    _check_player_count(num_players)
    return num_players * (num_players + 1) // 2


def valid_win_score_changes(
    num_players: int, winner: int, reaction_order: tuple[int, ...]
) -> tuple[int, ...]:
    """Per-seat score change for a valid-win round (§3A.5). The winner receives N;
    the non-winners receive N-1, N-2, ..., 1 in `reaction_order`. `reaction_order`
    must list every non-winner exactly once."""
    _check_player_count(num_players)
    if not _is_int(winner) or not 0 <= winner < num_players:
        raise ValueError(f"winner must be an integer seat in [0, {num_players}), got {winner!r}")
    if (
        not isinstance(reaction_order, tuple)
        or not all(_is_int(seat) for seat in reaction_order)
        or sorted(reaction_order) != [seat for seat in range(num_players) if seat != winner]
    ):
        raise ValueError(
            f"reaction_order must list every non-winner of {num_players} players exactly once, "
            f"got {reaction_order!r} for winner {winner}"
        )
    changes = [0] * num_players
    changes[winner] = winner_score(num_players)
    for position, seat in enumerate(reaction_order, start=1):
        changes[seat] = reaction_score(num_players, position)
    return tuple(changes)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
