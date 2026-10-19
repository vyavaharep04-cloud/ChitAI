"""Validated, JSON-loadable simulation configuration (M8 Stage 2).

`SimulationConfig` describes a batch: who plays (the lineup), how games are seeded,
the game parameters, the two safety caps and the output options. It only describes
and validates. It builds no agents, runs nothing and writes nothing.

The two caps have **no default** (owner decision D1/D2): `max_draw_restarts_per_round`
and `max_actions_per_attempt` must be given explicitly, because suitable values are
to be chosen from Stage 3 measurements. Game rules are validated by the engine's
own `GameConfig`, never re-implemented here.

JSON shape (every key except the optional ones is required)::

    {
      "schema_version": 1,                      # optional on load; always written
      "lineup": [{"agent_type": "rulebot", "agent_config": {}}, ...],
      "num_players": 4, "num_rounds": 4,
      "pass_timeout_seconds": 15.0,             # optional (engine default)
      "batch_seed": 2026, "game_count": 8,
      "games_per_seed": 1,                      # optional: 1 = independent seeds
      "rotate_seats": true,                     # optional
      "max_draw_restarts_per_round": ..., "max_actions_per_attempt": ...,
      "output": {"directory": null, "public_event_log": true, "private_diagnostics": false}
    }
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ..engine import MAX_PASS_TIMEOUT_SECONDS, ConfigError, GameConfig

CONFIG_SCHEMA_VERSION = 1

_AGENT_TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")


class SimulationConfigError(ValueError):
    """Raised when a simulation configuration is invalid."""


def _is_int(value: object) -> bool:
    # bool is a subclass of int; True/False are not acceptable numeric settings.
    return isinstance(value, int) and not isinstance(value, bool)


def _require_int(name: str, value: object, minimum: int) -> int:
    if not _is_int(value):
        raise SimulationConfigError(f"{name} must be an integer, got {value!r}")
    if value < minimum:  # type: ignore[operator]
        raise SimulationConfigError(f"{name} must be at least {minimum}, got {value}")
    return value  # type: ignore[return-value]


def _require_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise SimulationConfigError(f"{name} must be true or false, got {value!r}")
    return value


def _check_json(path: str, value: object) -> None:
    """Accept only JSON primitives, lists and string-keyed objects; finite numbers."""
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SimulationConfigError(f"{path} must be a finite number, got {value!r}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_json(f"{path}[{index}]", item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SimulationConfigError(f"{path} has a non-string key {key!r}")
            _check_json(f"{path}.{key}", item)
        return
    raise SimulationConfigError(f"{path} is not a JSON value: {value!r}")


def _plain(value: Any) -> Any:
    """A deep copy using plain dicts and lists only (JSON-shaped). Accepts frozen
    values (read-only mappings, tuples) as well as ordinary ones."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    """A deep, recursively read-only copy: objects become read-only mappings and
    arrays become tuples, at every depth. Nothing is shared with `value`."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def canonical_json(value: Any) -> str:
    """Sorted-key, compact, ASCII JSON: the same value always gives the same text.
    Frozen values (as held by `AgentSpec.agent_config`) serialise like plain ones."""
    return json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


@dataclass(frozen=True)
class AgentSpec:
    """Describes one lineup entry: an agent type and its JSON configuration.

    This is a description only; turning it into an agent is the runner's job.
    `agent_config` is deep-copied and recursively read-only: nested objects are
    read-only mappings and nested arrays are tuples.
    """

    agent_type: str
    agent_config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.agent_type, str) or not _AGENT_TYPE.fullmatch(self.agent_type):
            raise SimulationConfigError(
                f"agent_type must be a name such as 'rulebot', got {self.agent_type!r}"
            )
        if not isinstance(self.agent_config, Mapping):
            raise SimulationConfigError(f"agent_config must be an object, got {self.agent_config!r}")
        _check_json(f"agent_config of {self.agent_type}", self.agent_config)
        object.__setattr__(self, "agent_config", _freeze(self.agent_config))

    def to_dict(self) -> dict[str, Any]:
        return {"agent_type": self.agent_type, "agent_config": _plain(self.agent_config)}

    @classmethod
    def from_dict(cls, data: object) -> AgentSpec:
        if not isinstance(data, Mapping):
            raise SimulationConfigError(f"a lineup entry must be an object, got {data!r}")
        unknown = set(data) - {"agent_type", "agent_config"}
        if unknown:
            raise SimulationConfigError(f"unknown lineup entry keys: {sorted(unknown)}")
        if "agent_type" not in data:
            raise SimulationConfigError("a lineup entry needs an agent_type")
        return cls(data["agent_type"], data.get("agent_config", {}))


