"""Per-agent diagnostics in batches, and the control/treatment plumbing (M9 Stage 2)."""

from __future__ import annotations

import hashlib
import json

import pytest

from chitai.agents import MindBot
from chitai.batch import MANIFEST_NAME, main, run_batch
from chitai.eventlog import (
    AGENT_DIAGNOSTIC_COLUMNS,
    AGENT_DIAGNOSTIC_KEYS,
    SEAT_COLUMNS,
    agent_diagnostic_rows,
    read_csv,
)
from chitai.simulation import AgentSpec, build_agent, run_game

from .support import make_config, read_files, write_config

FEWEST = {"non_target_order": "fewest_copies"}
DIAGNOSTICS = "agent_diagnostics.csv"


def lineup(n, focal_type="mindbot", focal_config=None):
    focal = {"agent_type": focal_type, "agent_config": {**FEWEST, **(focal_config or {})}}
    return [focal] + [{"agent_type": "rulebot", "agent_config": FEWEST}] * (n - 1)


def condition(n=4, focal_type="mindbot", focal_config=None, **overrides):
    settings = {"num_players": n, "num_rounds": n, "game_count": 2 * n, "games_per_seed": n, "batch_seed": 23}
    settings.update(overrides)
    return make_config(lineup=lineup(n, focal_type, focal_config), **settings)


def as_ints(row):
    return {key: int(row[key]) for key in AGENT_DIAGNOSTIC_KEYS}


# --- the file ------------------------------------------------------------------------------------


def test_a_mindbot_batch_writes_the_diagnostics_table_and_lists_it_in_the_manifest(tmp_path):
    manifest = run_batch(condition(), tmp_path / "run")
    files = read_files(tmp_path / "run")
    assert DIAGNOSTICS in files and DIAGNOSTICS in manifest["files"]
    assert manifest["files"][DIAGNOSTICS] == {
        "sha256": hashlib.sha256(files[DIAGNOSTICS]).hexdigest(), "bytes": len(files[DIAGNOSTICS]),
    }  # fmt: skip
    assert json.loads(files[MANIFEST_NAME]) == manifest
    header = files[DIAGNOSTICS].decode().splitlines()[0].split(",")
    assert tuple(header) == AGENT_DIAGNOSTIC_COLUMNS
    assert b"\r" not in files[DIAGNOSTICS]


def test_a_rulebot_only_batch_has_no_diagnostics_file_exactly_as_before(tmp_path):
    manifest = run_batch(make_config(), tmp_path)
    assert DIAGNOSTICS not in read_files(tmp_path) and DIAGNOSTICS not in manifest["files"]


def test_the_table_schema_matches_what_mindbot_reports():
    assert set(MindBot().diagnostics()) == set(AGENT_DIAGNOSTIC_KEYS)
    assert AGENT_DIAGNOSTIC_COLUMNS[:5] == ("game_index", "status", "seat", "lineup_index", "agent_type")


def test_the_table_holds_only_identifiers_and_counters(tmp_path):
    run_batch(condition(), tmp_path)
    for row in read_csv(tmp_path / DIAGNOSTICS):
        assert set(row) == set(AGENT_DIAGNOSTIC_COLUMNS)
        assert all(row[key].isdigit() for key in ("game_index", "seat", "lineup_index", *AGENT_DIAGNOSTIC_KEYS))
        assert row["agent_type"] == "mindbot" and row["status"] in {"completed", "draw_cap_reached", "action_cap_reached"}


def test_two_identical_batches_give_byte_identical_files_including_the_diagnostics(tmp_path):
    run_batch(condition(), tmp_path / "a")
    run_batch(condition(), tmp_path / "b")
    assert read_files(tmp_path / "a") == read_files(tmp_path / "b")


# --- attribution ----------------------------------------------------------------------------------


def test_every_row_belongs_to_the_mindbot_seat_of_that_game(tmp_path):
    cfg = condition(5, game_count=10)
    run_batch(cfg, tmp_path)
    rows = read_csv(tmp_path / DIAGNOSTICS)
    seats = read_csv(tmp_path / "seats.csv")
    assert len(rows) == cfg.game_count  # one MindBot per game
    expected = {(r["game_index"], r["seat"]) for r in seats if r["agent_type"] == "mindbot"}
    assert {(r["game_index"], r["seat"]) for r in rows} == expected
    for row in rows:
        seat = next(s for s in seats if s["game_index"] == row["game_index"] and s["seat"] == row["seat"])
        assert (seat["lineup_index"], seat["agent_type"], seat["status"]) == (row["lineup_index"], row["agent_type"], row["status"])
    assert {int(r["seat"]) for r in rows} == set(range(5))  # rotation moved it through every seat


