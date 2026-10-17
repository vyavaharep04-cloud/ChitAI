"""Shared test helpers for M2 engine tests."""

from __future__ import annotations

import json

from chitai.engine import (
    CHIT_NAMES,
    Accepted,
    ClaimAction,
    DeclineAction,
    Deal,
    GameConfig,
    build_deck,
    chit_names_for,
    initiator_for_round,
    start_from_deal,
)


def make_config(n: int = 4, rounds: int | None = None, seed: int = 1) -> GameConfig:
    return GameConfig(num_players=n, num_rounds=rounds if rounds is not None else n, seed=seed)


def crafted_deal(
    config: GameConfig,
    matching: frozenset[int] | set[int] = frozenset(),
    completed_round: int = 0,
    attempt: int = 1,
) -> Deal:
    """A valid deck deal in which exactly the seats in `matching` hold four
    chits of one name and every other seat holds a mixed (non-matching) hand."""
    n = config.num_players
    matching = frozenset(matching)
    others = [s for s in range(n) if s not in matching]
    if len(others) == 1:
        raise ValueError("exactly one non-matching seat is impossible (its leftover chits must match)")
    names = chit_names_for(n)
    deck = build_deck(n)
    hands: dict[int, tuple] = {}
    for seat in matching:
        hands[seat] = tuple(c for c in deck if c.name == names[seat])
    leftover = sorted(
        (c for c in deck if names.index(c.name) in set(others)),
        key=lambda c: (c.copy, names.index(c.name)),
    )
    for i, seat in enumerate(others):
        hands[seat] = tuple(leftover[4 * i : 4 * i + 4])
    return Deal(
        completed_round=completed_round,
        attempt=attempt,
        initiator=initiator_for_round(config, completed_round),
        hands=tuple(hands[s] for s in range(n)),
    )


def start(config: GameConfig, matching=frozenset(), completed_round: int = 0):
    result = start_from_deal(config, crafted_deal(config, matching, completed_round))
    assert isinstance(result, Accepted)
    return result.state


def decline_all_but(state, apply_action, count: int):
    """Decline for the next `count` decision-point seats; returns (state, events)."""
    events = []
    for _ in range(count):
        result = apply_action(state, DeclineAction(state.decision_seat))
        assert isinstance(result, Accepted)
        state = result.state
        events.extend(result.events)
    return state, events


def all_names_json_free(view: dict) -> bool:
    """True when no chit name appears anywhere in a JSON rendering of `view`."""
    text = json.dumps(view)
    return not any(name in text for name in CHIT_NAMES)


__all__ = [
    "ClaimAction",
    "DeclineAction",
    "make_config",
    "crafted_deal",
    "start",
    "decline_all_but",
    "all_names_json_free",
]
