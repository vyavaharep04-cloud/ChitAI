"""M3: invariants for the three-chit initiator / five-chit receiver states, and
randomized play checked against an independent oracle of the §3A.4 rules."""

import random
from collections import Counter
from dataclasses import replace

import pytest

from chitai.engine import (
    Accepted,
    ClaimAction,
    DecisionKind,
    GameConfig,
    InvariantViolation,
    PassAction,
    Phase,
    apply_action,
    check_invariants,
    legal_actions,
    new_game,
)

from .helpers import decline_to_passing, do_pass, make_config, to_passing

PLAYER_COUNTS = [4, 5, 6, 7, 8]


@pytest.fixture
def first_pass():
    return to_passing(make_config(4))


@pytest.fixture
def receive(first_pass):
    state, _ = do_pass(first_pass)  # seat 0 holds 3, seat 1 holds 5
    return state


@pytest.fixture
def returned(first_pass):
    state = first_pass
    for _ in range(4):
        state, _ = do_pass(state)
    return state


def move_chit(state, src, dst):
    """Corrupt `state` by moving one chit between hands without any engine step."""
    hands = [list(h) for h in state.hands]
    hands[dst].append(hands[src].pop())
    return replace(state, hands=tuple(tuple(h) for h in hands))


def test_engine_made_passing_states_pass_the_checker(first_pass, receive, returned):
    for state in (first_pass, receive, returned):
        check_invariants(state)


# --- hand-size corruption -------------------------------------------------------------

def test_first_pass_state_with_a_three_and_a_five_is_rejected(first_pass):
    with pytest.raises(InvariantViolation):
        check_invariants(move_chit(first_pass, 0, 1))


def test_receive_state_requires_initiator_three_and_receiver_five(receive):
    # initiator back to four, receiver back to four -> a chit has vanished
    with pytest.raises(InvariantViolation):
        check_invariants(replace(receive, hands=tuple(h[:4] for h in receive.hands)))
    # a bystander holds the extra chit instead of the receiver
    with pytest.raises(InvariantViolation):
        check_invariants(move_chit(move_chit(receive, 1, 3), 2, 1))


def test_receive_state_with_the_wrong_decision_seat_for_its_hands_is_rejected(receive):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(receive, decision_seat=2))  # seat 1 holds the five


def test_return_state_with_a_leftover_three_five_split_is_rejected(returned):
    with pytest.raises(InvariantViolation):
        check_invariants(move_chit(returned, 0, 1))


# --- decision-point consistency -----------------------------------------------------------

def test_receive_kind_at_the_initiator_is_rejected(receive):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(receive, decision_seat=receive.initiator))


def test_return_kind_at_a_non_initiator_is_rejected(returned):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(returned, decision_seat=1))


def test_first_pass_kind_at_a_non_initiator_is_rejected(first_pass):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(first_pass, decision_seat=2))


def test_initial_claim_kind_cannot_appear_during_passing(first_pass):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(first_pass, decision_kind=DecisionKind.INITIAL_CLAIM))


def test_missing_decision_point_during_passing_is_rejected(receive):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(receive, decision_seat=None))


def test_outcome_fields_cannot_be_set_while_passing(receive):
    for change in (
        {"claim_decision_kind": DecisionKind.NON_INITIATOR_RECEIVE},
        {"winner": 1},
        {"false_claimant": 1},
    ):
        with pytest.raises(InvariantViolation):
            check_invariants(replace(receive, **change))


# --- passing-phase outcomes ------------------------------------------------------------------

def holding(state, phase, claimant, kind):
    return replace(
        state,
        phase=phase,
        decision_seat=None,
        decision_kind=None,
        winner=claimant if phase is Phase.WIN_DECLARED else None,
        false_claimant=claimant if phase is Phase.FALSE_CLAIM else None,
        claim_decision_kind=kind,
    )


def test_outcome_without_a_claim_decision_kind_is_rejected(receive):
    bad = holding(receive, Phase.FALSE_CLAIM, 1, None)
    with pytest.raises(InvariantViolation):
        check_invariants(bad)


def test_win_in_a_receive_state_needs_four_of_five(receive):
    # `receive` is the fixture's mixed hand: a recorded win there is inconsistent.
    assert max(Counter(c.name for c in receive.hands[1]).values()) < 4
    with pytest.raises(InvariantViolation):
        check_invariants(holding(receive, Phase.WIN_DECLARED, 1, DecisionKind.NON_INITIATOR_RECEIVE))
    check_invariants(holding(receive, Phase.FALSE_CLAIM, 1, DecisionKind.NON_INITIATOR_RECEIVE))


