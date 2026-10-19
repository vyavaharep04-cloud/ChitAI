"""Deterministic seeds, seat rotation and the reaction-order policy (M8 Stage 2).

Everything here is a pure function. All randomness comes from the engine's
`derive_seed` / `make_rng` (SHA-256, never `hash()`); nothing in this module
implements its own generator, keeps state, reads a clock or touches a file.

Two purpose labels are added, both defined here so the engine is untouched:

* `GAME` ("sim_game"): the per-game master seed, keyed by (batch seed, seed index).
* `REACTION` ("sim_reaction"): the reaction-order stream, keyed by
  (game seed, completed round, attempt).

Each call builds a fresh generator from a key that contains the purpose string,
so a draw from one stream can never change another. In particular the engine's
`DEAL` and `TIMEOUT` streams are unaffected by anything in this module.

Reaction order is an *experimental policy*, not a model of human reaction speed.
In the reaction phase every pending non-winner is eligible at once and the
engine's accepted-action order sets the scores (PROJECT_CONTEXT.md §3A.5, §9
questions 1, 18, 20). The host needs some order in which to let AI agents react;
a seeded permutation is a neutral, reproducible choice. It carries no claim about
how quickly any player would really react.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from ..engine import GameState, make_rng, derive_seed, pending_reactors

GAME = "sim_game"
REACTION = "sim_reaction"

T = TypeVar("T")


def _check_int(name: str, value: object, minimum: int | None = None) -> int:
    # bool is a subclass of int; True/False are not acceptable numeric settings.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


# --- per-game seeds ----------------------------------------------------------------------


def seed_index(game_index: int, games_per_seed: int = 1) -> int:
    """The seed index a game uses: `game_index // games_per_seed`.

    With the default of 1 every game has its own seed (independent mode). With
    `games_per_seed = k > 1` the games `0..k-1` share one seed, `k..2k-1` the next,
    and so on (paired mode). Games that share a seed play identical deals and
    identical timeout draws, so they can be compared like for like; typically k is
    the number of seatings or conditions being compared.
    """
    _check_int("game_index", game_index, 0)
    _check_int("games_per_seed", games_per_seed, 1)
    return game_index // games_per_seed


def game_seed(batch_seed: int, game_index: int, games_per_seed: int = 1) -> int:
    """The master seed (a `GameConfig.seed`) of game `game_index` in a batch.

    `derive_seed(batch_seed, "sim_game", seed_index(game_index, games_per_seed))`.
    """
    _check_int("batch_seed", batch_seed)
    return derive_seed(batch_seed, GAME, seed_index(game_index, games_per_seed))


# --- seat rotation -----------------------------------------------------------------------


def seat_assignment(num_players: int, game_index: int, rotate: bool = True) -> tuple[int, ...]:
    """`result[seat]` is the lineup index sitting in `seat` in game `game_index`.

    Definition: lineup entry `e` sits in seat `(e + game_index) mod N`, i.e. the
    whole lineup moves one seat clockwise (increasing seat index, wrapping) per
    game; equivalently seat `s` holds entry `(s - game_index) mod N`. Game 0 is the
    identity. Over any N consecutive games every entry occupies every seat exactly
    once. With `rotate=False` the assignment is always the identity.
    """
    _check_int("num_players", num_players, 1)
    _check_int("game_index", game_index, 0)
    shift = game_index % num_players if rotate else 0
    return tuple((seat - shift) % num_players for seat in range(num_players))


def lineup_seat(num_players: int, game_index: int, lineup_index: int, rotate: bool = True) -> int:
    """The seat that lineup entry `lineup_index` occupies in game `game_index`
    (the inverse of `seat_assignment`)."""
    _check_int("num_players", num_players, 1)
    _check_int("lineup_index", lineup_index, 0)
    if lineup_index >= num_players:
        raise ValueError(f"lineup_index must be below {num_players}, got {lineup_index}")
    assignment = seat_assignment(num_players, game_index, rotate)
    return assignment.index(lineup_index)


def seated_lineup(lineup: Sequence[T], game_index: int, rotate: bool = True) -> tuple[T, ...]:
    """`lineup` arranged by seat for game `game_index`: element `seat` is the entry
    that plays that seat."""
    return tuple(lineup[index] for index in seat_assignment(len(lineup), game_index, rotate))


# --- reaction order ----------------------------------------------------------------------


def reaction_order(
    game_seed_value: int, completed_round: int, attempt: int, pending: Sequence[int]
) -> tuple[int, ...]:
    """A seeded permutation of the seats in `pending`.

    The stream is `make_rng(game_seed, "sim_reaction", completed_round, attempt)`.
    `pending` is treated as a set (it is sorted first, and duplicates are an error),
    so the result depends only on the key and on which seats are pending, never on
    the order they were passed in. Call it once per valid win with the full
    `pending_reactors(state)`: a valid win happens at most once for a given
    (completed round, attempt), so the key identifies the win.
    """
    _check_int("game_seed", game_seed_value)
    _check_int("completed_round", completed_round, 0)
    _check_int("attempt", attempt, 1)
    seats = [_check_int("pending seat", seat, 0) for seat in pending]
    if len(set(seats)) != len(seats):
        raise ValueError(f"pending seats must be distinct, got {tuple(pending)!r}")
    seats.sort()
    make_rng(game_seed_value, REACTION, completed_round, attempt).shuffle(seats)
    return tuple(seats)


def reaction_order_for_state(state: GameState) -> tuple[int, ...]:
    """`reaction_order` for the pending reactors of `state` (host-side use).

    Empty outside the reaction phase. This reads the game seed, which is a host
    secret: the result is a list of seats, which is public once reactions happen,
    and the seed itself never leaves the host.
    """
    return reaction_order(
        state.config.seed, state.completed_rounds, state.attempt, pending_reactors(state)
    )
