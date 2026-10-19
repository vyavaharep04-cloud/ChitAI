"""The seeded reaction-order policy and its independence from the DEAL and TIMEOUT streams."""

from __future__ import annotations

import itertools
import random
import subprocess
import sys
from collections import Counter

import pytest
from observations.support import PLAYER_COUNTS, winning_state

from chitai.engine import (
    DEAL,
    TIMEOUT,
    Accepted,
    AttemptDrawn,
    DealEvent,
    DecisionTimedOut,
    GameConfig,
    PassAction,
    Phase,
    ReactAction,
    apply_action,
    deal_round,
    derive_seed,
    make_rng,
    new_game,
    pending_reactors,
    timeout_action,
    timeout_chit,
    valid_win_score_changes,
)
from chitai.simulation import REACTION, game_seed, reaction_order, reaction_order_for_state

# --- pinned values -----------------------------------------------------------------------

GOLDEN = {
    (2026, 0, 1): (3, 6, 1, 2, 4, 5),
    (2026, 0, 2): (2, 3, 1, 6, 4, 5),
    (2026, 1, 1): (5, 2, 6, 1, 3, 4),
    (7, 3, 1): (4, 1, 5, 2, 3, 6),
    (13036505416530766680, 0, 1): (1, 6, 4, 3, 5, 2),
}


@pytest.mark.parametrize(("key", "expected"), GOLDEN.items())
def test_permutations_are_pinned(key, expected):
    seed, completed_round, attempt = key
    assert reaction_order(seed, completed_round, attempt, (1, 2, 3, 4, 5, 6)) == expected


def test_the_stream_is_the_documented_rng_stream():
    expected = list(range(1, 7))
    make_rng(2026, "sim_reaction", 0, 1).shuffle(expected)
    assert tuple(expected) == reaction_order(2026, 0, 1, range(1, 7))
    assert REACTION == "sim_reaction"


def test_the_permutation_is_stable_across_processes_with_different_hash_seeds():
    code = "from chitai.simulation import reaction_order; print(reaction_order(2026, 0, 1, (1,2,3,4,5,6)))"
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
    assert outputs == {str(GOLDEN[(2026, 0, 1)])}


# --- permutation properties --------------------------------------------------------------


@pytest.mark.parametrize("pending", [(1,), (1, 2), (0, 2, 3), (1, 2, 3, 4, 5, 6, 7)])
def test_the_result_is_a_complete_permutation_of_the_pending_seats(pending):
    for completed_round in range(5):
        for attempt in range(1, 4):
            result = reaction_order(5, completed_round, attempt, pending)
            assert sorted(result) == list(pending) and len(result) == len(pending)


def test_an_empty_pending_set_gives_an_empty_order():
    assert reaction_order(5, 0, 1, ()) == ()


def test_the_same_key_always_gives_the_same_order():
    first = reaction_order(11, 2, 3, (0, 1, 2, 3, 4, 5, 6))
    assert all(reaction_order(11, 2, 3, (0, 1, 2, 3, 4, 5, 6)) == first for _ in range(20))


def test_the_result_does_not_depend_on_the_order_pending_is_given_in():
    pending = [0, 2, 3, 5, 6, 7]
    expected = reaction_order(11, 2, 3, pending)
    for shuffled in itertools.islice(itertools.permutations(pending), 0, 720, 37):
        assert reaction_order(11, 2, 3, shuffled) == expected


def test_the_order_varies_across_rounds_attempts_and_seeds():
    pending = (1, 2, 3, 4, 5, 6)
    by_round = {reaction_order(11, r, 1, pending) for r in range(30)}
    by_attempt = {reaction_order(11, 0, a, pending) for a in range(1, 31)}
    by_seed = {reaction_order(s, 0, 1, pending) for s in range(30)}
    assert min(len(by_round), len(by_attempt), len(by_seed)) >= 25  # 720 orders; collisions are rare


def test_no_seat_is_systematically_first_or_last():
    # Deterministic, so these loose bounds cannot flake: 4 seats, 2000 keys, ~500 each expected.
    pending = (0, 1, 2, 3)
    first, last = Counter(), Counter()
    for completed_round in range(40):
        for attempt in range(1, 51):
            order = reaction_order(99, completed_round, attempt, pending)
            first[order[0]] += 1
            last[order[-1]] += 1
    assert set(first) == set(last) == set(pending)
    assert all(400 <= count <= 600 for count in first.values()), first
    assert all(400 <= count <= 600 for count in last.values()), last


@pytest.mark.parametrize(
    "call",
    [
        lambda: reaction_order(True, 0, 1, (1, 2)),
        lambda: reaction_order(1, -1, 1, (1, 2)),
        lambda: reaction_order(1, 0, 0, (1, 2)),  # attempts start at 1
        lambda: reaction_order(1, 0, 1, (1, 1)),
        lambda: reaction_order(1, 0, 1, (1, -2)),
        lambda: reaction_order(1, 0, 1, (1, "2")),
    ],
)
def test_bad_arguments_are_rejected(call):
    with pytest.raises(ValueError):
        call()


