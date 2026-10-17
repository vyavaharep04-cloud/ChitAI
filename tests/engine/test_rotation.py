import pytest

from chitai.engine import GameConfig, deal_round, initiator_for_round


def cfg(n, k=1):
    return GameConfig(num_players=n, num_rounds=n * k, seed=5)


@pytest.mark.parametrize("n", range(4, 9))
def test_first_initiator_is_seat_zero(n):
    assert initiator_for_round(cfg(n), 0) == 0


@pytest.mark.parametrize("n", range(4, 9))
def test_rotates_one_seat_clockwise_with_wraparound(n):
    c = cfg(n, 2)
    assert [initiator_for_round(c, r) for r in range(2 * n)] == list(range(n)) * 2


@pytest.mark.parametrize("n", range(4, 9))
def test_full_rotation_gives_every_seat_equal_turns(n):
    c = cfg(n, 3)
    seats = [initiator_for_round(c, r) for r in range(c.num_rounds)]
    assert all(seats.count(s) == 3 for s in range(n))


def test_initiator_depends_only_on_completed_round_not_attempt():
    c = cfg(5)
    for r in range(5):
        assert {deal_round(c, r, a).initiator for a in (1, 2, 3)} == {r}


@pytest.mark.parametrize("bad", [-1, 4, 1.0, "0", None, True])
def test_invalid_round_rejected(bad):
    with pytest.raises(ValueError):
        initiator_for_round(cfg(4), bad)
