"""CSV tables and summaries (M8 Stage 4)."""

from __future__ import annotations

import csv

import pytest
from simulation.runner_support import claim_policy, crafted_start, play, sim_config, stall_policy

from chitai.eventlog import (
    GAME_COLUMNS, ROUND_COLUMNS, SEAT_COLUMNS, SUMMARY_COLUMNS, CsvWriter, game_row, read_csv,
    round_rows, seat_rows, summarize,
)  # fmt: skip
from chitai.eventlog.tables import cell
from chitai.simulation import STATUS_ACTION_CAP_REACHED, TERMINATION_STATUSES, run_game


def test_cells_are_plain_text():
    assert [cell(v) for v in (None, True, False, 5, "x", (1, 2, 3), ())] == ["", "true", "false", "5", "x", "1 2 3", ""]


def test_rows_match_their_columns_for_completed_and_stopped_games():
    done = run_game(sim_config(4), 0)
    stopped = run_game(sim_config(4, actions=3), 0)
    for result in (done, stopped):
        assert len(game_row(result)) == len(GAME_COLUMNS)
        assert all(len(row) == len(SEAT_COLUMNS) for row in seat_rows(result))
        assert all(len(row) == len(ROUND_COLUMNS) for row in round_rows(result))
    g = dict(zip(GAME_COLUMNS, game_row(done)))
    assert g["status"] == "completed" and g["stopped_attempt"] == "" and g["winning_seats"] != ""
    assert len(round_rows(done)) == done.num_rounds
    g = dict(zip(GAME_COLUMNS, game_row(stopped)))
    assert g["status"] == STATUS_ACTION_CAP_REACHED and g["tie_for_first"] == "" and g["winning_seats"] == ""
    for row in seat_rows(stopped):  # a truncated game has no rank, no tie flag
        seat = dict(zip(SEAT_COLUMNS, row))
        assert seat["rank"] == "" and seat["tied"] == ""


def test_round_rows_record_reactions_scores_and_draw_restarts():
    result, _, _ = play(sim_config(4, ["c"] * 4, draws=3), 0, {"c": claim_policy}, crafted_start({0}))
    first = dict(zip(ROUND_COLUMNS, round_rows(result)[0]))
    assert first["outcome"] == "valid_win" and first["reaction_order"] == "3 2 1"
    assert first["score_changes"] == "4 1 2 3" and first["draw_restarts"] == "0"
    false_round = dict(zip(ROUND_COLUMNS, round_rows(result)[1]))
    assert false_round["outcome"] == "false_claim" and false_round["reaction_order"] == ""


def test_draw_restarts_per_round_are_attempts_minus_one():
    from simulation.test_runner_caps import stall_then_claim

    result, _, _ = play(sim_config(4, ["s"] * 4, draws=1), 0, {"s": stall_then_claim})
    assert [dict(zip(ROUND_COLUMNS, r))["draw_restarts"] for r in round_rows(result)] == ["1"] * 4


def test_files_are_utf8_with_lf_line_endings_and_round_trip(tmp_path):
    result = run_game(sim_config(4), 0)
    path = tmp_path / "seats.csv"
    with CsvWriter(path, SEAT_COLUMNS) as writer:
        writer.writerows(seat_rows(result))
    raw = path.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    rows = read_csv(path)
    assert len(rows) == 4 and list(rows[0]) == list(SEAT_COLUMNS)
    assert rows[0]["agent_config_json"] == '{"avoid_draw":true,"non_target_order":"most_copies"}'  # commas and quotes survive
    assert [r["seat"] for r in rows] == ["0", "1", "2", "3"]


def test_a_row_of_the_wrong_width_is_refused(tmp_path):
    with CsvWriter(tmp_path / "x.csv", ("a", "b")) as writer:
        with pytest.raises(ValueError):
            writer.writerow(["only one"])


# --- summaries --------------------------------------------------------------------------------------


def _game(index, status, actions=10, draws=0, tie="false"):
    return {"game_index": str(index), "status": status, "actions": str(actions), "draw_restarts": str(draws), "tie_for_first": tie}


def _seat(game, status, seat, lineup, score, rank, tied, fc=0, to=0, af=0, config="{}"):
    return {
        "game_index": str(game), "status": status, "seat": str(seat), "lineup_index": str(lineup), "agent_type": "rulebot",
        "agent_version": "1", "agent_config_json": config, "score": str(score), "rank": rank, "tied": tied,
        "rounds_won": "0", "false_claims": str(fc), "timeouts": str(to), "agent_faults": str(af),
    }  # fmt: skip


def _table(rows):
    return {(t, g, m): v for t, g, m, v in rows}


