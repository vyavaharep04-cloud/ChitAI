"""Layering and privacy rules for the eventlog package (M8 Stage 4)."""

from __future__ import annotations

import ast
from pathlib import Path

import chitai.eventlog as package

PACKAGE_DIR = Path(package.__file__).parent
SRC_DIR = PACKAGE_DIR.parent
STDLIB = {"__future__", "collections", "collections.abc", "csv", "pathlib", "typing"}
LOWER = {"observations", "simulation"}
FORBIDDEN_NAMES = {"random", "hashlib", "time", "datetime", "os", "sys", "subprocess", "print", "input", "socket", "threading", "uuid"}
FORBIDDEN_ATTRIBUTES = {"hands", "pass_streaks", "timeout_chit", "copy", "chit", "seed", "debug_view"}


def _trees():
    return {p.name: ast.parse(p.read_text(encoding="utf-8")) for p in PACKAGE_DIR.glob("*.py")}


def test_the_package_has_exactly_the_stage_4_modules():
    assert set(_trees()) == {"__init__.py", "diagnostics.py", "jsonl.py", "recorder.py", "summary.py", "tables.py"}


def test_imports_are_stdlib_siblings_or_the_observation_and_simulation_layers():
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
                    assert node.level == 2 and node.module in LOWER, (name, node.level, node.module)


def test_no_randomness_clock_or_process_access_and_no_hidden_fields():
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, (name, node.id)
            if isinstance(node, ast.Attribute) and not (name == "diagnostics.py" and node.attr == "debug_view"):
                assert node.attr not in FORBIDDEN_ATTRIBUTES, (name, node.attr)


def test_only_diagnostics_reads_a_private_event_view():
    for name, tree in _trees().items():
        used = any(isinstance(n, ast.Attribute) and n.attr == "debug_view" for n in ast.walk(tree))
        assert used == (name == "diagnostics.py"), name


def test_lower_layers_do_not_depend_on_the_logging_or_batch_packages():
    for lower in ("engine", "observations", "agents", "simulation"):
        for path in (SRC_DIR / lower).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                modules = []
                if isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""] + [a.name for a in node.names]
                elif isinstance(node, ast.Import):
                    modules = [a.name for a in node.names]
                assert not any(m.split(".")[0] in {"eventlog", "batch"} or "eventlog" in m or "batch" in m for m in modules), (lower, path.name, modules)
