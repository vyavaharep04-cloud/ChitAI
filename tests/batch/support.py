"""Helpers for the batch tests (M8 Stage 5)."""

from __future__ import annotations

import json
from pathlib import Path

from chitai.simulation import SimulationConfig


def config_data(**overrides) -> dict:
    """A small, fast, valid batch description (cap values are arbitrary test fixtures)."""
    data = {
        "lineup": [{"agent_type": "rulebot"}] * 4,
        "num_players": 4, "num_rounds": 4, "batch_seed": 11, "game_count": 4,
        "max_draw_restarts_per_round": 50, "max_actions_per_attempt": 400,
    }  # fmt: skip
    data.update(overrides)
    return data


def make_config(**overrides) -> SimulationConfig:
    return SimulationConfig.from_dict(config_data(**overrides))


def write_config(path: Path, **overrides) -> Path:
    path.write_text(json.dumps(config_data(**overrides)), encoding="utf-8")
    return path


def read_files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}
