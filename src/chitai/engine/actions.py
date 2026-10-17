"""Player actions (§5A). Milestone 2: initial-phase claim and decline only.

Actions are plain data. They are *requests*; only the authoritative engine
decides whether they are legal and what they do. Passing actions, engine
generated timeout actions, and reactions arrive in later milestones.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimAction:
    """Explicitly claim. Never generated automatically by the engine (§3A.4)."""

    seat: int


@dataclass(frozen=True)
class DeclineAction:
    """Explicitly decline the current claim opportunity."""

    seat: int


Action = ClaimAction | DeclineAction
