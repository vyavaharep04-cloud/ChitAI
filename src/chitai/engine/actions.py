"""Player actions (§5A). M2: initial-phase claim and decline. M3: passing.

Actions are plain data. They are *requests*; only the authoritative engine
decides whether they are legal and what they do. Engine-generated timeout
actions and reactions arrive in later milestones.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chits import Chit


@dataclass(frozen=True)
class ClaimAction:
    """Explicitly claim. Never generated automatically by the engine (§3A.4)."""

    seat: int


@dataclass(frozen=True)
class DeclineAction:
    """Explicitly decline the current claim opportunity.

    Declining exists only in the initial claim phase (§3A.3). During ordinary
    passing a player who does not claim simply passes (§3A.4: passing forfeits
    the opportunity), so there is no separate decline there.
    """

    seat: int


@dataclass(frozen=True)
class PassAction:
    """Pass one specific physical chit instance to the next seat clockwise.

    The chit is addressed by physical instance (§3A.4: "pass one of the five
    physical chit instances"), not by name, so the engine never has to choose
    between two copies of the same name on the player's behalf.
    """

    seat: int
    chit: Chit


Action = ClaimAction | DeclineAction | PassAction