# --- use with a real engine state --------------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_the_order_for_a_real_win_is_a_permutation_the_engine_accepts_and_scores(n):
    state = winning_state(n)
    pending = pending_reactors(state)
    order = reaction_order_for_state(state)
    assert order == reaction_order(state.config.seed, state.completed_rounds, state.attempt, pending)
    assert sorted(order) == list(pending) and state.winner not in order
    for seat in order[:-1]:
        result = apply_action(state, ReactAction(seat))
        assert isinstance(result, Accepted)
        state = result.state
    final = apply_action(state, ReactAction(order[-1]))
    assert isinstance(final, Accepted)
    expected = valid_win_score_changes(n, winning_state(n).winner, order)
    assert final.state.scores == expected


def test_outside_the_reaction_phase_the_order_is_empty():
    state = new_game(GameConfig(4, 4, 1)).state
    assert state.phase is Phase.INITIAL_CLAIMS and reaction_order_for_state(state) == ()


# --- independence from the DEAL and TIMEOUT streams --------------------------------------


def test_the_reaction_stream_has_its_own_keys():
    for seed in range(200):
        for r, a in ((0, 1), (1, 1), (0, 2), (3, 4)):
            reaction = derive_seed(seed, REACTION, r, a)
            assert reaction not in {derive_seed(seed, DEAL, r, a), derive_seed(seed, TIMEOUT, r, a)}
            # and the timeout key has an extra index, so no prefix of one is another
            assert reaction != derive_seed(seed, TIMEOUT, r, a, 0)
    assert REACTION not in (DEAL, TIMEOUT)


def test_using_the_reaction_stream_leaves_deals_and_the_forced_pass_unchanged():
    config = GameConfig(4, 8, 424242)
    state = new_game(config).state  # initial-claims state, then to a passing state with a timeout pending
    while state.phase is Phase.INITIAL_CLAIMS:
        state = apply_action(state, timeout_action(state)).state
    assert state.phase is Phase.PASSING

    deals = [(r, a) for r in range(config.num_rounds) for a in (1, 2, 3)]
    deals_before = [deal_round(config, r, a) for r, a in deals]
    chit_before = timeout_chit(state)

    for r in range(40):  # consume the reaction stream heavily, for this seed and others
        for a in range(1, 6):
            reaction_order(config.seed, r, a, range(1, 8))
            reaction_order(game_seed(config.seed, r), r, a, range(1, 8))
    rng = make_rng(config.seed, REACTION, 0, 1)
    for _ in range(1000):
        rng.random()

    assert [deal_round(config, r, a) for r, a in deals] == deals_before
    assert timeout_chit(state) == chit_before


def _scripted_game(seed: int, interleave: bool):
    """A host-timeout game that stalls into several redeals; optionally calls the
    reaction function before every action. Returns every event's private view."""
    config = GameConfig(4, 4, seed)
    start = new_game(config)
    state, events = start.state, list(start.events)
    for step in range(700):
        if state.phase not in (Phase.INITIAL_CLAIMS, Phase.PASSING):
            break
        if interleave:
            reaction_order_for_state(state)
            reaction_order(seed, state.completed_rounds, state.attempt, (1, 2, 3))
        if state.phase is Phase.INITIAL_CLAIMS or step % 5 == 4:
            action = timeout_action(state)  # initial auto-decline / forced pass (TIMEOUT stream)
        else:
            seat = state.decision_seat
            action = PassAction(seat, min(state.hands[seat], key=lambda c: (c.name, c.copy)))
        result = apply_action(state, action)
        assert isinstance(result, Accepted)
        state = result.state
        events.extend(result.events)
    return state, [event.debug_view() for event in events], events


def test_a_whole_game_with_redeals_and_timeouts_is_identical_with_and_without_the_stream():
    state_a, views_a, events = _scripted_game(1, interleave=False)
    state_b, views_b, _ = _scripted_game(1, interleave=True)
    # the script really exercises all three streams
    assert sum(isinstance(e, AttemptDrawn) for e in events) >= 3
    assert sum(isinstance(e, DecisionTimedOut) for e in events) >= 50
    assert sum(isinstance(e, DealEvent) and e.attempt > 1 for e in events) >= 3
    assert views_a == views_b and state_a == state_b


def test_random_pending_sets_never_disturb_a_game(monkeypatch):
    # A second, independent check: hammer the function with random arguments mid-game.
    rng = random.Random(0)
    baseline = _scripted_game(2, interleave=False)[1]
    original = reaction_order

    def noisy(*args, **kwargs):
        for _ in range(3):
            original(rng.randrange(10**6), rng.randrange(5), rng.randrange(1, 5), range(rng.randrange(1, 8)))
        return original(*args, **kwargs)

    monkeypatch.setattr(sys.modules[__name__], "reaction_order", noisy)
    assert _scripted_game(2, interleave=True)[1] == baseline
