"""Invariant checker: accepts valid states, rejects each kind of corruption."""

from dataclasses import replace

import pytest

from chitai.engine import (
    Chit,
    DecisionKind,
    InvariantViolation,
    Phase,
    check_invariants,
)

from .helpers import make_config, start


@pytest.fixture
def state():
    return start(make_config(4), matching={0})


def test_valid_start_state_passes(state):
    check_invariants(state)


def _swap_in(state, seat, index, chit):
    hand = list(state.hands[seat])
    hand[index] = chit
    hands = list(state.hands)
    hands[seat] = tuple(hand)
    return replace(state, hands=tuple(hands))


def test_duplicate_physical_chit_detected(state):
    bad = _swap_in(state, 1, 0, state.hands[0][0])
    with pytest.raises(InvariantViolation):
        check_invariants(bad)


def test_chit_from_outside_the_deck_detected(state):
    bad = _swap_in(state, 1, 0, Chit("Stone", 0))  # 4-player games never use "Stone"
    with pytest.raises(InvariantViolation):
        check_invariants(bad)


def test_wrong_hand_size_detected(state):
    hands = list(state.hands)
    hands[1] = hands[1][:3]
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, hands=tuple(hands)))


def test_extra_chit_in_a_hand_detected(state):
    hands = list(state.hands)
    hands[1] = hands[1] + (hands[2][0],)
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, hands=tuple(hands)))


def test_missing_hand_detected(state):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, hands=state.hands[:-1]))


def test_decision_seat_must_follow_clockwise_order(state):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, decision_seat=2))


def test_wrong_initiator_for_round_detected(state):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, initiator=1, decision_seat=1))


def test_passing_phase_requires_all_opportunities_resolved(state):
    bad = replace(
        state,
        phase=Phase.PASSING,
        decision_kind=DecisionKind.INITIATOR_FIRST_PASS,
        decision_seat=state.initiator,
    )
    with pytest.raises(InvariantViolation):
        check_invariants(bad)


def test_win_declared_requires_matching_hand(state):
    bad = replace(
        state,
        phase=Phase.WIN_DECLARED,
        decision_seat=None,
        decision_kind=None,
        initial_claims_resolved=2,
        winner=1,  # seat 1 does not hold a matching hand
    )
    with pytest.raises(InvariantViolation):
        check_invariants(bad)


def test_false_claim_requires_non_matching_hand(state):
    bad = replace(
        state,
        phase=Phase.FALSE_CLAIM,
        decision_seat=None,
        decision_kind=None,
        initial_claims_resolved=1,
        false_claimant=0,  # seat 0 actually matches
    )
    with pytest.raises(InvariantViolation):
        check_invariants(bad)


def test_outcome_fields_must_not_be_set_while_waiting(state):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, winner=0))
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, false_claimant=0))


@pytest.mark.parametrize("scores", [(0, 0, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0.0), (0, 0, 0, True), [0, 0, 0, 0]])
def test_bad_scores_detected(state, scores):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, scores=scores))


@pytest.mark.parametrize("attempt", [0, -1, 1.5, True])
def test_bad_attempt_detected(state, attempt):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, attempt=attempt))


@pytest.mark.parametrize("rounds", [-1, 4, 99])
def test_completed_rounds_out_of_range_detected(state, rounds):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, completed_rounds=rounds))


def test_negative_next_seq_detected(state):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, next_seq=-1))
