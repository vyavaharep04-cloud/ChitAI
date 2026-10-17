"""False-claim scoring rule (§3A.5). M4."""

import pytest

from chitai.engine import false_claim_penalty, false_claim_score_changes

PLAYER_COUNTS = [4, 5, 6, 7, 8]


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_penalty_is_n_minus_one(n):
    assert false_claim_penalty(n) == n - 1


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_only_the_claimant_loses_points(n):
    for claimant in range(n):
        changes = false_claim_score_changes(n, claimant)
        assert len(changes) == n
        assert changes[claimant] == -(n - 1)
        assert all(c == 0 for seat, c in enumerate(changes) if seat != claimant)
        assert sum(changes) == -(n - 1)  # no winner or reaction score exists


@pytest.mark.parametrize("n", [-1, 0, 3, 9, True, 4.0, "4", None])
def test_penalty_rejects_invalid_player_counts(n):
    with pytest.raises(ValueError):
        false_claim_penalty(n)


@pytest.mark.parametrize("claimant", [-1, 4, 99, True, 1.0, "1", None])
def test_score_changes_reject_invalid_claimants(claimant):
    with pytest.raises(ValueError):
        false_claim_score_changes(4, claimant)
