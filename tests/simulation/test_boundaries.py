"""Structural guards for the simulation package (M8 Stage 2).

* it sits above the engine and nothing below it imports it;
* it has no second RNG implementation and no clock, file or process access;
* it never reads hidden engine fields such as hands or debug views.

Stage 3 added the runner, which sits above the observation and agent layers; the
allowlist below was widened on purpose for exactly those two packages and the new
sibling module. Every other prohibition is unchanged.
"""

from __future__ import annotations

import ast
from pathlib import Path

import chitai.simulation as simulation_pkg

PACKAGE_DIR = Path(simulation_pkg.__file__).parent
SRC_DIR = PACKAGE_DIR.parent

STDLIB = {
    "__future__", "collections", "collections.abc", "dataclasses", "json", "math", "re", "types", "typing",
}  # fmt: skip
SIBLINGS = {"config", "results", "runner", "seeds"}
LOWER_LAYERS = {"engine", "observations", "agents"}
FORBIDDEN_NAMES = {
    "random", "hashlib", "hash", "secrets", "time", "datetime", "os", "sys", "subprocess",
    "open", "print", "input", "pathlib", "shutil", "tempfile", "socket", "threading", "uuid",
}  # fmt: skip
FORBIDDEN_ATTRIBUTES = {"debug_view", "hands", "copy", "chit", "pass_streaks", "timeout_chit"}


def _trees():
    return {path.name: ast.parse(path.read_text(encoding="utf-8")) for path in PACKAGE_DIR.glob("*.py")}


def test_the_package_has_exactly_the_stage_3_modules():
    assert {path.name for path in PACKAGE_DIR.glob("*.py")} == {
        "__init__.py", "config.py", "results.py", "runner.py", "seeds.py",
    }  # fmt: skip


def test_imports_are_stdlib_siblings_or_the_lower_layers_only():
    for file_name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert {alias.name for alias in node.names} <= STDLIB, (file_name, [a.name for a in node.names])
                continue
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 0:
                assert node.module in STDLIB, (file_name, node.module)
            elif node.level == 1:
                assert node.module in SIBLINGS or node.module is None, (file_name, node.module)
            else:
                assert node.level == 2 and node.module in LOWER_LAYERS, (file_name, node.level, node.module)


def test_no_rng_clock_file_or_process_access_and_no_hidden_fields():
    for file_name, tree in _trees().items():
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not names & FORBIDDEN_NAMES, (file_name, names & FORBIDDEN_NAMES)
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not attributes & FORBIDDEN_ATTRIBUTES, (file_name, attributes & FORBIDDEN_ATTRIBUTES)


def test_the_only_randomness_is_the_engines_make_rng():
    uses = []
    for file_name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "make_rng":
                uses.append(file_name)
    assert uses == ["seeds.py"]


def test_lower_layers_do_not_depend_on_simulation():
    for sibling in ("engine", "observations", "agents"):
        for path in (SRC_DIR / sibling).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                elif isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                assert not any("simulation" in module for module in modules), (sibling, path.name)


def test_only_the_runner_reaches_the_observation_and_agent_layers():
    users = {}
    for file_name, tree in _trees().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 2 and node.module in {"observations", "agents"}:
                users.setdefault(node.module, set()).add(file_name)
    assert users == {"observations": {"runner.py"}, "agents": {"runner.py"}}


def test_agents_import_nothing_from_the_simulation_package():
    for path in (SRC_DIR / "agents").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or "simulation" not in node.module, path.name
                assert not any("simulation" in alias.name for alias in node.names), path.name
            elif isinstance(node, ast.Import):
                assert not any("simulation" in alias.name for alias in node.names), path.name
