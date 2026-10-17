"""Player actions (§5A). M2: initial-phase claim and decline. M3: passing. M5: reactions.
M6: host-issued timeouts.

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


@dataclass(frozen=True)
class ReactAction:
    """A non-winner reacts to a valid win (§3A.5). M5.

    A reaction is an explicit engine action. The authoritative engine's
    accepted-action order *is* the reaction order, which fixes the non-winners'
    scores; no clock, timer or latency is part of the engine. A seeded latency
    model (later milestone) or a timeout (M6) may generate these actions, but
    the engine only ever sees the resulting action order.
    """

    seat: int


@dataclass(frozen=True)
class TimeoutAction:
    """The host reports that `seat`'s decision timer expired (M6, §3A.7).

    The engine has no clock, so it cannot check that time has really elapsed;
    the host (server or simulator) issues this action when its own timer runs
    out, and the engine validates only that a timeout is *available* for that
    seat. An accepted timeout resolves through the ordinary transition for the
    decision point and never claims on the player's behalf:

    * initial claim phase: an automatic decline (§3A.3);
    * ordinary passing: a forced pass of one legal physical chit, chosen
      uniformly with the seeded timeout stream (§3A.7);
    * reaction phase: the one remaining non-winner's reaction, and only when
      exactly one non-winner remains (§3A.5).
    """

    seat: int


Action = ClaimAction | DeclineAction | PassAction | ReactAction | TimeoutAction
