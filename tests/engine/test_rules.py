"""Pure rule functions: claim order, claim validity, seat validation, legal actions."""

import pytest

from chitai.engine import (
    Chit,
    ClaimAction,
    DeclineAction,
    Phase,
    initial_claim_order,
    is_valid_initial_claim,
    is_valid_seat,
    legal_actions,
)

from .helpers import make_config, start


@pytest.mark.parametrize("n", range(4, 9))
def test_order_starts_at_initiator_and_covers_each_seat_once(n):
    for initiator in range(n):
        order = initial_claim_order(n, initiator)
        assert order[0] == initiator
        assert sorted(order) == list(range(n))
        for a, b in zip(order, order[1:]):
            assert b == (a + 1) % n  # clockwise, wrapping


def test_order_examples_including_wraparound():
    assert initial_claim_order(4, 0) == (0, 1, 2, 3)
    assert initial_claim_order(4, 2) == (2, 3, 0, 1)
    assert initial_claim_order(8, 7) == (7, 0, 1, 2, 3, 4, 5, 6)


def _hand(*names):
    return tuple(Chit(name, i) for i, name in enumerate(names))


def test_valid_initial_claim_requires_all_four_same_name():
    assert is_valid_initial_claim(_hand("Sun", "Sun", "Sun", "Sun"))


@pytest.mark.parametrize(
    "names",
    [
        ("Sun", "Sun", "Sun", "Moon"),  # three of a kind is not enough
        ("Sun", "Sun", "Moon", "Moon"),
        ("Sun", "Moon", "Star", "Cloud"),
        ("Moon", "Sun", "Sun", "Sun"),  # position of the odd chit is irrelevant
    ],
)
def test_non_matching_hands_are_invalid(names):
    assert not is_valid_initial_claim(_hand(*names))


def test_matching_ignores_copy_index():
    hand = (Chit("Sun", 3), Chit("Sun", 0), Chit("Sun", 2), Chit("Sun", 1))
    assert is_valid_initial_claim(hand)


@pytest.mark.parametrize("size", [0, 1, 3, 5])
def test_claim_judged_only_on_four_chits(size):
    with pytest.raises(ValueError):
        is_valid_initial_claim(tuple(Chit("Sun", i % 4) for i in range(size)))


def test_is_valid_seat_boundaries():
    config = make_config(4)
    assert is_valid_seat(config, 0) and is_valid_seat(config, 3)
    for bad in (-1, 4, 100, True, False, 1.0, "1", None, (1,)):
        assert not is_valid_seat(config, bad)


def test_legal_actions_only_for_decision_seat_in_initial_phase():
    state = start(make_config(5))
    assert legal_actions(state) == (ClaimAction(0), DeclineAction(0))


def test_legal_actions_offer_claim_even_when_hand_does_not_match():
    # §3A.3: opportunity does not depend on the hand matching.
    state = start(make_config(4), matching=set())
    assert ClaimAction(state.decision_seat) in legal_actions(state)


def test_legal_actions_empty_outside_initial_phase():
    from dataclasses import replace

    state = start(make_config(4))
    for phase in (Phase.PASSING, Phase.WIN_DECLARED, Phase.FALSE_CLAIM):
        assert legal_actions(replace(state, phase=phase)) == ()