def test_summary_counts_statuses_and_excludes_truncated_games_from_score_metrics():
    games = [_game(0, "completed", 10), _game(1, "completed", 30, tie="true"), _game(2, "action_cap_reached", 100)]
    seats = [
        _seat(0, "completed", 0, 0, 5, "1", "false"), _seat(0, "completed", 1, 1, -5, "2", "false"),
        _seat(1, "completed", 0, 1, 2, "1", "true"), _seat(1, "completed", 1, 0, 2, "1", "true"),
        _seat(2, "action_cap_reached", 0, 0, 99, "", "", fc=1, to=2, af=3), _seat(2, "action_cap_reached", 1, 1, -99, "", ""),
    ]  # fmt: skip
    t = _table(summarize(games, seats))
    assert t[("batch", "all", "games")] == "3"
    assert t[("status", "completed", "games")] == "2" and t[("status", "action_cap_reached", "games")] == "1"
    assert t[("status", "completed", "share")] == "0.666667" and t[("status", "draw_cap_reached", "share")] == "0.000000"
    assert t[("batch", "completed", "mean_actions")] == "20.000000" and t[("batch", "all", "mean_actions")] == "46.666667"
    assert t[("batch", "completed", "ties_for_first")] == "1"
    a0, a1 = "lineup=0|rulebot@1|{}", "lineup=1|rulebot@1|{}"
    assert t[("agent", a0, "completed_games")] == "2" and t[("agent", a0, "mean_score")] == "3.500000"  # 5 and 2; 99 excluded
    assert t[("agent", a0, "mean_rank")] == "1.000000" and t[("agent", a0, "rank1_share")] == "1.000000"
    assert t[("agent", a0, "outright_win_share")] == "0.500000"  # the tied first is not an outright win
    assert t[("agent", a1, "mean_score")] == "-1.500000" and t[("agent", a1, "rank1_share")] == "0.500000"
    assert t[("agent", a0, "false_claims")] == "1" and t[("agent", a0, "timeouts")] == "2" and t[("agent", a0, "agent_faults")] == "3"
    assert t[("agent", a0, "games")] == "3"  # the truncated game still counts as a game played


def test_summary_groups_by_lineup_entry_not_by_seat_and_reports_positions_separately():
    games = [_game(0, "completed"), _game(1, "completed")]
    seats = [  # the same two entries swap seats between games
        _seat(0, "completed", 0, 0, 4, "1", "false"), _seat(0, "completed", 1, 1, 0, "2", "false"),
        _seat(1, "completed", 0, 1, 2, "1", "false"), _seat(1, "completed", 1, 0, 0, "2", "false"),
    ]  # fmt: skip
    t = _table(summarize(games, seats))
    assert t[("agent", "lineup=0|rulebot@1|{}", "mean_score")] == "2.000000"
    assert t[("agent", "lineup=1|rulebot@1|{}", "mean_score")] == "1.000000"
    assert t[("seat", "seat=0", "mean_score")] == "3.000000" and t[("seat", "seat=1", "rank1_share")] == "0.000000"


def test_an_empty_or_all_truncated_batch_has_empty_cells_not_errors():
    t = _table(summarize([_game(0, "draw_cap_reached")], [_seat(0, "draw_cap_reached", 0, 0, 0, "", "")]))
    assert t[("batch", "completed", "mean_actions")] == "" and t[("agent", "lineup=0|rulebot@1|{}", "mean_score")] == ""
    assert _table(summarize([], []))[("batch", "all", "games")] == "0"
    assert SUMMARY_COLUMNS == ("table", "group", "metric", "value") and set(TERMINATION_STATUSES) <= {g for (_, g, _) in t}


def test_summary_of_real_games_matches_an_independent_calculation(tmp_path):
    results = [run_game(sim_config(4, game_count=6), i) for i in range(6)]
    with CsvWriter(tmp_path / "g.csv", GAME_COLUMNS) as g, CsvWriter(tmp_path / "s.csv", SEAT_COLUMNS) as s:
        for r in results:
            g.writerow(game_row(r)); s.writerows(seat_rows(r))  # noqa: E702
    t = _table(summarize(read_csv(tmp_path / "g.csv"), read_csv(tmp_path / "s.csv")))
    done = [r for r in results if r.completed]
    expected = sum(r.seats[0].score for r in done) / len(done)
    # lineup 0 sits in seat 0 in every game of this unrotated batch
    assert t[("agent", 'lineup=0|rulebot@1|{"avoid_draw":true,"non_target_order":"most_copies"}', "mean_score")] == format(expected, ".6f")
    assert t[("batch", "all", "games")] == "6"