def test_receiver_claim_outcome_must_come_from_the_five_chit_seat(receive):
    with pytest.raises(InvariantViolation):
        check_invariants(holding(receive, Phase.FALSE_CLAIM, 2, DecisionKind.NON_INITIATOR_RECEIVE))
    with pytest.raises(InvariantViolation):  # the initiator never claims while holding three
        check_invariants(holding(receive, Phase.FALSE_CLAIM, 0, DecisionKind.NON_INITIATOR_RECEIVE))


def test_return_claim_outcome_must_come_from_the_initiator(returned):
    mixed = len({c.name for c in returned.hands[0]}) > 1
    assert mixed
    check_invariants(holding(returned, Phase.FALSE_CLAIM, 0, DecisionKind.INITIATOR_RETURN))
    with pytest.raises(InvariantViolation):
        check_invariants(holding(returned, Phase.FALSE_CLAIM, 2, DecisionKind.INITIATOR_RETURN))
    with pytest.raises(InvariantViolation):  # a false claimant must not actually match
        check_invariants(holding(returned, Phase.WIN_DECLARED, 0, DecisionKind.INITIATOR_RETURN))


def test_return_outcome_with_a_receive_shaped_hand_set_is_rejected(receive):
    with pytest.raises(InvariantViolation):
        check_invariants(holding(receive, Phase.FALSE_CLAIM, 0, DecisionKind.INITIATOR_RETURN))


def test_duplicate_physical_chit_during_passing_is_rejected(receive):
    hands = [list(h) for h in receive.hands]
    hands[2][0] = hands[1][0]
    with pytest.raises(InvariantViolation):
        check_invariants(replace(receive, hands=tuple(tuple(h) for h in hands)))


# --- randomized play against an independent oracle ---------------------------------------------

def oracle_expected_sizes(n, initiator, decision_seat, kind):
    sizes = [4] * n
    if kind is DecisionKind.NON_INITIATOR_RECEIVE:
        sizes[initiator] = 3
        sizes[decision_seat] = 5
    return sizes


def oracle_claim_is_valid(hand):
    counts = Counter(c.name for c in hand).values()
    return max(counts) == 4  # 4 of 4 for the initiator, 4 of 5 for a receiver


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_random_play_keeps_the_hand_size_table_and_judges_claims_correctly(n):
    rng = random.Random(900 + n)
    claims_seen = {True: 0, False: 0}
    for seed in range(60):
        state = new_game(GameConfig(n, n, seed=seed)).state
        state = decline_to_passing(state) if state.phase is Phase.INITIAL_CLAIMS else state
        for _ in range(400):
            if state.phase is not Phase.PASSING:
                break
            assert state.decision_kind in (
                DecisionKind.INITIATOR_FIRST_PASS,
                DecisionKind.NON_INITIATOR_RECEIVE,
                DecisionKind.INITIATOR_RETURN,
            )
            assert [len(h) for h in state.hands] == oracle_expected_sizes(
                n, state.initiator, state.decision_seat, state.decision_kind
            )
            actions = legal_actions(state)
            can_claim = ClaimAction(state.decision_seat) in actions
            assert can_claim == (state.decision_kind is not DecisionKind.INITIATOR_FIRST_PASS)
            if can_claim and rng.random() < 0.15:
                hand = state.hands[state.decision_seat]
                result = apply_action(state, ClaimAction(state.decision_seat))
                assert isinstance(result, Accepted)
                expected = oracle_claim_is_valid(hand)
                claims_seen[expected] += 1
                assert result.state.phase is (Phase.WIN_DECLARED if expected else Phase.FALSE_CLAIM)
                assert result.state.scores == (0,) * n and result.state.completed_rounds == 0
                state = result.state
                break
            passes = [a for a in actions if isinstance(a, PassAction)]
            before_holder = state.decision_seat
            state = apply_action(state, rng.choice(passes)).state
            assert state.decision_seat == (before_holder + 1) % n
            check_invariants(state)
        held = [c for h in state.hands for c in h]
        assert len(held) == 4 * n and len(set(held)) == 4 * n
    assert claims_seen[True] + claims_seen[False] > 0
