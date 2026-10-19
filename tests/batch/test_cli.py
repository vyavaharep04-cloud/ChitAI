"""The command line (M8 Stage 5), including a real `python -m chitai.batch` subprocess."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from chitai.batch import MANIFEST_NAME, run_batch
from chitai.batch.cli import main

from .support import config_data, make_config, read_files, write_config

REPO = Path(__file__).resolve().parents[2]


def test_validate_checks_a_configuration_and_plays_nothing(tmp_path, capsys):
    cfg = write_config(tmp_path / "c.json")
    assert main(["validate", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "valid configuration: 4 players, 4 rounds, 4 games" in out and "nothing was run" in out
    assert list(tmp_path.iterdir()) == [cfg]


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"lineup": [{"agent_type": "ghost"}] * 4}, "unknown agent_type"),
        ({"max_actions_per_attempt": 0}, "max_actions_per_attempt"),
        ({"surprise": 1}, "unknown configuration keys"),
    ],
)
def test_a_bad_configuration_is_an_error_message_and_status_2(tmp_path, capsys, overrides, fragment):
    cfg = write_config(tmp_path / "c.json", **overrides)
    for command in (["validate", str(cfg)], ["run", str(cfg), "--output", str(tmp_path / "out")]):
        assert main(command) == 2
        assert fragment in capsys.readouterr().err
    assert not (tmp_path / "out").exists() or MANIFEST_NAME not in read_files(tmp_path / "out")


def test_missing_and_malformed_files_are_errors_not_tracebacks(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.json")]) == 2 and "cannot read configuration" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["validate", str(bad)]) == 2 and "invalid JSON" in capsys.readouterr().err
    binary = tmp_path / "bin.json"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    assert main(["validate", str(binary)]) == 2 and "UTF-8" in capsys.readouterr().err


def test_a_utf8_bom_from_powershell_is_accepted(tmp_path):
    cfg = tmp_path / "bom.json"
    cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps(config_data()).encode("utf-8"))
    assert main(["validate", str(cfg)]) == 0


def test_run_writes_the_files_and_reports_counts(tmp_path, capsys):
    cfg = write_config(tmp_path / "c.json", game_count=2)
    assert main(["run", str(cfg), "--output", str(tmp_path / "out"), "--quiet"]) == 0
    captured = capsys.readouterr()
    assert "config_sha256" in captured.out and "files written" in captured.out and captured.err == ""
    manifest = json.loads((tmp_path / "out" / MANIFEST_NAME).read_text())
    assert sum(manifest["status_counts"].values()) == 2
    for status, count in manifest["status_counts"].items():
        assert f"{status}: {count}" in captured.out


def test_run_refuses_a_non_empty_output_directory(tmp_path, capsys):
    cfg = write_config(tmp_path / "c.json")
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep").write_text("x")
    assert main(["run", str(cfg), "--output", str(out)]) == 2
    assert "not empty" in capsys.readouterr().err and read_files(out) == {"keep": b"x"}


def test_progress_goes_to_standard_error_only(tmp_path, capsys):
    cfg = write_config(tmp_path / "c.json", game_count=2)
    main(["run", str(cfg), "--output", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert "2/2 games" in captured.err and "games\n" not in captured.out.replace("files written", "")


def test_summarize_prints_the_summary_of_a_finished_run(tmp_path, capsys):
    run_batch(make_config(), tmp_path / "run")
    assert main(["summarize", str(tmp_path / "run")]) == 0
    rows = list(csv.reader(capsys.readouterr().out.splitlines()))
    assert rows[0] == ["table", "group", "metric", "value"]
    printed = [tuple(r) for r in rows[1:]]
    saved = [tuple(r.values()) for r in csv.DictReader(open(tmp_path / "run" / "summary.csv", encoding="utf-8", newline=""))]
    assert printed == saved
    assert main(["summarize", str(tmp_path / "missing")]) == 2


def test_the_module_runs_as_a_script_and_is_hash_seed_independent(tmp_path):
    cfg = write_config(tmp_path / "c.json", game_count=3)
    manifests = []
    for hash_seed in ("1", "2"):
        out = tmp_path / f"out{hash_seed}"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(REPO / "src")}
        done = subprocess.run(
            [sys.executable, "-m", "chitai.batch", "run", str(cfg), "--output", str(out), "--quiet"],
            capture_output=True, text=True, cwd=REPO, env=env,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        manifests.append(json.loads((out / MANIFEST_NAME).read_text()))
    assert manifests[0]["files"] == manifests[1]["files"]
    # and it equals an in-process run of the same configuration
    in_process = run_batch(make_config(game_count=3), tmp_path / "inproc")
    assert in_process["files"] == manifests[0]["files"]
