"""Layering rules for the batch package (M8 Stage 5)."""

from __future__ import annotations

import ast
from pathlib import Path

import chitai.batch as package

PACKAGE_DIR = Path(package.__file__).parent
STDLIB = {"__future__", "argparse", "collections", "collections.abc", "csv", "hashlib", "json", "pathlib", "platform", "sys", "time", "typing"}
LOWER = {"eventlog", "simulation"}
FORBIDDEN_NAMES = {"random", "datetime", "os", "subprocess", "socket", "threading", "uuid", "hash"}
FORBIDDEN_ATTRIBUTES = {"hands", "pass_streaks", "timeout_chit", "copy", "chit", "seed", "debug_view"}


def _trees():
    return {p.name: ast.parse(p.read_text(encoding="utf-8")) for p in PACKAGE_DIR.glob("*.py")}


def test_the_package_has_exactly_the_stage_5_modules():
    assert set(_trees()) == {"__init__.py", "__main__.py", "cli.py", "manifest.py", "runner.py"}


def test_imports_are_stdlib_siblings_package_root_or_the_eventlog_and_simulation_layers():
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name in STDLIB for a in node.names), (name, [a.name for a in node.names])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    assert node.module in STDLIB, (name, node.module)
                elif node.level == 1:
                    assert node.module is None or "." not in node.module, (name, node.module)
                else:
                    assert node.level == 2 and (node.module in LOWER or node.module is None), (name, node.level, node.module)


def test_no_randomness_and_no_hidden_fields_and_only_the_cli_prints_or_reads_the_clock():
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, (name, node.id)
                if name != "cli.py":
                    assert node.id not in {"print", "time", "sys"}, (name, node.id)
            if isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_ATTRIBUTES, (name, node.attr)
                if name != "cli.py":
                    assert node.attr != "perf_counter", name


def test_nothing_below_the_batch_package_imports_it():
    for lower in ("engine", "observations", "agents", "simulation", "eventlog"):
        for path in (PACKAGE_DIR.parent / lower).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    assert "batch" not in (node.module or "").split("."), (lower, path.name)
                    assert "batch" not in [a.name for a in node.names], (lower, path.name)
