"""Run a batch of seeded AI-only games and write its files (M8 Stage 5).

`run_batch(config, directory)` plays games ``0 .. game_count - 1`` in order with `run_game`,
and writes into a *new or empty* directory (it never overwrites or deletes anything):

    config.json              the effective configuration (canonical JSON, no output path); a
                             later run from this file reproduces the batch
    games.csv, seats.csv, rounds.csv   the result tables (Stage 4)
    events.jsonl             the public event log, if `output.public_event_log` (default on)
    private_diagnostics.jsonl  private events and fault kinds, only if `output.private_diagnostics`
    summary.csv              descriptive summary computed from games.csv and seats.csv
    agent_diagnostics.csv    only if a seated agent reports `diagnostics()` (MindBot does, RuleBot
                             does not): one row per game per such seat, written after the game
    manifest.json            hashes of everything above; written last (absent = incomplete run)

The same configuration always produces byte-identical files: nothing depends on the clock, the
machine's path, the hash seed or the order of a set. If a game raises, the exception propagates,
no manifest is written, and the partial files stay for inspection.

This module lives outside `simulation/` because it writes files; it adds no game logic.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..eventlog import (
    AGENT_DIAGNOSTIC_COLUMNS, GAME_COLUMNS, ROUND_COLUMNS, SEAT_COLUMNS, SUMMARY_COLUMNS, CsvWriter,
    GameRecorder, agent_diagnostic_rows, game_end_line, game_row, read_csv, round_rows, seat_rows,
    summarize,
)  # fmt: skip
from ..simulation import (
    TERMINATION_STATUSES,
    AgentSpec,
    SimulationConfig,
    build_agent,
    canonical_json,
    run_game,
)
from .manifest import MANIFEST_NAME, build_manifest, manifest_text

CONFIG_NAME = "config.json"
EVENTS_NAME = "events.jsonl"
DIAGNOSTICS_NAME = "private_diagnostics.jsonl"
SUMMARY_NAME = "summary.csv"
AGENT_DIAGNOSTICS_NAME = "agent_diagnostics.csv"


class BatchError(RuntimeError):
    """A problem with where or how a batch is written (not a game or configuration error)."""


def effective_config(config: SimulationConfig) -> dict[str, Any]:
    """The configuration as saved with a run: the output directory is machine-specific, so it is
    dropped; every setting that changes the games or the files is kept."""
    data = config.to_dict()
    data["output"] = {**data["output"], "directory": None}
    return data


def _prepare(directory: str | Path | None, config: SimulationConfig) -> Path:
    chosen = directory if directory is not None else config.output.directory
    if chosen is None:
        raise BatchError("no output directory: pass one explicitly or set output.directory in the configuration")
    path = Path(chosen)
    if path.exists():
        if not path.is_dir():
            raise BatchError(f"output path exists and is not a directory: {path}")
        if any(path.iterdir()):
            raise BatchError(f"output directory is not empty (nothing is ever overwritten): {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_batch(
    config: SimulationConfig,
    directory: str | Path | None = None,
    *,
    agent_factory: Callable[[AgentSpec], Any] = build_agent,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Play the batch, write its files and return the manifest (a plain dict).

    `progress(done, total)` is called after each game (the CLI uses it; it cannot affect a game).
    """
    if not isinstance(config, SimulationConfig):
        raise BatchError(f"config must be a SimulationConfig, got {type(config).__name__}")
    path = _prepare(directory, config)
    options = config.output
    data = effective_config(config)
    canonical = canonical_json(data)
    (path / CONFIG_NAME).write_bytes((canonical + "\n").encode("utf-8"))

    names = [CONFIG_NAME, "games.csv", "seats.csv", "rounds.csv", SUMMARY_NAME]
    statuses: Counter[str] = Counter()
    built: list[Any] = []  # the current game's agents, in the order run_game builds them (seat order)

    def collecting_factory(spec: AgentSpec) -> Any:
        agent = agent_factory(spec)
        built.append(agent)
        return agent

    agent_table: CsvWriter | None = None  # opened on the first diagnostic row; absent otherwise
    events = open(path / EVENTS_NAME, "w", encoding="utf-8", newline="") if options.public_event_log else None
    private = open(path / DIAGNOSTICS_NAME, "w", encoding="utf-8", newline="") if options.private_diagnostics else None
    try:
        with (
            CsvWriter(path / "games.csv", GAME_COLUMNS) as games,
            CsvWriter(path / "seats.csv", SEAT_COLUMNS) as seats,
            CsvWriter(path / "rounds.csv", ROUND_COLUMNS) as rounds,
        ):
            for index in range(config.game_count):
                recorder = None
                if events is not None or private is not None:
                    recorder = GameRecorder(
                        index, public=options.public_event_log, private=options.private_diagnostics
                    )
                built.clear()
                result = run_game(config, index, agent_factory=collecting_factory, recorder=recorder)
                games.writerow(game_row(result))
                seats.writerows(seat_rows(result))
                rounds.writerows(round_rows(result))
                diagnostic_rows = agent_diagnostic_rows(result, tuple(built))
                if diagnostic_rows:
                    if agent_table is None:
                        agent_table = CsvWriter(path / AGENT_DIAGNOSTICS_NAME, AGENT_DIAGNOSTIC_COLUMNS)
                    agent_table.writerows(diagnostic_rows)
                if events is not None:
                    events.write("".join(line + "\n" for line in recorder.public_lines))
                    events.write(game_end_line(result) + "\n")
                if private is not None:
                    private.write("".join(line + "\n" for line in recorder.private_lines))
                statuses[result.status] += 1
                if progress is not None:
                    progress(index + 1, config.game_count)
    finally:
        for handle in (events, private, agent_table):
            if handle is not None:
                handle.close()
    if events is not None:
        names.append(EVENTS_NAME)
    if private is not None:
        names.append(DIAGNOSTICS_NAME)
    if agent_table is not None:
        names.append(AGENT_DIAGNOSTICS_NAME)

    with CsvWriter(path / SUMMARY_NAME, SUMMARY_COLUMNS) as summary:
        summary.writerows(summarize(read_csv(path / "games.csv"), read_csv(path / "seats.csv")))
    manifest = build_manifest(
        config_canonical=canonical,
        config_data=data,
        directory=path,
        file_names=names,
        status_counts={status: statuses[status] for status in TERMINATION_STATUSES},
    )
    (path / MANIFEST_NAME).write_bytes(manifest_text(manifest).encode("utf-8"))
    return manifest


__all__ = ["BatchError", "effective_config", "run_batch"]
