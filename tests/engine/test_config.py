import math

import pytest

from chitai.engine import ConfigError, GameConfig


def make(**overrides):
    params = dict(num_players=4, num_rounds=4, seed=1)
    params.update(overrides)
    return GameConfig(**params)


@pytest.mark.parametrize("n", [4, 5, 6, 7, 8])
def test_valid_player_counts(n):
    assert make(num_players=n, num_rounds=n).num_players == n


@pytest.mark.parametrize("n", [-4, 0, 1, 2, 3, 9, 100])
def test_player_count_out_of_range_rejected(n):
    with pytest.raises(ConfigError):
        make(num_players=n, num_rounds=max(abs(n), 1))


@pytest.mark.parametrize("n", [4.0, "4", None, True])
def test_player_count_must_be_int(n):
    with pytest.raises(ConfigError):
        make(num_players=n)


@pytest.mark.parametrize("n,k", [(4, 1), (4, 2), (5, 3), (8, 5)])
def test_round_count_multiples_accepted(n, k):
    assert make(num_players=n, num_rounds=n * k).num_rounds == n * k


@pytest.mark.parametrize("n,rounds", [(4, 0), (4, -4), (4, 1), (4, 6), (5, 4), (8, 12)])
def test_round_count_must_be_positive_multiple_of_n(n, rounds):
    with pytest.raises(ConfigError):
        make(num_players=n, num_rounds=rounds)


@pytest.mark.parametrize("rounds", [4.0, "4", None, True])
def test_round_count_must_be_int(rounds):
    with pytest.raises(ConfigError):
        make(num_rounds=rounds)


@pytest.mark.parametrize("timeout", [0.5, 1, 14.9, 15, 15.0])
def test_timeout_valid(timeout):
    assert make(pass_timeout_seconds=timeout).pass_timeout_seconds == timeout


def test_timeout_defaults_to_maximum():
    assert make().pass_timeout_seconds == 15.0


@pytest.mark.parametrize("timeout", [0, -1, 15.01, 16, 60, math.inf, math.nan, True, "5", None])
def test_timeout_invalid(timeout):
    with pytest.raises(ConfigError):
        make(pass_timeout_seconds=timeout)


@pytest.mark.parametrize("seed", [0, 1, -7, 2**70])
def test_seed_valid(seed):
    assert make(seed=seed).seed == seed


@pytest.mark.parametrize("seed", [1.5, "1", None, True])
def test_seed_must_be_int(seed):
    with pytest.raises(ConfigError):
        make(seed=seed)


def test_config_is_immutable():
    cfg = make()
    with pytest.raises(Exception):
        cfg.num_players = 5


def test_config_error_is_value_error():
    assert issubclass(ConfigError, ValueError)
