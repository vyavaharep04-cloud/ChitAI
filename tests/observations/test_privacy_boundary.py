"""Structural privacy checks of the observations package (M7)."""

from __future__ import annotations

import ast
from pathlib import Path

import chitai.observations as observations_pkg

PACKAGE_DIR = Path(observations_pkg.__file__).parent

# Engine names that carry hidden information or randomness; the observation layer
# must never import them (the seed reconstructs every deal, `timeout_chit` names
# the forced chit, and `Chit`/`PassAction` expose physical copy ids).
FORBIDDEN_IMPORTS = {
    "timeout_chit", "deal_round", "derive_seed", "make_rng", "GameConfig", "Deal",
    "build_deck", "start_from_deal", "new_game", "DEAL", "TIMEOUT", "TimeoutAction",
    "timeout_action", "update_pass_streaks",
}  # fmt: skip


def _sources():
    return {path.name: ast.parse(path.read_text(encoding="utf-8")) for path in PACKAGE_DIR.glob("*.py")}


def test_the_observation_layer_does_not_import_hidden_or_random_engine_names():
    for name, tree in _sources().items():
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert not imported & FORBIDDEN_IMPORTS, (name, imported & FORBIDDEN_IMPORTS)


def test_the_observation_layer_never_calls_debug_view_or_reads_seed_config_or_streak_fields_of_others():
    for name, tree in _sources().items():
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert "debug_view" not in attrs, name
        assert "seed" not in attrs, name


def test_the_observation_layer_imports_only_the_engine_package_its_siblings_and_the_stdlib():
    for name, tree in _sources().items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 0:
                assert node.module in {"__future__", "dataclasses", "typing"}, (name, node.module)
            elif node.level == 2:
                assert node.module == "engine", (name, node.module)  # the package, not a submodule
            else:
                assert node.level == 1, (name, node.level)  # a sibling module


def test_the_engine_does_not_depend_on_the_observation_layer():
    engine_dir = PACKAGE_DIR.parent / "engine"
    for path in engine_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "observations" not in text, path.name