@dataclass(frozen=True)
class OutputOptions:
    """Where and what a run writes (D9). Nothing is written by this stage.

    directory: the run's output directory, or None for no files.
    public_event_log: write the public event stream (on by default).
    private_diagnostics: write private diagnostics (opt-in, off by default).
    """

    directory: str | None = None
    public_event_log: bool = True
    private_diagnostics: bool = False

    def __post_init__(self) -> None:
        if self.directory is not None and (
            not isinstance(self.directory, str) or not self.directory or "\0" in self.directory
        ):
            raise SimulationConfigError(f"output directory must be a non-empty path or null, got {self.directory!r}")
        _require_bool("public_event_log", self.public_event_log)
        _require_bool("private_diagnostics", self.private_diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": self.directory,
            "public_event_log": self.public_event_log,
            "private_diagnostics": self.private_diagnostics,
        }

    @classmethod
    def from_dict(cls, data: object) -> OutputOptions:
        if not isinstance(data, Mapping):
            raise SimulationConfigError(f"output must be an object, got {data!r}")
        unknown = set(data) - {"directory", "public_event_log", "private_diagnostics"}
        if unknown:
            raise SimulationConfigError(f"unknown output keys: {sorted(unknown)}")
        return cls(**dict(data))


_REQUIRED = (
    "lineup",
    "num_players",
    "num_rounds",
    "batch_seed",
    "game_count",
    "max_draw_restarts_per_round",
    "max_actions_per_attempt",
)
_OPTIONAL = ("schema_version", "pass_timeout_seconds", "games_per_seed", "rotate_seats", "output")


