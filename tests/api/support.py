"""Helpers for the web-interface tests: a seat-local policy that sees only what a
browser would see (the `state` message), never the engine."""

from __future__ import annotations

from collections import Counter
from typing import Any

SEED = 123456789012345  # distinctive, so a leaked seed is easy to find in text


def policy(message: dict[str, Any], always_claim: bool = False) -> dict[str, Any] | None:
    """The action request a player would make from one `state` message, or None
    when it has nothing to decide. Uses only the message."""
    legal = message["legal_actions"]
    if not legal:
        return None
    kinds = {a["type"] for a in legal}
    hand = message["observation"]["my_hand"]
    counts = Counter(hand)
    if "react" in kinds:
        return {"type": "action", "action": "react"}
    if "claim" in kinds and (always_claim or max(counts.values()) >= 4):
        return {"type": "action", "action": "claim"}
    if "decline" in kinds:
        return {"type": "action", "action": "decline"}
    names = [a["chit_name"] for a in legal if a["type"] == "pass"]
    return {"type": "action", "action": "pass", "chit_name": min(names, key=lambda n: (counts[n], n))}
