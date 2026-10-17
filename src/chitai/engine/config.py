"""Game configuration and validation (PROJECT_CONTEXT.md §3A.2, §3A.6, §3A.7, §5A)."""

from __future__ import annotations

from dataclasses import dataclass

MIN_PLAYERS = 4
MAX_PLAYERS = 8
MAX_PASS_TIMEOUT_SECONDS = 15.0


class ConfigError(ValueError):
    """Raised when a GameConfig violates the documented constraints."""


def _is_int(value: object) -> bool:
    # bool is a subclass of int; True/False are not acceptable numeric settings.
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class GameConfig:
    """Validated, immutable game settings.

    num_players: 4-8 (§3A.2).
    num_rounds: configured *completed*-round count; a positive multiple of
        num_players (§3A.6).
    pass_timeout_seconds: greater than 0 and at most 15 seconds; the room
        creator may choose a shorter duration (§3A.7). The default is the
        maximum, 15 seconds. The engine has no clock: the host uses this value
        for its own timers and issues a `TimeoutAction` when one expires (M6).
    seed: master seed for all seeded randomness (§3A.7).
    """

    num_players: int
    num_rounds: int
    seed: int
    pass_timeout_seconds: float = MAX_PASS_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not _is_int(self.num_players):
            raise ConfigError(f"num_players must be an integer, got {self.num_players!r}")
        if not MIN_PLAYERS <= self.num_players <= MAX_PLAYERS:
            raise ConfigError(
                f"num_players must be between {MIN_PLAYERS} and {MAX_PLAYERS}, "
                f"got {self.num_players}"
            )

        if not _is_int(self.num_rounds):
            raise ConfigError(f"num_rounds must be an integer, got {self.num_rounds!r}")
        if self.num_rounds <= 0 or self.num_rounds % self.num_players != 0:
            raise ConfigError(
                f"num_rounds must be a positive multiple of num_players "
                f"({self.num_players}), got {self.num_rounds}"
            )

        if not _is_int(self.seed):
            raise ConfigError(f"seed must be an integer, got {self.seed!r}")

        timeout = self.pass_timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ConfigError(f"pass_timeout_seconds must be a number, got {timeout!r}")
        # `not (0 < t <= max)` also rejects NaN; infinity exceeds the maximum.
        if not 0 < timeout <= MAX_PASS_TIMEOUT_SECONDS:
            raise ConfigError(
                f"pass_timeout_seconds must be greater than 0 and at most "
                f"{MAX_PASS_TIMEOUT_SECONDS:g}, got {timeout!r}"
            )