def test_the_counters_equal_those_of_an_independent_replay_of_the_same_games(tmp_path):
    cfg = condition(4, game_count=8)
    run_batch(cfg, tmp_path)
    rows = {int(r["game_index"]): r for r in read_csv(tmp_path / DIAGNOSTICS)}
    for game_index in range(cfg.game_count):
        built = []

        def factory(spec, built=built):
            built.append(build_agent(spec))
            return built[-1]

        result = run_game(cfg, game_index, agent_factory=factory)
        seat = next(s.seat for s in result.seats if s.agent_type == "mindbot")
        assert as_ints(rows[game_index]) == built[seat].diagnostics()
        assert int(rows[game_index]["seat"]) == seat


def test_counters_are_consistent_and_show_inference_acting_only_as_a_tie_break(tmp_path):
    run_batch(condition(5, game_count=15), tmp_path)
    total_changed = 0
    for row in read_csv(tmp_path / DIAGNOSTICS):
        c = as_ints(row)
        assert c["decisions"] == c["matched_rulebot"] + c["inference_changed_action"]
        assert c["inference_changed_action"] <= c["inference_eligible"] <= c["pass_decisions"] <= c["decisions"]
        assert c["estimator_unreconstructable"] == c["estimator_uniform_priors"] == c["estimator_normalisation_resets"] == 0
        assert c["estimator_updates"] + c["estimator_no_change"] > 0 and c["estimator_deals"] >= 1
        total_changed += c["inference_changed_action"]
    assert total_changed > 0  # inference does change some real decisions


def test_stopped_games_still_report_diagnostics_with_their_true_status(tmp_path):
    """Capped games are excluded from rank metrics later, so each row must carry its game's status.
    `most_copies` RuleBots are the variant that stalls into the action cap (M8 measurement)."""
    stalling = {"non_target_order": "most_copies"}
    mixed = [{"agent_type": "mindbot", "agent_config": stalling}] + [{"agent_type": "rulebot", "agent_config": stalling}] * 3
    run_batch(make_config(lineup=mixed, game_count=16, games_per_seed=4, batch_seed=5), tmp_path)
    games = {r["game_index"]: r["status"] for r in read_csv(tmp_path / "games.csv")}
    rows = read_csv(tmp_path / DIAGNOSTICS)
    assert len(rows) == 16
    assert set(games.values()) - {"completed"}, "the cap was expected to stop some games"
    assert "completed" in games.values()
    assert all(r["status"] == games[r["game_index"]] for r in rows)
    assert all(int(r["decisions"]) > 0 for r in rows)


def test_two_mindbots_with_different_settings_are_reported_separately(tmp_path):
    mixed = [
        {"agent_type": "mindbot", "agent_config": {**FEWEST, "use_inference": True}},
        {"agent_type": "mindbot", "agent_config": {**FEWEST, "use_inference": False}},
        {"agent_type": "rulebot", "agent_config": FEWEST},
        {"agent_type": "rulebot", "agent_config": FEWEST},
    ]
    cfg = make_config(lineup=mixed, game_count=8, games_per_seed=4)
    run_batch(cfg, tmp_path)
    rows = read_csv(tmp_path / DIAGNOSTICS)
    assert len(rows) == 16
    on = [as_ints(r) for r in rows if r["lineup_index"] == "0"]
    off = [as_ints(r) for r in rows if r["lineup_index"] == "1"]
    assert len(on) == len(off) == 8
    assert all(c["inference_eligible"] == c["inference_changed_action"] == c["estimator_deals"] == 0 for c in off)
    assert all(c["matched_rulebot"] == c["decisions"] for c in off)
    assert sum(c["estimator_deals"] for c in on) > 0


def test_a_row_that_cannot_be_attributed_is_an_error_not_a_mislabel():
    cfg = condition(4, game_count=1, games_per_seed=1)
    agents = []

    def factory(spec):
        agents.append(build_agent(spec))
        return agents[-1]

    result = run_game(cfg, 0, agent_factory=factory)
    assert len(agent_diagnostic_rows(result, agents)) == 1
    other = [build_agent(AgentSpec("mindbot", {**FEWEST, "epsilon": 0.5}))] + agents[1:]
    with pytest.raises(ValueError, match="does not match the seat record"):
        agent_diagnostic_rows(result, other)  # the configuration is not the recorded one
    with pytest.raises(ValueError, match="expected 4 agents"):
        agent_diagnostic_rows(result, agents[:3] + [])  # a wrong count is never silently accepted


def test_diagnostics_with_the_wrong_shape_are_rejected():
    cfg = condition(4, game_count=1, games_per_seed=1)

    class Odd(MindBot):
        def diagnostics(self):
            return {"decisions": 1}

    result = run_game(cfg, 0, agent_factory=lambda spec: Odd(**spec.to_dict()["agent_config"]) if spec.agent_type == "mindbot" else build_agent(spec))
    agents = [Odd(**FEWEST) if s.agent_type == "mindbot" else build_agent(AgentSpec("rulebot", FEWEST)) for s in result.seats]
    with pytest.raises(ValueError, match="schema"):
        agent_diagnostic_rows(result, agents)


# --- the experimental conditions --------------------------------------------------------------------


