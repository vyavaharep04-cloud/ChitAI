"""Command line for batches (M8 Stage 5): ``python -m chitai.batch <command>``.

    run CONFIG [--output DIR] [--quiet]   play the batch, write the files (see `runner`)
    summarize DIR                         print the summary of a finished run directory
    validate CONFIG                       check a configuration and print the plan; plays nothing

Configuration files are JSON (a UTF-8 BOM, as PowerShell can write, is accepted). Errors print
``error: ...`` to standard error and exit with status 2. Timing is printed for planning only and is
never written to a file.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from ..eventlog import SUMMARY_COLUMNS, read_csv, summarize
from ..simulation import SimulationConfig, SimulationConfigError, build_agent
from .runner import BatchError, run_batch


def _load(path: str) -> SimulationConfig:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as error:
        raise BatchError(f"cannot read configuration {path}: {error.strerror or error}") from error
    except UnicodeDecodeError as error:
        raise BatchError(f"configuration {path} is not UTF-8 text") from error
    return SimulationConfig.from_json(text)


def _cmd_validate(args: argparse.Namespace) -> int:
    config = _load(args.config)
    for spec in config.lineup:  # fails here, not mid-batch, for an unknown or invalid agent
        build_agent(spec)
    out = sys.stdout
    out.write(f"valid configuration: {config.num_players} players, {config.num_rounds} rounds, {config.game_count} games\n")
    for index, spec in enumerate(config.lineup):
        out.write(f"  lineup {index}: {spec.agent_type} {spec.to_dict()['agent_config']}\n")
    out.write(f"  batch_seed {config.batch_seed}, games_per_seed {config.games_per_seed}, rotate_seats {config.rotate_seats}\n")
    out.write(f"  caps: {config.max_draw_restarts_per_round} draw restarts per round, {config.max_actions_per_attempt} actions per attempt\n")
    out.write("nothing was run\n")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config = _load(args.config)
    step = max(1, config.game_count // 10)

    def progress(done: int, total: int) -> None:
        if not args.quiet and (done % step == 0 or done == total):
            sys.stderr.write(f"  {done}/{total} games\n")

    started = time.perf_counter()
    manifest = run_batch(config, args.output, progress=progress)
    elapsed = time.perf_counter() - started
    out = sys.stdout
    out.write(f"config_sha256 {manifest['config_sha256']}\n")
    for status, count in manifest["status_counts"].items():
        out.write(f"  {status}: {count}\n")
    out.write(f"{len(manifest['files'])} files written ({elapsed:.1f} s, not recorded in any file)\n")
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    try:
        games, seats = read_csv(directory / "games.csv"), read_csv(directory / "seats.csv")
    except OSError as error:
        raise BatchError(f"cannot read the result tables in {directory}: {error.strerror or error}") from error
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(SUMMARY_COLUMNS)
    writer.writerows(summarize(games, seats))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chitai.batch", description="Seeded AI-only game batches.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="play a batch and write its files")
    run.add_argument("config")
    run.add_argument("--output", help="output directory (overrides output.directory; must be new or empty)")
    run.add_argument("--quiet", action="store_true", help="no progress lines")
    run.set_defaults(handler=_cmd_run)
    summarize_parser = commands.add_parser("summarize", help="print the summary of a finished run directory")
    summarize_parser.add_argument("directory")
    summarize_parser.set_defaults(handler=_cmd_summarize)
    validate = commands.add_parser("validate", help="check a configuration; plays nothing")
    validate.add_argument("config")
    validate.set_defaults(handler=_cmd_validate)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (SimulationConfigError, BatchError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 2


__all__ = ["main"]
