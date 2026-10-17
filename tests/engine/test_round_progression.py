"""M4: invariants across multi-round play, and invariant detection of bad M4 states."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from chitai.engine import (
    Accepted,
    ClaimAction,
    DeclineAction,
    GameConfig,
    InvariantViolation,
    PassAction,
    Phase,
    apply_action,
    check_invariants,
    legal_actions,
    new_game,
)

from .helpers import CLAIM_POSITIONS, false_claim_ready, make_config

PLAYER_COUNTS = [4, 5, 6, 7, 8]


def random_game(config, rng, claim_probability, max_steps=3000):
    """Play random legal actions until the game ends, a valid claim is made
    (WIN_DECLARED holds until M5), or the step bound is reached (nothing in M4
    stops an endless pass cycle). Yields every accepted (before, result)."""
    result = new_game(config)
    state = result.state
    yield None, result
    for _ in range(max_steps):
        actions = legal_actions(state)
        if not actions:
            return
        claim = ClaimAction(state.decision_seat)
        decline = DeclineAction(state.decision_seat)
        passes = [a for a in actions if isinstance(a, PassAction)]
        if claim in actions and (not passes or rng.random() < claim_probability):
            action = claim
        elif decline in actions and rng.random() < 0.9:
            action = decline
        elif passes:
            action = rng.choice(passes)
        else:
            action = rng.choice(actions)
        step = apply_action(state, action)
        assert isinstance(step, Accepted), step
        yield state, step
        state = step.state


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_invariants_hold_at_every_state_across_generated_multi_round_games(n):
    rng = random.Random(4000 + n)
    rounds_seen, finished, deals_seen = set(), 0, 0
    for seed in range(60):
        config = GameConfig(num_players=n, num_rounds=n, seed=seed)
        expected_seq, prev = 0, None
        for before, step in random_game(config, rng, claim_probability=0.35):
            state = step.state
            check_invariants(state)
            # contiguous event numbering across the whole game, round boundaries included
            for event in step.events:
                assert event.seq == expected_seq
                expected_seq += 1
            assert state.next_seq == expected_seq
            # chit conservation: 4N distinct physical chits at every state
            held = [c for h in state.hands for c in h]
            assert len(held) == 4 * n and len(set(held)) == 4 * n
            assert state.initiator == state.completed_rounds % n
            assert state.attempt == 1
            if before is not None:
                # scores never rise in M4 and rounds complete one at a time
                assert all(a <= b for a, b in zip(state.scores, before.scores))
                assert state.completed_rounds - before.completed_rounds in (0, 1)
                if state.completed_rounds == before.completed_rounds + 1:
                    delta = [a - b for a, b in zip(state.scores, before.scores)]
                    assert sorted(delta) == [-(n - 1)] + [0] * (n - 1)
                    assert before.decision_seat == delta.index(-(n - 1))  # the claimant paid
                    deals_seen += 1
                else:
                    assert state.scores == before.scores
            # every completed round so far was a false claim, so exactly one penalty each
            assert -sum(state.scores) == (n - 1) * state.completed_rounds
            rounds_seen.add(state.completed_rounds)
            prev = state
        if prev.phase is Phase.GAME_OVER:
            finished += 1
            assert prev.completed_rounds == n
    assert deals_seen > 0 and finished > 0
    assert len(rounds_seen) > 1  # the generated games really did span several rounds


def _seed_with_matching_round_one_initiator(n):
    """The first seed whose round-1 deal gives the round-1 initiator (seat 1)
    four chits of one name. Deterministic search over the real seeded deals."""
    from itertools import count

    from chitai.engine import deal_round

    for seed in count():
        config = GameConfig(num_players=n, num_rounds=2 * n, seed=seed)
        deal = deal_round(config, 1, 1)
        if len({c.name for c in deal.hands[1]}) == 1:
            return seed


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_valid_claim_in_a_later_round_holds_without_win_scoring_or_completion(n):
    from chitai.engine import start_from_deal

    from .helpers import crafted_deal

    config = GameConfig(num_players=n, num_rounds=2 * n, seed=_seed_with_matching_round_one_initiator(n))
    # Round 0: a crafted all-mixed deal ends in a false claim by seat 0 ...
    state = start_from_deal(config, crafted_deal(config, matching=set())).state
    state = apply_action(state, ClaimAction(0)).state
    assert state.completed_rounds == 1 and state.scores[0] == -(n - 1)
    # ... then round 1 (the real seeded deal) opens with seat 1 holding four of a kind.
    assert state.decision_seat == 1
    result = apply_action(state, ClaimAction(1))
    won = result.state
    assert won.phase is Phase.WIN_DECLARED and won.winner == 1
    assert won.scores == state.scores  # no win or reaction score in M4 (M5)
    assert won.completed_rounds == 1  # a valid win does not complete the round in M4
    assert won.attempt == 1 and won.next_seq == state.next_seq + 1
    assert len(result.events) == 1
    check_invariants(won)
    assert legal_actions(won) == ()
    for seat in range(n):
        for action in (ClaimAction(seat), DeclineAction(seat)):
            assert apply_action(won, action).reason.value == "phase_not_accepting"


# --- invariants detect bad M4 states -----------------------------------------------------

@pytest.fixture
def state():
    return false_claim_ready(make_config(4, rounds=8), "initial", completed_round=2)


@pytest.mark.parametrize(
    "scores",
    [
        (0, 0, 0),  # wrong length
        (0, 0, 0, 0, 0),
        [0, 0, 0, 0],  # not a tuple
        (0, 0, 0, 1),  # positive (win scores are M5)
        (0, 0, 0, -1),  # not a multiple of N-1
        (0, 0, 0, -4),
        (0.0, 0, 0, 0),  # not integers
        (True, 0, 0, 0),
        (0, 0, 0, -3 * 3),  # three penalties exceed the two completed rounds
        (-3, -3, -3, 0),
    ],
)
def test_bad_score_vectors_are_rejected(state, scores):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, scores=scores))


def test_scores_within_the_completed_round_budget_are_accepted(state):
    check_invariants(replace(state, scores=(-3, -3, 0, 0)))  # two penalties, two completed rounds
    check_invariants(replace(state, scores=(0, 0, 0, 0)))  # a game started at round 2 has none
    check_invariants(replace(state, scores=(-6, 0, 0, 0)))  # a seat can be penalized twice


@pytest.mark.parametrize("bad", [-1, 8, 9, True])
def test_completed_rounds_must_stay_below_the_total_while_playing(state, bad):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, completed_rounds=bad))


def test_initiator_must_agree_with_the_completed_round_index(state):
    check_invariants(state)
    for wrong in (0, 1, 3):
        with pytest.raises(InvariantViolation):
            check_invariants(replace(state, initiator=wrong))


def _terminal():
    config = make_config(4, rounds=4)
    return apply_action(false_claim_ready(config, "initial", completed_round=3), ClaimAction(3)).state


@pytest.mark.parametrize("position", CLAIM_POSITIONS)
def test_every_claim_position_reaches_a_valid_terminal_state(position):
    config = make_config(4, rounds=4)
    state = false_claim_ready(config, position, completed_round=3)
    over = apply_action(state, ClaimAction(state.decision_seat)).state
    assert over.phase is Phase.GAME_OVER
    check_invariants(over)


@pytest.mark.parametrize(
    "change",
    [
        {"completed_rounds": 3},  # a finished game has completed every round
        {"completed_rounds": 5},
        {"initiator": 2},
        {"attempt": 2},
        {"decision_seat": 0},
        {"decision_kind": object()},
        {"winner": 0},
        {"false_claimant": 0},
        {"initial_claims_resolved": 1},
        {"scores": (0, 0, 0, 0, 0)},
        {"scores": (0, 0, 0, 3)},
        {"scores": (-3, -3, -3, -3, -3)},
    ],
)
def test_a_corrupted_terminal_state_is_detected(change):
    terminal = _terminal()
    check_invariants(terminal)
    with pytest.raises(InvariantViolation):
        check_invariants(replace(terminal, **change))


def test_the_terminal_state_must_keep_a_claim_time_hand_shape():
    terminal = _terminal()
    # move one chit from seat 1 to seat 0: sizes become [5, 3, 4, 4] with a 3 and a 5 -> allowed shape
    moved = list(terminal.hands)
    moved[0] = moved[0] + (moved[1][0],)
    moved[1] = moved[1][1:]
    check_invariants(replace(terminal, hands=tuple(moved)))
    # moving a second chit gives [6, 2, 4, 4]: not any claim-time shape
    moved[0] = moved[0] + (moved[1][0],)
    moved[1] = moved[1][1:]
    with pytest.raises(InvariantViolation):
        check_invariants(replace(terminal, hands=tuple(moved)))


def test_chit_conservation_is_still_enforced_in_the_terminal_state():
    terminal = _terminal()
    duplicated = list(terminal.hands)
    duplicated[1] = (duplicated[0][0],) + duplicated[1][1:]
    with pytest.raises(InvariantViolation):
        check_invariants(replace(terminal, hands=tuple(duplicated)))


def test_a_game_over_phase_cannot_be_reached_before_the_last_round(state):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, phase=Phase.GAME_OVER))