def test_control_and_treatment_batches_use_the_same_seeds_seatings_and_opponents(tmp_path):
    n = 4
    run_batch(condition(n, focal_type="rulebot"), tmp_path / "control")
    run_batch(condition(n), tmp_path / "treatment")
    control_games, treatment_games = (read_csv(tmp_path / d / "games.csv") for d in ("control", "treatment"))
    assert [g["game_seed"] for g in control_games] == [g["game_seed"] for g in treatment_games]
    control_seats, treatment_seats = (read_csv(tmp_path / d / "seats.csv") for d in ("control", "treatment"))
    key = lambda r: (r["game_index"], r["seat"], r["lineup_index"])  # noqa: E731
    assert [key(r) for r in control_seats] == [key(r) for r in treatment_seats]
    for a, b in zip(control_seats, treatment_seats):
        if a["lineup_index"] == "0":
            assert (a["agent_type"], b["agent_type"]) == ("rulebot", "mindbot")
        else:
            assert {k: a[k] for k in SEAT_COLUMNS if k not in ("score", "rank", "tied", "rounds_won", "false_claims", "timeouts", "agent_faults", "status")} == {
                k: b[k] for k in SEAT_COLUMNS if k not in ("score", "rank", "tied", "rounds_won", "false_claims", "timeouts", "agent_faults", "status")
            }
    assert DIAGNOSTICS not in read_files(tmp_path / "control") and DIAGNOSTICS in read_files(tmp_path / "treatment")
    # games per deal seed = N: every deal seed is played from every seat, in both conditions
    seeds = [g["game_seed"] for g in treatment_games]
    assert len(set(seeds[:n])) == 1 and len(set(seeds)) == 2
    for chunk in (slice(0, n), slice(n, 2 * n)):
        focal_seats = [r["seat"] for r in treatment_seats if r["lineup_index"] == "0"][chunk]
        assert sorted(focal_seats) == [str(s) for s in range(n)]


def test_with_inference_off_the_treatment_batch_reproduces_the_control_results_exactly(tmp_path):
    run_batch(condition(focal_type="rulebot"), tmp_path / "control")
    run_batch(condition(focal_config={"use_inference": False}), tmp_path / "off")
    assert (tmp_path / "control" / "games.csv").read_bytes() == (tmp_path / "off" / "games.csv").read_bytes()
    assert (tmp_path / "control" / "rounds.csv").read_bytes() == (tmp_path / "off" / "rounds.csv").read_bytes()
    for a, b in zip(read_csv(tmp_path / "control" / "seats.csv"), read_csv(tmp_path / "off" / "seats.csv")):
        identity = ("agent_type", "agent_version", "agent_config_json")
        assert {k: v for k, v in a.items() if k not in identity} == {k: v for k, v in b.items() if k not in identity}
    rows = read_csv(tmp_path / "off" / DIAGNOSTICS)
    assert rows and all(as_ints(r)["matched_rulebot"] == as_ints(r)["decisions"] for r in rows)


def test_a_game_in_which_inference_never_changed_a_decision_is_identical_to_the_control_game(tmp_path):
    """If MindBot never deviated from RuleBot in a game, nothing in that game can differ."""
    cfg_control, cfg_treat = condition(5, focal_type="rulebot", game_count=15), condition(5, game_count=15)
    run_batch(cfg_control, tmp_path / "control")
    run_batch(cfg_treat, tmp_path / "treatment")
    control = {r["game_index"]: r for r in read_csv(tmp_path / "control" / "games.csv")}
    treatment = {r["game_index"]: r for r in read_csv(tmp_path / "treatment" / "games.csv")}
    diagnostics = {r["game_index"]: as_ints(r) for r in read_csv(tmp_path / "treatment" / DIAGNOSTICS)}
    unchanged = [g for g, c in diagnostics.items() if c["inference_changed_action"] == 0]
    changed = [g for g, c in diagnostics.items() if c["inference_changed_action"] > 0]
    assert unchanged and changed  # both kinds of game occur, so the check is not vacuous
    for game in unchanged:
        assert treatment[game] == control[game], game


# --- the command line ------------------------------------------------------------------------------------------


def test_the_command_line_validates_and_runs_a_mindbot_configuration(tmp_path, capsys):
    path = tmp_path / "treatment.json"
    path.write_text(json.dumps({**condition().to_dict(), "output": {}}), encoding="utf-8")
    assert main(["validate", str(path)]) == 0
    out = capsys.readouterr().out
    assert "lineup 0: mindbot" in out and "lineup 1: rulebot" in out and "nothing was run" in out
    assert main(["run", str(path), "--output", str(tmp_path / "out"), "--quiet"]) == 0
    assert DIAGNOSTICS in read_files(tmp_path / "out")
    assert main(["summarize", str(tmp_path / "out")]) == 0  # the M8 summary still works on these files


def test_an_unknown_agent_type_is_still_rejected_by_validate(tmp_path, capsys):
    path = write_config(tmp_path / "bad.json", lineup=[{"agent_type": "smartbot"}] * 4)
    assert main(["validate", str(path)]) == 2
    assert "unknown agent_type 'smartbot' (known: mindbot, rulebot)" in capsys.readouterr().err
