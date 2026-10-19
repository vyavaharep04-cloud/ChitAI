"""Seed derivation, paired seeds and seat rotation (M8 Stage 2)."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections import Counter

import pytest

from chitai.engine import DEAL, TIMEOUT, derive_seed
from chitai.simulation import (
    GAME,
    REACTION,
    game_seed,
    lineup_seat,
    seat_assignment,
    seated_lineup,
    seed_index,
)


def sha(key: str) -> int:
    """Independent re-computation of the engine's documented key format."""
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


# --- labels ------------------------------------------------------------------------------


def test_labels_are_distinct_from_the_engine_labels_and_contain_no_colon():
    labels = [GAME, REACTION, DEAL, TIMEOUT]
    assert (GAME, REACTION) == ("sim_game", "sim_reaction")
    assert len(set(labels)) == 4
    assert all(":" not in label for label in labels)


# --- golden values (pinned) --------------------------------------------------------------

GOLDEN_GAME_SEEDS = {
    (2026, 0): 13036505416530766680,
    (2026, 1): 7832215708701031782,
    (2026, 2): 10071872300545666556,
    (0, 0): 17955205379339787888,
    (-7, 3): 11234668095437634072,
    (12345678901234567890, 5): 14349649448344238131,
    (42, 100): 9692080566064067268,
}


@pytest.mark.parametrize(("key", "expected"), GOLDEN_GAME_SEEDS.items())
def test_game_seeds_are_pinned_and_follow_the_documented_key_format(key, expected):
    batch, index = key
    assert game_seed(batch, index) == expected
    assert expected == sha(f"{batch}:sim_game:{index}")  # not just an echo of derive_seed
    assert expected == derive_seed(batch, GAME, index)


def test_game_seeds_are_64_bit_and_distinct_across_a_batch():
    seeds = [game_seed(2026, i) for i in range(2000)]
    assert len(set(seeds)) == len(seeds)
    assert all(0 <= seed < 2**64 for seed in seeds)


def test_game_seed_depends_on_the_batch_seed():
    assert game_seed(1, 0) != game_seed(2, 0)
    assert game_seed(1, 0) == game_seed(1, 0)


def test_game_seed_is_stable_across_processes_with_different_hash_seeds():
    # Guards against any use of the per-process-randomised built-in hash().
    code = "from chitai.simulation import game_seed; print(game_seed(2026, 1))"
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": str(s), "PYTHONPATH": "src"},
        ).stdout.strip()
        for s in (1, 2, 3)
    }
    assert outputs == {str(GOLDEN_GAME_SEEDS[(2026, 1)])}


@pytest.mark.parametrize(
    "call",
    [
        lambda: game_seed(True, 0),
        lambda: game_seed(1.5, 0),
        lambda: game_seed("1", 0),
        lambda: game_seed(1, -1),
        lambda: game_seed(1, True),
        lambda: game_seed(1, 0, 0),
        lambda: game_seed(1, 0, 1.0),
        lambda: seed_index(-1),
    ],
)
def test_bad_seed_arguments_are_rejected(call):
    with pytest.raises(ValueError):
        call()


# --- paired seeds ------------------------------------------------------------------------


def test_independent_mode_is_the_default_and_gives_every_game_its_own_seed():
    assert [seed_index(g) for g in range(5)] == [0, 1, 2, 3, 4]
    assert game_seed(9, 3) == game_seed(9, 3, games_per_seed=1)


def test_paired_mode_groups_consecutive_games_on_one_seed():
    assert [seed_index(g, 3) for g in range(8)] == [0, 0, 0, 1, 1, 1, 2, 2]
    seeds = [game_seed(9, g, games_per_seed=3) for g in range(9)]
    assert seeds[0] == seeds[1] == seeds[2] != seeds[3] == seeds[4] == seeds[5] != seeds[6]
    assert len(set(seeds)) == 3


def test_a_paired_group_uses_the_independent_seed_of_its_index():
    # Group k of a paired batch plays the seed that independent game k would play.
    assert game_seed(9, 7, games_per_seed=4) == game_seed(9, 1)


# --- seat rotation -----------------------------------------------------------------------


@pytest.mark.parametrize("n", (4, 5, 6, 7, 8))
def test_game_zero_is_the_identity_and_each_game_is_a_permutation(n):
    assert seat_assignment(n, 0) == tuple(range(n))
    for game in range(3 * n):
        assert sorted(seat_assignment(n, game)) == list(range(n))


def test_the_rotation_is_defined_as_one_seat_clockwise_per_game():
    # lineup entry e sits in seat (e + game) % N; seat s holds entry (s - game) % N
    assert seat_assignment(4, 1) == (3, 0, 1, 2)
    assert seat_assignment(4, 2) == (2, 3, 0, 1)
    assert seat_assignment(4, 4) == (0, 1, 2, 3)  # period N
    assert seated_lineup(["a", "b", "c", "d"], 1) == ("d", "a", "b", "c")


@pytest.mark.parametrize("n", (4, 5, 6, 7, 8))
@pytest.mark.parametrize("start", (0, 1, 3))
def test_over_n_consecutive_games_every_entry_sits_in_every_seat_exactly_once(n, start):
    seats_of = {entry: [] for entry in range(n)}
    for game in range(start, start + n):
        for seat, entry in enumerate(seat_assignment(n, game)):
            seats_of[entry].append(seat)
    for entry, seats in seats_of.items():
        assert sorted(seats) == list(range(n)), entry


@pytest.mark.parametrize("n", (4, 8))
def test_seat_balance_over_a_whole_number_of_cycles(n):
    counts = Counter()
    for game in range(3 * n):
        for seat, entry in enumerate(seat_assignment(n, game)):
            counts[(entry, seat)] += 1
    assert set(counts.values()) == {3} and len(counts) == n * n


@pytest.mark.parametrize("n", (4, 6))
def test_lineup_seat_is_the_inverse_of_seat_assignment(n):
    for game in range(2 * n):
        assignment = seat_assignment(n, game)
        for seat, entry in enumerate(assignment):
            assert lineup_seat(n, game, entry) == seat


def test_rotation_can_be_switched_off():
    for game in range(6):
        assert seat_assignment(4, game, rotate=False) == (0, 1, 2, 3)
        assert lineup_seat(4, game, 2, rotate=False) == 2
        assert seated_lineup("abcd", game, rotate=False) == tuple("abcd")


def test_seated_lineup_keeps_the_entries_it_is_given():
    lineup = [{"x": 1}, {"x": 2}, {"x": 3}, {"x": 4}]
    seated = seated_lineup(lineup, 2)
    assert [e["x"] for e in seated] == [3, 4, 1, 2]
    assert seated[0] is lineup[2]


@pytest.mark.parametrize(
    "call",
    [
        lambda: seat_assignment(0, 0),
        lambda: seat_assignment(4, -1),
        lambda: seat_assignment(4.0, 0),
        lambda: lineup_seat(4, 0, 4),
        lambda: lineup_seat(4, 0, -1),
    ],
)
def test_bad_rotation_arguments_are_rejected(call):
    with pytest.raises(ValueError):
        call()
