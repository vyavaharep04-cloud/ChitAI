"""Result records, termination statuses and shared competition ranking (M8 Stage 2)."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import replace

import pytest

from chitai.engine import ROUND_OUTCOME_FALSE_CLAIM, ROUND_OUTCOME_VALID_WIN
from chitai.simulation import (
    STATUS_ACTION_CAP_REACHED,
    STATUS_AGENT_FAULT_UNRESOLVABLE,
    STATUS_COMPLETED,
    STATUS_DRAW_CAP_REACHED,
    STOPPED_STATUSES,
    TERMINATION_STATUSES,
    GameResult,
    ResultError,
    RoundResult,
    SeatResult,
    competition_ranks,
    final_ranks,
    tie_flags,
)

from .support import completed_game, false_round, four_player_rounds, seats_for, stopped_game, win_round

# --- statuses ----------------------------------------------------------------------------


def test_the_termination_statuses_are_the_four_documented_strings():
    assert TERMINATION_STATUSES == (
        "completed",
        "draw_cap_reached",
        "action_cap_reached",
        "agent_fault_unresolvable",
    )
    assert (STATUS_COMPLETED, STATUS_DRAW_CAP_REACHED) == ("completed", "draw_cap_reached")
    assert (STATUS_ACTION_CAP_REACHED, STATUS_AGENT_FAULT_UNRESOLVABLE) == (
        "action_cap_reached",
        "agent_fault_unresolvable",
    )
    assert STOPPED_STATUSES == TERMINATION_STATUSES[1:] and STATUS_COMPLETED not in STOPPED_STATUSES


# --- shared competition ranking (D7) -----------------------------------------------------


@pytest.mark.parametrize(
    ("scores", "ranks"),
    [
        ((10, 5, 5, 1), (1, 2, 2, 4)),  # the canonical 1,2,2,4
        ((5, 5, 5, 5), (1, 1, 1, 1)),
        ((7, 7, 3, 3), (1, 1, 3, 3)),
        ((1, 5, 10, 5), (4, 2, 1, 2)),  # seat order is preserved
        ((9, 7, 5, 3), (1, 2, 3, 4)),
        ((3, 3, 3, 1, 0), (1, 1, 1, 4, 5)),
        ((0, -3, -3, 6), (2, 3, 3, 1)),  # negative scores from false claims
        ((-1, -1, -1, -1, -1, -1, -1, -1), (1,) * 8),
        ((4,), (1,)),
        ((), ()),
    ],
)
def test_competition_ranks(scores, ranks):
    assert competition_ranks(scores) == ranks


def test_ranks_do_not_depend_on_the_container_type_or_mutate_it():
    scores = [10, 5, 5, 1]
    assert competition_ranks(scores) == competition_ranks(tuple(scores)) == (1, 2, 2, 4)
    assert scores == [10, 5, 5, 1]


def test_a_tie_for_first_is_never_broken():
    ranks = competition_ranks((12, 12, 3, 0))
    assert ranks == (1, 1, 3, 4)
    assert tie_flags(ranks) == (True, True, False, False)


@pytest.mark.parametrize("bad", ([1, 2.0], [1, True], [1, "2"], [None]))
def test_scores_must_be_integers(bad):
    with pytest.raises(ResultError):
        competition_ranks(bad)


def test_tie_flags():
    assert tie_flags((1, 2, 2, 4)) == (False, True, True, False)
    assert tie_flags((1, 1, 1, 1)) == (True, True, True, True)
    assert tie_flags((None, None, None)) == (None, None, None)
    assert tie_flags(()) == ()


# --- the rule that stopped games carry no final ranks (D1, D8) ---------------------------


def test_a_completed_game_gets_ranks_and_every_stopped_status_gets_none():
    scores = (10, 5, 5, 1)
    assert final_ranks(STATUS_COMPLETED, scores) == (1, 2, 2, 4)
    for status in STOPPED_STATUSES:
        assert final_ranks(status, scores) == (None, None, None, None)


def test_final_ranks_rejects_an_unknown_status():
    with pytest.raises(ResultError):
        final_ranks("finished", (1, 2))


# --- records -----------------------------------------------------------------------------


def test_a_completed_game_record_is_consistent_and_keeps_raw_scores():
    game = completed_game()
    assert game.completed and game.status == STATUS_COMPLETED
    assert [s.score for s in game.seats] == [10, 9, 2, 6]
    assert [s.rank for s in game.seats] == [1, 2, 4, 3]
    assert [s.tied for s in game.seats] == [False] * 4
    assert game.winning_seats == (0,) and game.tie_for_first is False
    assert [r.draw_restarts for r in game.rounds] == [0, 1, 0, 0]
    assert [(s.rounds_won, s.false_claims) for s in game.seats] == [(1, 0), (1, 0), (0, 1), (1, 0)]


def test_a_tie_for_first_is_recorded_explicitly_and_not_broken():
    rounds = (
        win_round(4, 0, 0, (1, 2, 3)),  # seat 0 +4 ... seat 1 +3
        win_round(4, 1, 1, (0, 2, 3)),  # seat 1 +4, seat 0 +3
        false_round(4, 2, 2),
        false_round(4, 3, 3),
    )
    seats = seats_for(rounds, 4, STATUS_COMPLETED)
    assert [s.score for s in seats] == [7, 7, 1, -1]
    game = completed_game(rounds=rounds, seats=seats, winning_seats=(0, 1), draw_restarts=0)
    assert [s.rank for s in game.seats] == [1, 1, 3, 4]
    assert [s.tied for s in game.seats] == [True, True, False, False]
    assert game.winning_seats == (0, 1) and game.tie_for_first is True


@pytest.mark.parametrize("status", STOPPED_STATUSES)
def test_a_stopped_game_has_no_ranks_ties_or_winners_but_keeps_raw_scores(status):
    game = stopped_game(status)
    assert not game.completed and game.tie_for_first is None
    assert all(s.rank is None and s.tied is None for s in game.seats)
    assert game.winning_seats == ()
    assert [s.score for s in game.seats] == [7, 7, 4, 2]  # unaltered totals of the two rounds played
    assert game.completed_rounds < game.num_rounds and game.stopped_attempt == 3


@pytest.mark.parametrize("status", STOPPED_STATUSES)
def test_a_stopped_game_cannot_be_given_ranks_a_tie_flag_or_winners(status):
    ranked = seats_for(four_player_rounds()[:2], 4, STATUS_COMPLETED)
    with pytest.raises(ResultError):
        stopped_game(status, seats=ranked)
    one_rank = (replace(stopped_game(status).seats[0], rank=1, tied=False),) + stopped_game(status).seats[1:]
    with pytest.raises(ResultError):
        stopped_game(status, seats=one_rank)
    with pytest.raises(ResultError):
        stopped_game(status, winning_seats=(0,))


def test_a_stopped_game_cannot_claim_all_its_rounds_and_a_completed_one_must_have_them():
    with pytest.raises(ResultError):
        stopped_game(STATUS_DRAW_CAP_REACHED, completed_rounds=4, rounds=four_player_rounds(), draw_restarts=1 + 2)
    with pytest.raises(ResultError):
        completed_game(rounds=four_player_rounds()[:3], completed_rounds=3)
    with pytest.raises(ResultError):
        completed_game(stopped_attempt=2)


def test_a_completed_game_must_carry_the_competition_ranks_and_winners():
    game = completed_game()
    wrong_rank = (replace(game.seats[2], rank=3),) + ()
    seats = game.seats[:2] + wrong_rank + game.seats[3:]
    with pytest.raises(ResultError):
        completed_game(seats=seats)
    with pytest.raises(ResultError):
        completed_game(winning_seats=(1,))
    with pytest.raises(ResultError):
        completed_game(winning_seats=())
    flags = tuple(replace(s, tied=True) for s in game.seats)
    with pytest.raises(ResultError):
        completed_game(seats=flags)
    unranked = tuple(replace(s, rank=None, tied=None) for s in game.seats)
    with pytest.raises(ResultError):
        completed_game(seats=unranked)


def test_scores_must_reconcile_with_the_round_records():
    game = completed_game()
    cheated = (replace(game.seats[0], score=game.seats[0].score + 1),) + game.seats[1:]
    with pytest.raises(ResultError, match="score"):
        completed_game(seats=cheated)


def test_win_and_false_claim_counts_must_reconcile_with_the_round_records():
    game = completed_game()
    with pytest.raises(ResultError):
        completed_game(seats=(replace(game.seats[0], rounds_won=2),) + game.seats[1:])
    with pytest.raises(ResultError):
        completed_game(seats=game.seats[:2] + (replace(game.seats[2], false_claims=0),) + game.seats[3:])


def test_draw_restarts_must_reconcile_with_round_attempts_and_the_stopped_attempt():
    with pytest.raises(ResultError, match="draw_restarts"):
        completed_game(draw_restarts=0)
    with pytest.raises(ResultError, match="draw_restarts"):
        stopped_game(STATUS_DRAW_CAP_REACHED, draw_restarts=1)
    assert stopped_game(STATUS_DRAW_CAP_REACHED, stopped_attempt=1, draw_restarts=1).stopped_attempt == 1


def test_the_seats_and_lineup_indices_must_be_a_proper_arrangement():
    game = completed_game()
    with pytest.raises(ResultError):
        completed_game(seats=game.seats[:3])
    with pytest.raises(ResultError):
        completed_game(seats=tuple(reversed(game.seats)))
    clash = (replace(game.seats[1], lineup_index=0),)
    with pytest.raises(ResultError):
        completed_game(seats=game.seats[:1] + clash + game.seats[2:])
    rotated = tuple(replace(s, lineup_index=(s.seat + 1) % 4) for s in game.seats)
    assert completed_game(seats=rotated).seats[0].lineup_index == 1  # a valid rotation is accepted


def test_unknown_statuses_are_rejected():
    with pytest.raises(ResultError):
        completed_game(status="finished")
    with pytest.raises(ResultError):
        stopped_game("timeout")


def test_round_records_are_validated():
    ok = win_round(4, 0, 1, (0, 2, 3))
    assert ok.draw_restarts == 0 and win_round(4, 0, 1, (0, 2, 3), attempts=3).draw_restarts == 2
    for fields in (
        {"outcome": "draw"},
        {"claimant": 4},
        {"initiator": -1},
        {"attempts": 0},
        {"reaction_order": (0, 2)},  # missing a non-winner
        {"reaction_order": (0, 1, 2)},  # includes the winner
        {"reaction_order": (0, 2, 2)},
        {"score_changes": (1, 2, 3, 4.0)},
    ):
        with pytest.raises(ResultError):
            replace(ok, **fields)
    false = false_round(4, 1, 2)
    assert false.reaction_order == () and false.outcome == ROUND_OUTCOME_FALSE_CLAIM
    with pytest.raises(ResultError):
        replace(false, reaction_order=(0, 1, 3))
    assert ok.outcome == ROUND_OUTCOME_VALID_WIN


def test_seat_records_are_validated():
    seat = completed_game().seats[0]
    for fields in (
        {"seat": -1},
        {"score": 1.5},
        {"rank": 0},
        {"rank": 1, "tied": None},
        {"rank": None, "tied": False},
        {"rank": 1, "tied": 1},
        {"timeouts": -1},
        {"agent_faults": True},
        {"agent_type": 5},
    ):
        with pytest.raises(ResultError):
            replace(seat, **fields)
    assert isinstance(replace(seat, timeouts=3, agent_faults=2), SeatResult)


def test_faults_and_timeouts_are_separate_counters():
    seats = seats_for(four_player_rounds(), 4, STATUS_COMPLETED, counters={1: {"timeouts": 2, "agent_faults": 1}})
    game = completed_game(seats=seats)
    assert (game.seats[1].timeouts, game.seats[1].agent_faults) == (2, 1)
    assert (game.seats[0].timeouts, game.seats[0].agent_faults) == (0, 0)


# --- primitives only ---------------------------------------------------------------------


def _primitive(value) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    return isinstance(value, tuple) and all(_primitive(v) for v in value)


@pytest.mark.parametrize("game", [completed_game(), stopped_game(STATUS_ACTION_CAP_REACHED)])
def test_records_hold_primitives_only_and_serialise_to_json(game):
    for record in (*game.seats, *game.rounds):  # the leaf records
        for field in dataclasses.fields(record):
            assert _primitive(getattr(record, field.name)), (type(record).__name__, field.name)
    for field in dataclasses.fields(game):  # the game record: primitives plus its two record tuples
        value = getattr(game, field.name)
        if field.name in ("seats", "rounds"):
            assert isinstance(value, tuple) and all(dataclasses.is_dataclass(v) for v in value)
        else:
            assert _primitive(value), field.name
    data = dataclasses.asdict(game)
    assert json.loads(json.dumps(data, sort_keys=True))["status"] == game.status


def test_records_are_immutable():
    game = completed_game()
    with pytest.raises(dataclasses.FrozenInstanceError):
        game.status = "draw_cap_reached"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        game.seats[0].rank = 2  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        game.rounds[0].outcome = "x"  # type: ignore[misc]
    assert isinstance(game, GameResult) and isinstance(game.rounds[0], RoundResult)
