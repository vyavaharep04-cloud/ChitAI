"""chitai.experiment: comparability, paired arithmetic, diagnostics, equivalence, determinism (M9 Stage 3)."""

from __future__ import annotations

import ast
import csv
import json
import shutil
from pathlib import Path

import pytest
from batch.support import make_config

import chitai.experiment as experiment
from chitai.batch import run_batch
from chitai.experiment import Run, compare, equivalent, identical, main

FEWEST = {"non_target_order": "fewest_copies"}
SOURCE = Path(experiment.__file__)


def lineup(n, focal_type="mindbot", focal_config=None):
    return [{"agent_type": focal_type, "agent_config": {**FEWEST, **(focal_config or {})}}] + [
        {"agent_type": "rulebot", "agent_config": FEWEST}
    ] * (n - 1)


def cond(n=5, games=15, focal_type="mindbot", focal_config=None, **kw):
    settings = {"num_players": n, "num_rounds": n, "game_count": games, "games_per_seed": n, "batch_seed": 31}
    settings.update(kw)
    return make_config(lineup=lineup(n, focal_type, focal_config), **settings)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("runs")
    run_batch(cond(focal_type="rulebot"), base / "control")
    run_batch(cond(), base / "treatment")
    run_batch(cond(focal_config={"use_inference": False}), base / "off")
    run_batch(cond(), base / "treatment_again")
    return base


def text(report):
    return "\n".join(report.lines)


# --- comparability --------------------------------------------------------------------------------


def test_a_proper_control_and_treatment_pair_passes_every_check(runs):
    report = compare(Run(runs / "control"), Run(runs / "treatment"), 0)
    assert report.failures == [], text(report)
    body = text(report)
    assert "same game seed for every game index" in body and "paired games: 15" in body
    assert "all " in body and "games with no changed action are identical to the control game" in body


def _copy_with_config(source, target, edit):
    shutil.copytree(source, target)
    path = target / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    edit(config)
    path.write_text(json.dumps(config), encoding="utf-8")
    return target


@pytest.mark.parametrize(
    "label, edit",
    [
        ("seed", lambda c: c.update(batch_seed=c["batch_seed"] + 1)),
        ("caps", lambda c: c.update(max_actions_per_attempt=c["max_actions_per_attempt"] + 1)),
        ("rounds", lambda c: c.update(num_rounds=c["num_rounds"] * 2)),
        ("opponent", lambda c: c["lineup"][1]["agent_config"].update(non_target_order="most_copies")),
        ("strategy", lambda c: c["lineup"][0]["agent_config"].update(non_target_order="most_copies")),
        ("rotation", lambda c: c.update(rotate_seats=False)),
    ],
)
def test_batches_that_differ_in_more_than_the_focal_entry_are_not_compared(runs, tmp_path, label, edit):
    altered = _copy_with_config(runs / "treatment", tmp_path / label, edit)
    report = compare(Run(runs / "control"), Run(altered), 0)
    assert report.failures, label
    assert "no comparison is reported" in text(report)
    assert "Paired comparison" not in text(report)


