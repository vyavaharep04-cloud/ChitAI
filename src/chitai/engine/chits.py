"""Fixed chit names, physical chit instances, and deck construction (§3A.2).

Matching uses chit *names* only. Symbols and colours belong to the future
presentation layer and never appear here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import MAX_PLAYERS, MIN_PLAYERS

COPIES_PER_NAME = 4
CHITS_PER_HAND = 4

# Fixed chit names (customization is out of scope, §3A.2). N players use the
# first N names. Eight names support the maximum of eight players. The specific
# words are neutral placeholders; renaming them here changes no game rule.
CHIT_NAMES: tuple[str, ...] = (
    "Sun",
    "Moon",
    "Star",
    "Cloud",
    "Flame",
    "Wave",
    "Leaf",
    "Stone",
)

assert len(CHIT_NAMES) == MAX_PLAYERS and len(set(CHIT_NAMES)) == MAX_PLAYERS


@dataclass(frozen=True, order=True)
class Chit:
    """One physical chit instance.

    `copy` (0..3) distinguishes the four copies of a name for uniform random
    selection and private debug logs. Rules must compare `name` only.
    """

    name: str
    copy: int

    def matches(self, other: "Chit") -> bool:
        """True when both chits have the same name (copy index is irrelevant)."""
        return self.name == other.name


def chit_names_for(num_players: int) -> tuple[str, ...]:
    """The N chit names in play for an N-player game."""
    _check_player_count(num_players)
    return CHIT_NAMES[:num_players]


def build_deck(num_players: int) -> tuple[Chit, ...]:
    """The canonical (unshuffled) deck: N names x 4 copies = 4N chits."""
    return tuple(
        Chit(name, copy)
        for name in chit_names_for(num_players)
        for copy in range(COPIES_PER_NAME)
    )


def _check_player_count(num_players: int) -> None:
    if (
        not isinstance(num_players, int)
        or isinstance(num_players, bool)
        or not MIN_PLAYERS <= num_players <= MAX_PLAYERS
    ):
        raise ValueError(
            f"num_players must be an integer between {MIN_PLAYERS} and {MAX_PLAYERS}, "
            f"got {num_players!r}"
        )
