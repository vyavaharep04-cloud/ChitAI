from collections import Counter

import pytest

from chitai.engine import GameConfig, build_deck, deal_round, make_rng


def cfg(n=4, rounds=None, seed=123):
    return GameConfig(num_players=n, num_rounds=rounds or n, seed=seed)


@pytest.mark.parametrize("n", range(4, 9))
def test_every_player_gets_four_and_all_chits_dealt_once(n):
    d = deal_round(cfg(n), 0)
    assert len(d.hands) == n
    assert all(len(h) == 4 for h in d.hands)
    dealt = [c for h in d.hands for c in h]
    assert len(dealt) == 4 * n
    assert sorted(dealt) == sorted(build_deck(n))  # exact multiset, no loss or duplication


@pytest.mark.parametrize("n", range(4, 9))
def test_each_name_appears_exactly_four_times(n):
    d = deal_round(cfg(n), 0)
    counts = Counter(c.name for h in d.hands for c in h)
    assert len(counts) == n and all(v == 4 for v in counts.values())


def test_same_seed_round_attempt_reproduces_deal():
    assert deal_round(cfg(), 2, 1) == deal_round(cfg(), 2, 1)


def test_deal_is_order_independent():
    # Stateless derivation: dealing other rounds first must not change a deal.
    c = cfg()
    expected = deal_round(c, 3, 1)
    for r in (0, 1, 2):
        deal_round(c, r, 1)
    assert deal_round(c, 3, 1) == expected


def test_different_seeds_differ():
    assert deal_round(cfg(seed=1), 0).hands != deal_round(cfg(seed=2), 0).hands


def test_different_rounds_differ():
    c = cfg(rounds=8)
    assert deal_round(c, 0).hands != deal_round(c, 1).hands


def test_redeal_after_draw_is_fresh_but_same_initiator():
    c = cfg()
    first, second = deal_round(c, 1, 1), deal_round(c, 1, 2)
    assert first.hands != second.hands
    assert first.initiator == second.initiator
    assert (first.completed_round, second.completed_round) == (1, 1)
    assert (first.attempt, second.attempt) == (1, 2)


def test_actually_shuffled():
    d = deal_round(cfg(), 0)
    assert tuple(c for h in d.hands for c in h) != build_deck(4)


def test_does_not_disturb_other_streams():
    c = cfg()
    expected = deal_round(c, 0)
    timeouts = make_rng(c.seed, "timeout", 0, 1)
    for _ in range(50):
        timeouts.random()
    assert deal_round(c, 0) == expected


def test_deal_contents_are_immutable_tuples():
    d = deal_round(cfg(), 0)
    assert isinstance(d.hands, tuple) and all(isinstance(h, tuple) for h in d.hands)


def test_default_attempt_is_first():
    assert deal_round(cfg(), 0) == deal_round(cfg(), 0, 1)


@pytest.mark.parametrize("bad", [-1, 4, 5, 1.0, "0", None, True])
def test_invalid_round_rejected(bad):
    with pytest.raises(ValueError):
        deal_round(cfg(), bad)


@pytest.mark.parametrize("bad", [0, -1, 1.0, "1", None, True])
def test_invalid_attempt_rejected(bad):
    with pytest.raises(ValueError):
        deal_round(cfg(), 0, bad)