def test_different_game_seeds_or_seatings_are_detected(runs, tmp_path):
    for column, table in (("game_seed", "games.csv"), ("seat", "seats.csv")):
        altered = tmp_path / column
        shutil.copytree(runs / "treatment", altered)
        rows = list(csv.DictReader(open(altered / table, encoding="utf-8", newline="")))
        rows[0][column] = "999" if column == "game_seed" else str((int(rows[0][column]) + 1) % 5)
        with open(altered / table, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        failures = compare(Run(runs / "control"), Run(altered), 0).failures
        needle = "same game seed" if column == "game_seed" else "same seating"
        assert any(needle in f for f in failures), (column, failures)


# --- paired arithmetic on hand-built data ------------------------------------------------------------------


def fabricate(path, scores, statuses, seats, ranks=None, tied=None):
    """A minimal batch directory: one focal seat (lineup 0) and one opponent per game."""
    path.mkdir()
    n = len(scores)
    config = {"lineup": [{"agent_type": "rulebot", "agent_config": FEWEST}] * 2, "num_players": 2, "output": {}}
    (path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    def write(name, header, rows):
        with open(path / name, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)

    write("games.csv", ["game_index", "game_seed", "status"], [[i, 100 + i, statuses[i]] for i in range(n)])
    rows = []
    for i in range(n):
        for lineup_index in (0, 1):
            focal = lineup_index == 0
            rows.append([i, statuses[i], seats[i] if focal else 1 - seats[i], lineup_index, "rulebot", "1", "{}",
                         scores[i] if focal else 0, (ranks or [1] * n)[i] if focal else 2,
                         (tied or ["false"] * n)[i] if focal else "false", 1 if focal else 0, 0, 0, 0])
    write("seats.csv", ["game_index", "status", "seat", "lineup_index", "agent_type", "agent_version",
                        "agent_config_json", "score", "rank", "tied", "rounds_won", "false_claims", "timeouts",
                        "agent_faults"], rows)
    write("rounds.csv", ["game_index", "round_index"], [])
    return path


def test_paired_means_differences_and_counts_are_exact_and_only_use_games_completed_in_both(tmp_path):
    done = "completed"
    control = fabricate(tmp_path / "c", [10, 12, 8, 9, 99], [done, done, done, "action_cap_reached", done], [0, 1, 0, 1, 0],
                        ranks=[2, 1, 2, 2, 1])
    treat = fabricate(tmp_path / "t", [11, 12, 6, 15, 0], [done, done, done, done, "draw_cap_reached"], [0, 1, 0, 1, 0],
                      ranks=[1, 1, 2, 1, 2])
    report = compare(Run(control), Run(treat), 0)
    body = text(report)
    assert report.failures == [], body
    assert "paired games: 3" in body  # games 3 and 4 are excluded: each was capped in one condition
    assert "not paired: control action_cap_reached / treatment completed: 1 game(s)" in body
    assert "not paired: control completed / treatment draw_cap_reached: 1 game(s)" in body
    # paired games 0, 1, 2: control 10,12,8 ; treatment 11,12,6 ; diffs +1, 0, -2
    assert "score       control 10.0000  treatment 9.6667  diff -0.3333 (SE 0.8819)" in body
    assert "treatment higher/lower/equal in 1/1/1 games" in body
    assert "rank        control 1.6667  treatment 1.3333  diff -0.3333" in body
    assert "completion rate" in body and "80.00%" in body
    row = lambda name, c, t: f"  {name:<26}{c:>9}{t:>11}"  # noqa: E731
    assert row("completed", 4, 4) in body and row("draw_cap_reached", 0, 1) in body
    assert row("action_cap_reached", 1, 0) in body and row("agent_fault_unresolvable", 0, 0) in body
    assert "seat 0: games    2  mean score diff -0.5000" in body and "seat 1: games    1  mean score diff 0.0000" in body
    assert "no agent_diagnostics.csv" in body


def test_a_batch_with_no_games_completed_in_both_reports_nothing_to_compare(tmp_path):
    control = fabricate(tmp_path / "c", [1], ["draw_cap_reached"], [0])
    treat = fabricate(tmp_path / "t", [1], ["completed"], [0])
    body = text(compare(Run(control), Run(treat), 0))
    assert "paired games: 0" in body and "no paired games" in body


def test_faults_timeouts_and_false_claims_are_totalled_per_condition_including_capped_games(tmp_path):
    control = fabricate(tmp_path / "c", [1, 1], ["completed", "action_cap_reached"], [0, 1])
    treat = fabricate(tmp_path / "t", [1, 1], ["completed", "completed"], [0, 1])
    rows = list(csv.reader(open(control / "seats.csv", encoding="utf-8", newline="")))
    rows[3][12] = "2"  # timeouts of the capped game's focal seat
    with open(control / "seats.csv", "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    assert "control   agent_faults=0  timeouts=2  false_claims=0" in text(compare(Run(control), Run(treat), 0))


# --- diagnostics ----------------------------------------------------------------------------------------------


def test_diagnostic_totals_equal_independent_sums_of_the_csv(runs):
    body = text(compare(Run(runs / "control"), Run(runs / "treatment"), 0))
    rows = list(csv.DictReader(open(runs / "treatment" / "agent_diagnostics.csv", encoding="utf-8", newline="")))
    total = lambda key: sum(int(r[key]) for r in rows)  # noqa: E731
    assert total("inference_eligible") > 0 and total("inference_changed_action") > 0
    assert f"decisions {total('decisions')}  pass decisions {total('pass_decisions')}" in body
    assert f"inference-eligible (tied target) {total('inference_eligible')}:" in body
    assert f"inference changed the action {total('inference_changed_action')}:" in body
    assert f"matched RuleBot {total('matched_rulebot')}" in body
    pct = lambda a, b: f"{100.0 * a / b:.2f}%"  # noqa: E731
    assert (f"{pct(total('inference_eligible'), total('decisions'))} of decisions, "
            f"{pct(total('inference_eligible'), total('pass_decisions'))} of pass decisions") in body
    assert (f"{pct(total('inference_changed_action'), total('decisions'))} of decisions, "
            f"{pct(total('inference_changed_action'), total('inference_eligible'))} of eligible") in body


def test_a_tampered_unchanged_game_is_caught(runs, tmp_path):
    altered = tmp_path / "tampered"
    shutil.copytree(runs / "treatment", altered)
    diag = list(csv.DictReader(open(altered / "agent_diagnostics.csv", encoding="utf-8", newline="")))
    unchanged = next(r["game_index"] for r in diag if r["inference_changed_action"] == "0")
    seats = list(csv.DictReader(open(altered / "seats.csv", encoding="utf-8", newline="")))
    for row in seats:
        if row["game_index"] == unchanged and row["lineup_index"] == "0":
            row["score"] = str(int(row["score"]) + 1)
    with open(altered / "seats.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(seats[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(seats)
    report = compare(Run(runs / "control"), Run(altered), 0)
    assert any("identical to the control game" in f for f in report.failures)


def test_a_misattributed_diagnostics_row_is_caught(runs, tmp_path):
    altered = tmp_path / "misattributed"
    shutil.copytree(runs / "treatment", altered)
    rows = list(csv.DictReader(open(altered / "agent_diagnostics.csv", encoding="utf-8", newline="")))
    rows[0]["seat"] = str((int(rows[0]["seat"]) + 1) % 5)
    with open(altered / "agent_diagnostics.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    assert any("attributed" in f for f in compare(Run(runs / "control"), Run(altered), 0).failures)


# --- equivalence and determinism ----------------------------------------------------------------------------------


def test_inference_off_is_equivalent_to_the_control_and_inference_on_is_not(runs):
    assert equivalent(Run(runs / "control"), Run(runs / "off")).failures == []
    report = equivalent(Run(runs / "control"), Run(runs / "treatment"))
    assert report.failures  # inference on does change play, and the check says so


def test_equivalence_notices_a_changed_event_stream_or_any_inference_activity(runs, tmp_path):
    events = tmp_path / "events"
    shutil.copytree(runs / "off", events)
    path = events / "events.jsonl"
    path.write_bytes(path.read_bytes().replace(b"deal", b"dea1", 1))
    assert "events.jsonl is byte-identical" in equivalent(Run(runs / "control"), Run(events)).failures

    active = tmp_path / "active"
    shutil.copytree(runs / "off", active)
    rows = list(csv.DictReader(open(active / "agent_diagnostics.csv", encoding="utf-8", newline="")))
    rows[0]["inference_eligible"] = "1"
    with open(active / "agent_diagnostics.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    assert any("no inference activity" in f for f in equivalent(Run(runs / "control"), Run(active)).failures)


def test_the_control_is_not_its_own_inference_off_batch(runs):
    assert equivalent(Run(runs / "control"), Run(runs / "control")).failures  # no MindBot seated


def test_identical_runs_are_identical_and_a_single_byte_is_noticed(runs, tmp_path):
    assert identical(runs / "treatment", runs / "treatment_again").failures == []
    altered = tmp_path / "altered"
    shutil.copytree(runs / "treatment_again", altered)
    path = altered / "games.csv"
    path.write_bytes(path.read_bytes().replace(b"completed", b"complete_", 1))
    assert identical(runs / "treatment", altered).failures == ["games.csv is byte-identical"]
    (altered / "extra.txt").write_text("x")
    assert any("same file names" in f for f in identical(runs / "treatment", altered).failures)


# --- command line -----------------------------------------------------------------------------------------------------


def test_exit_codes_and_the_never_overwrite_report_file(runs, tmp_path, capsys):
    out = tmp_path / "report.txt"
    assert main(["compare", str(runs / "control"), str(runs / "treatment"), "--output", str(out)]) == 0
    assert "RESULT: all checks passed" in out.read_text(encoding="utf-8")
    assert main(["compare", str(runs / "control"), str(runs / "treatment"), "--output", str(out)]) == 2  # exists
    assert main(["equivalent", str(runs / "control"), str(runs / "treatment")]) == 1
    assert main(["identical", str(runs / "treatment"), str(runs / "treatment_again")]) == 0
    assert main(["compare", str(runs / "control"), str(tmp_path / "missing")]) == 2
    assert "error:" in capsys.readouterr().err


# --- the module itself ---------------------------------------------------------------------------------------------------


def test_the_module_is_standard_library_plus_the_two_lower_layers_and_has_no_randomness():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    allowed = {"__future__", "argparse", "json", "sys", "collections", "collections.abc", "pathlib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name in allowed for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed or (node.level == 1 and node.module in {"eventlog", "simulation"}), node.module
        if isinstance(node, ast.Name):
            assert node.id not in {"random", "datetime", "os", "subprocess", "socket", "time"}
