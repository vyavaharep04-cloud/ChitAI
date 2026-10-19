"""Shared helpers for simulation tests. Builds records with the engine's own scoring functions."""

from __future__ import annotations

from chitai.engine import (
    ROUND_OUTCOME_FALSE_CLAIM,
    ROUND_OUTCOME_VALID_WIN,
    false_claim_score_changes,
    valid_win_score_changes,
)
from chitai.simulation import (
    STATUS_COMPLETED,
    GameResult,
    RoundResult,
    SeatResult,
    final_ranks,
    tie_flags,
)

# Deliberately small, arbitrary values: the caps have no default and these are not proposals.
CAP_DRAWS = 3
CAP_ACTIONS = 500


def config_dict(**overrides):
    """A valid configuration dictionary (4 players, 4 rounds) with overrides."""
    data = {
        "lineup": [{"agent_type": "rulebot", "agent_config": {"avoid_draw": True}}] * 4,
        "num_players": 4,
        "num_rounds": 4,
        "batch_seed": 2026,
        "game_count": 8,
        "max_draw_restarts_per_round": CAP_DRAWS,
        "max_actions_per_attempt": CAP_ACTIONS,
    }
    data.update(overrides)
    return data


def win_round(n: int, index: int, claimant: int, order: tuple[int, ...], attempts: int = 1) -> RoundResult:
    return RoundResult(
        index, ROUND_OUTCOME_VALID_WIN, index % n, claimant, attempts, order,
        valid_win_score_changes(n, claimant, order),
    )  # fmt: skip


def false_round(n: int, index: int, claimant: int, attempts: int = 1) -> RoundResult:
    return RoundResult(
        index, ROUND_OUTCOME_FALSE_CLAIM, index % n, claimant, attempts, (),
        false_claim_score_changes(n, claimant),
    )  # fmt: skip


def seats_for(rounds, n: int, status: str, counters: dict | None = None) -> tuple[SeatResult, ...]:
    """SeatResults consistent with `rounds` (scores and counts summed from them)."""
    scores = [sum(r.score_changes[s] for r in rounds) for s in range(n)]
    ranks = final_ranks(status, scores)
    ties = tie_flags(ranks)
    return tuple(
        SeatResult(
            seat=s, lineup_index=s, agent_type="rulebot", agent_version="1",
            agent_config_json="{}", score=scores[s], rank=ranks[s], tied=ties[s],
            rounds_won=sum(r.outcome == ROUND_OUTCOME_VALID_WIN and r.claimant == s for r in rounds),
            false_claims=sum(r.outcome == ROUND_OUTCOME_FALSE_CLAIM and r.claimant == s for r in rounds),
            **(counters or {}).get(s, {}),
        )
        for s in range(n)
    )  # fmt: skip


def four_player_rounds():
    """Four completed rounds (one with a redeal). Totals: seat 0=10, 1=9, 2=2, 3=6."""
    return (
        win_round(4, 0, 0, (1, 2, 3)),  # seat 0 +4, 1 +3, 2 +2, 3 +1
        win_round(4, 1, 1, (0, 2, 3), attempts=2),  # seat 1 +4, 0 +3, 2 +2, 3 +1
        false_round(4, 2, 2),  # seat 2 -3
        win_round(4, 3, 3, (0, 1, 2)),  # seat 3 +4, 0 +3, 1 +2, 2 +1
    )


def completed_game(**overrides) -> GameResult:
    """A consistent completed 4-player game. Scores: seat 0=10, 1=9, 2=2, 3=6."""
    rounds = four_player_rounds()
    fields = dict(
        game_index=0, game_seed=99, status=STATUS_COMPLETED, num_players=4, num_rounds=4,
        completed_rounds=4, stopped_attempt=None, draw_restarts=1, actions=321,
        seats=seats_for(rounds, 4, STATUS_COMPLETED), rounds=rounds, winning_seats=(0,),
    )  # fmt: skip
    fields.update(overrides)
    return GameResult(**fields)


def stopped_game(status: str, **overrides) -> GameResult:
    """A consistent stopped 4-player game after two completed rounds, in attempt 3."""
    rounds = four_player_rounds()[:2]
    fields = dict(
        game_index=1, game_seed=100, status=status, num_players=4, num_rounds=4,
        completed_rounds=2, stopped_attempt=3, draw_restarts=1 + 2, actions=77,
        seats=seats_for(rounds, 4, status), rounds=rounds, winning_seats=(),
    )  # fmt: skip
    fields.update(overrides)
    return GameResult(**fields)
