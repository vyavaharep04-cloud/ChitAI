from collections import Counter

import pytest

from chitai.engine import CHIT_NAMES, Chit, build_deck, chit_names_for


def test_eight_unique_fixed_names():
    assert len(CHIT_NAMES) == 8
    assert len(set(CHIT_NAMES)) == 8


@pytest.mark.parametrize("n", range(4, 9))
def test_names_in_play(n):
    assert chit_names_for(n) == CHIT_NAMES[:n]
    assert len(set(chit_names_for(n))) == n


@pytest.mark.parametrize("n", range(4, 9))
def test_deck_has_4n_chits_with_four_of_each_name(n):
    deck = build_deck(n)
    assert len(deck) == 4 * n
    counts = Counter(c.name for c in deck)
    assert set(counts) == set(chit_names_for(n))
    assert all(v == 4 for v in counts.values())


@pytest.mark.parametrize("n", range(4, 9))
def test_physical_instances_are_unique(n):
    deck = build_deck(n)
    assert len(set(deck)) == len(deck)
    assert {c.copy for c in deck} == {0, 1, 2, 3}


def test_deck_is_deterministic_and_unshuffled():
    assert build_deck(5) == build_deck(5)
    assert build_deck(4)[:4] == tuple(Chit(CHIT_NAMES[0], i) for i in range(4))


def test_matching_uses_name_only():
    assert Chit("Sun", 0).matches(Chit("Sun", 3))
    assert not Chit("Sun", 0).matches(Chit("Moon", 0))
    assert Chit("Sun", 0) != Chit("Sun", 3)  # distinct physical instances


@pytest.mark.parametrize("n", [3, 9, 0, -1, 4.0, "4", None, True])
def test_invalid_player_count_rejected(n):
    with pytest.raises(ValueError):
        build_deck(n)
    with pytest.raises(ValueError):
        chit_names_for(n)