@dataclass(frozen=True)
class SimulationConfig:
    """A validated batch description.

    lineup: one `AgentSpec` per seat of the base seating; its length must equal
        `num_players`. With `rotate_seats` the lineup moves one seat per game
        (see `seeds.seat_assignment`).
    num_players, num_rounds, pass_timeout_seconds: the engine's `GameConfig`
        settings, validated by the engine itself.
    batch_seed: the master seed of the batch (any integer).
    game_count: how many games the batch plays (at least 1).
    games_per_seed: 1 gives every game its own seed; k > 1 makes each run of k
        consecutive games share one seed (paired mode). `game_count` must then be a
        multiple of k so that no group is left incomplete.
    max_draw_restarts_per_round: a round may be redealt at most this many times
        (0 means the first draw stops the game). REQUIRED, no default (D1).
    max_actions_per_attempt: most accepted engine actions between two deals.
        REQUIRED, no default (D2).
    """

    lineup: tuple[AgentSpec, ...]
    num_players: int
    num_rounds: int
    batch_seed: int
    game_count: int
    max_draw_restarts_per_round: int
    max_actions_per_attempt: int
    pass_timeout_seconds: float = MAX_PASS_TIMEOUT_SECONDS
    games_per_seed: int = 1
    rotate_seats: bool = True
    output: OutputOptions = field(default_factory=OutputOptions)

    def __post_init__(self) -> None:
        if isinstance(self.lineup, (str, bytes)) or not isinstance(self.lineup, Sequence):
            raise SimulationConfigError(f"lineup must be a list of agents, got {self.lineup!r}")
        lineup = tuple(self.lineup)
        for entry in lineup:
            if not isinstance(entry, AgentSpec):
                raise SimulationConfigError(f"lineup entries must be AgentSpec, got {entry!r}")
        object.__setattr__(self, "lineup", lineup)

        if not _is_int(self.batch_seed):
            raise SimulationConfigError(f"batch_seed must be an integer, got {self.batch_seed!r}")
        _require_int("game_count", self.game_count, 1)
        _require_int("games_per_seed", self.games_per_seed, 1)
        if self.game_count % self.games_per_seed != 0:
            raise SimulationConfigError(
                f"game_count ({self.game_count}) must be a multiple of games_per_seed ({self.games_per_seed})"
            )
        _require_bool("rotate_seats", self.rotate_seats)
        _require_int("max_draw_restarts_per_round", self.max_draw_restarts_per_round, 0)
        _require_int("max_actions_per_attempt", self.max_actions_per_attempt, 1)
        if not isinstance(self.output, OutputOptions):
            raise SimulationConfigError(f"output must be OutputOptions, got {self.output!r}")

        # The engine owns the rules for players, rounds and timeout: reuse its validation.
        try:
            GameConfig(
                num_players=self.num_players,
                num_rounds=self.num_rounds,
                seed=0,
                pass_timeout_seconds=self.pass_timeout_seconds,
            )
        except ConfigError as error:
            raise SimulationConfigError(str(error)) from error
        if len(lineup) != self.num_players:
            raise SimulationConfigError(
                f"lineup has {len(lineup)} agents but num_players is {self.num_players}"
            )

    # --- derived values --------------------------------------------------------------

    def game_config(self, game_seed: int) -> GameConfig:
        """The engine `GameConfig` for one game of this batch."""
        return GameConfig(
            num_players=self.num_players,
            num_rounds=self.num_rounds,
            seed=game_seed,
            pass_timeout_seconds=self.pass_timeout_seconds,
        )

    # --- JSON ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "lineup": [spec.to_dict() for spec in self.lineup],
            "num_players": self.num_players,
            "num_rounds": self.num_rounds,
            "pass_timeout_seconds": self.pass_timeout_seconds,
            "batch_seed": self.batch_seed,
            "game_count": self.game_count,
            "games_per_seed": self.games_per_seed,
            "rotate_seats": self.rotate_seats,
            "max_draw_restarts_per_round": self.max_draw_restarts_per_round,
            "max_actions_per_attempt": self.max_actions_per_attempt,
            "output": self.output.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: object) -> SimulationConfig:
        if not isinstance(data, Mapping):
            raise SimulationConfigError(f"a configuration must be an object, got {type(data).__name__}")
        unknown = set(data) - set(_REQUIRED) - set(_OPTIONAL)
        if unknown:
            raise SimulationConfigError(f"unknown configuration keys: {sorted(unknown)}")
        missing = [key for key in _REQUIRED if key not in data]
        if missing:
            raise SimulationConfigError(f"missing required configuration keys: {missing}")
        version = data.get("schema_version", CONFIG_SCHEMA_VERSION)
        if not _is_int(version) or version != CONFIG_SCHEMA_VERSION:
            raise SimulationConfigError(
                f"schema_version must be {CONFIG_SCHEMA_VERSION}, got {version!r}"
            )
        lineup = data["lineup"]
        if not isinstance(lineup, (list, tuple)):
            raise SimulationConfigError(f"lineup must be a list, got {lineup!r}")
        kwargs: dict[str, Any] = {key: data[key] for key in _REQUIRED if key != "lineup"}
        for key in ("pass_timeout_seconds", "games_per_seed", "rotate_seats"):
            if key in data:
                kwargs[key] = data[key]
        if "output" in data:
            kwargs["output"] = OutputOptions.from_dict(data["output"])
        return cls(lineup=tuple(AgentSpec.from_dict(entry) for entry in lineup), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> SimulationConfig:
        """Parse JSON text. Duplicate keys and NaN/Infinity are errors."""

        def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise SimulationConfigError(f"duplicate key in JSON: {key!r}")
                result[key] = value
            return result

        def no_constants(name: str) -> Any:
            raise SimulationConfigError(f"{name} is not valid in a configuration")

        try:
            data = json.loads(text, object_pairs_hook=no_duplicates, parse_constant=no_constants)
        except json.JSONDecodeError as error:
            raise SimulationConfigError(f"invalid JSON: {error}") from error
        return cls.from_dict(data)


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "AgentSpec",
    "OutputOptions",
    "SimulationConfig",
    "SimulationConfigError",
    "canonical_json",
]
