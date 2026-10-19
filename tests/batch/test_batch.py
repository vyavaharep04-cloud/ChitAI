"""run_batch: files, determinism, safety and fairness plumbing (M8 Stage 5)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from unittest import mock

import pytest
from simulation.runner_support import Trigger, factory_for, misbehaving_policy, rule_policy, sim_config

from chitai.batch import MANIFEST_NAME, BatchError, effective_config, run_batch
from chitai.eventlog import GAME_COLUMNS, SEAT_COLUMNS, game_row, read_csv, summarize
from chitai.simulation import SimulationConfig, run_game

from .support import make_config, read_files

BASE_FILES = {"config.json", "games.csv", "seats.csv", "rounds.csv", "summary.csv", "events.jsonl", MANIFEST_NAME}


def test_a_batch_writes_the_documented_files_and_a_matching_manifest(tmp_path):
    config = make_config()
    manifest = run_batch(config, tmp_path / "run")
    files = read_files(tmp_path / "run")
    assert set(files) == BASE_FILES  # private diagnostics are off by default
    on_disk = json.loads(files[MANIFEST_NAME])
    assert on_disk == manifest
    assert set(manifest["files"]) == BASE_FILES - {MANIFEST_NAME}
    for name, entry in manifest["files"].items():
        assert entry == {"sha256": hashlib.sha256(files[name]).hexdigest(), "bytes": len(files[name])}
    assert sum(manifest["status_counts"].values()) == config.game_count
    assert manifest["config_sha256"] == hashlib.sha256(files["config.json"].rstrip(b"\n")).hexdigest()
    text = files[MANIFEST_NAME].decode()
    assert str(tmp_path) not in text  # no machine-specific path; no clock time either
    assert not any(key in manifest for key in ("timestamp", "created", "elapsed", "directory"))


def test_the_tables_agree_with_independent_runs_of_the_same_games(tmp_path):
    config = make_config(game_count=4)
    run_batch(config, tmp_path)
    games = read_csv(tmp_path / "games.csv")
    seats = read_csv(tmp_path / "seats.csv")
    rounds = read_csv(tmp_path / "rounds.csv")
    expected = [run_game(config, i) for i in range(4)]
    assert [list(r.values()) for r in games] == [game_row(r) for r in expected]
    assert len(seats) == 16 and [int(r["game_index"]) for r in seats] == sorted(int(r["game_index"]) for r in seats)
    assert len(rounds) == sum(len(r.rounds) for r in expected)
    assert list(games[0]) == list(GAME_COLUMNS) and list(seats[0]) == list(SEAT_COLUMNS)
    summary = read_csv(tmp_path / "summary.csv")
    assert [tuple(r.values()) for r in summary] == summarize(games, seats)


def test_the_event_log_has_one_closing_line_per_game_in_order(tmp_path):
    config = make_config(game_count=4)
    run_batch(config, tmp_path)
    lines = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    ends = [l for l in lines if l["record"] == "game_end"]
    assert [l["game_index"] for l in ends] == [0, 1, 2, 3]
    assert [l["status"] for l in ends] == [r["status"] for r in read_csv(tmp_path / "games.csv")]
    indexes = [l["game_index"] for l in lines]
    assert indexes == sorted(indexes)  # games are contiguous and in order


def test_the_same_configuration_gives_byte_identical_files(tmp_path):
    config = make_config()
    run_batch(config, tmp_path / "a")
    run_batch(config, tmp_path / "b")
    assert read_files(tmp_path / "a") == read_files(tmp_path / "b")


def test_a_run_can_be_repeated_from_its_saved_configuration(tmp_path):
    run_batch(make_config(output={"private_diagnostics": True}), tmp_path / "first")
    saved = SimulationConfig.from_json((tmp_path / "first" / "config.json").read_text())
    assert saved.output.directory is None and saved.output.private_diagnostics is True
    run_batch(saved, tmp_path / "second")
    assert read_files(tmp_path / "first") == read_files(tmp_path / "second")


def test_a_different_seed_gives_a_different_run(tmp_path):
    a = run_batch(make_config(batch_seed=1), tmp_path / "a")
    b = run_batch(make_config(batch_seed=2), tmp_path / "b")
    assert a["config_sha256"] != b["config_sha256"]
    assert (tmp_path / "a" / "games.csv").read_bytes() != (tmp_path / "b" / "games.csv").read_bytes()


def test_output_options_choose_the_optional_files(tmp_path):
    run_batch(make_config(output={"public_event_log": False}), tmp_path / "none")
    assert set(read_files(tmp_path / "none")) == BASE_FILES - {"events.jsonl"}
    run_batch(make_config(output={"private_diagnostics": True}), tmp_path / "both")
    files = read_files(tmp_path / "both")
    assert set(files) == BASE_FILES | {"private_diagnostics.jsonl"}
    assert b'"hands"' in files["private_diagnostics.jsonl"] and b'"hands"' not in files["events.jsonl"]
    run_batch(make_config(output={"public_event_log": False, "private_diagnostics": True}), tmp_path / "private_only")
    assert set(read_files(tmp_path / "private_only")) == (BASE_FILES - {"events.jsonl"}) | {"private_diagnostics.jsonl"}


def test_every_file_uses_lf_line_endings_and_valid_json_lines(tmp_path):
    run_batch(make_config(output={"private_diagnostics": True}), tmp_path)
    for name, data in read_files(tmp_path).items():
        assert b"\r" not in data, name
        if name.endswith(".jsonl"):
            assert all(json.loads(line) for line in data.decode().splitlines())


def test_the_saved_configuration_drops_the_output_path_but_keeps_everything_else():
    config = make_config(output={"directory": "C:/somewhere/else", "private_diagnostics": True})
    data = effective_config(config)
    assert data["output"] == {"directory": None, "public_event_log": True, "private_diagnostics": True}
    assert {k: v for k, v in data.items() if k != "output"} == {k: v for k, v in config.to_dict().items() if k != "output"}


# --- directory safety -----------------------------------------------------------------------------


def test_a_non_empty_directory_is_refused_and_left_untouched(tmp_path):
    (tmp_path / "keep.txt").write_text("mine")
    with pytest.raises(BatchError, match="not empty"):
        run_batch(make_config(), tmp_path)
    assert read_files(tmp_path) == {"keep.txt": b"mine"}


def test_an_existing_file_is_refused(tmp_path):
    target = tmp_path / "a_file"
    target.write_text("x")
    with pytest.raises(BatchError, match="not a directory"):
        run_batch(make_config(), target)
    assert target.read_text() == "x"


def test_new_nested_and_empty_directories_are_accepted(tmp_path):
    (tmp_path / "empty").mkdir()
    run_batch(make_config(game_count=1), tmp_path / "empty")
    run_batch(make_config(game_count=1), tmp_path / "x" / "y" / "z")
    assert MANIFEST_NAME in read_files(tmp_path / "x" / "y" / "z")


def test_the_output_directory_comes_from_the_argument_or_the_configuration(tmp_path):
    with pytest.raises(BatchError, match="no output directory"):
        run_batch(make_config())
    run_batch(make_config(game_count=1, output={"directory": str(tmp_path / "from_config")}))
    assert MANIFEST_NAME in read_files(tmp_path / "from_config")
    run_batch(make_config(game_count=1, output={"directory": str(tmp_path / "ignored")}), tmp_path / "from_arg")
    assert (tmp_path / "from_arg").exists() and not (tmp_path / "ignored").exists()


def test_a_failing_game_leaves_no_manifest_so_the_run_is_visibly_incomplete(tmp_path):
    real = run_game.__wrapped__ if hasattr(run_game, "__wrapped__") else run_game

    def flaky(config, index, **kwargs):
        if index == 2:
            raise RuntimeError("engine bug")
        return real(config, index, **kwargs)

    with mock.patch("chitai.batch.runner.run_game", flaky):
        with pytest.raises(RuntimeError, match="engine bug"):
            run_batch(make_config(game_count=4), tmp_path)
    files = read_files(tmp_path)
    assert MANIFEST_NAME not in files and "games.csv" in files
    assert len(read_csv(tmp_path / "games.csv")) == 2  # the two finished games were kept


def test_a_bad_lineup_fails_before_any_game_is_played_but_after_nothing_is_overwritten(tmp_path):
    config = make_config(lineup=[{"agent_type": "ghost"}] * 4)
    with pytest.raises(Exception, match="unknown agent_type"):
        run_batch(config, tmp_path / "run")
    assert MANIFEST_NAME not in read_files(tmp_path / "run")


# --- faults and fairness plumbing -------------------------------------------------------------------------


def test_faults_and_timeouts_reach_the_tables_the_summary_and_the_private_file_only(tmp_path):
    trigger = Trigger(lambda o: o.phase == "initial_claims", limit=3)
    factory, _ = factory_for({"m": misbehaving_policy("raise", trigger)})
    config = sim_config(4, ["m"] * 4, game_count=4, batch_seed=5)
    config = SimulationConfig.from_dict({**config.to_dict(), "output": {"private_diagnostics": True}})
    run_batch(config, tmp_path, agent_factory=factory)
    seats = read_csv(tmp_path / "seats.csv")
    assert sum(int(r["agent_faults"]) for r in seats) == 3 == sum(int(r["timeouts"]) for r in seats)
    private = [json.loads(l) for l in (tmp_path / "private_diagnostics.jsonl").read_text().splitlines()]
    assert Counter(r["kind"] for r in private if r["record"] == "fault") == {"exception": 3}
    assert b"fault" not in (tmp_path / "events.jsonl").read_bytes()
    summary = read_csv(tmp_path / "summary.csv")
    for metric in ("agent_faults", "timeouts"):  # one row per lineup entry; together they hold all 3
        assert sum(int(r["value"]) for r in summary if r["table"] == "agent" and r["metric"] == metric) == 3


def test_with_rotation_every_lineup_entry_sits_in_every_seat_equally(tmp_path):
    lineup = [{"agent_type": "rulebot", "agent_config": {"avoid_draw": a, "non_target_order": o}}
              for a in (True, False) for o in ("most_copies", "fewest_copies")]  # fmt: skip
    run_batch(make_config(lineup=lineup, game_count=8, rotate_seats=True), tmp_path)
    placed = Counter((r["lineup_index"], r["seat"]) for r in read_csv(tmp_path / "seats.csv"))
    assert set(placed.values()) == {2} and len(placed) == 16


def test_paired_mode_gives_every_game_of_a_group_the_same_deal_seed(tmp_path):
    run_batch(make_config(game_count=8, games_per_seed=4, rotate_seats=True), tmp_path)
    seeds = [r["game_seed"] for r in read_csv(tmp_path / "games.csv")]
    assert len(set(seeds[:4])) == 1 and len(set(seeds[4:])) == 1 and seeds[0] != seeds[4]
