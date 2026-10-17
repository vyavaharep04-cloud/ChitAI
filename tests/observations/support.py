"""Shared helpers for observation tests. Reuses the engine test helpers."""

from __future__ import annotations

import json
import random
from dataclasses import replace

from engine.helpers import (  # noqa: F401  (re-exported for the tests)
    crafted_deal,
    decline_to_passing,
    deal_from_names,
    do_pass,
    make_config,
    start,
    start_deal,
    to_passing,
)

from chitai.engine import (
    Accepted,
    ClaimAction,
    DeclineAction,
    PassAction,
    Phase,
    ReactAction,
    build_deck,
    check_invariants,
    new_game,
    apply_action,
    start_from_deal,
)

SEED = 123456789  # distinctive, so a leaked seed is easy to spot in text
PLAYER_COUNTS = (4, 5, 6, 7, 8)


def seeded_config(n: int = 4, rounds: int | None = None):
    return make_config(n, rounds, seed=SEED)


def winning_state(n: int, position: str = "initial", winner_seat: int | None = None):
    """A WIN_DECLARED state (no reactions yet) after a valid claim at `position`
    ('initial' or 'return')."""
    config = seeded_config(n)
    if position == "initial":
        deck = build_deck(n)
        names = [deck[4 * s].name for s in range(n)]
        hands = tuple(tuple(c for c in deck if c.name == names[s]) for s in range(n))
        from chitai.engine import Deal

        state = start_from_deal(config, Deal(0, 1, 0, hands)).state
        seat = state.decision_seat
        result = apply_action(state, ClaimAction(seat))
        assert isinstance(result, Accepted) and result.state.phase is Phase.WIN_DECLARED
        return result.state
    raise ValueError(position)


def with_hidden_changes(state, observer: int, rng: random.Random):
    """A twin of `state` that differs from it only in information `observer`
    must not have: the other seats' chits are permuted among those seats (the
    winner's hand is left alone in a decided round, so the claim stays
    consistent) and every other seat's anti-stall streak is changed. The
    observer's own hand and streak, all public fields and all hand sizes are
    kept. Returns (twin, whether anything hidden actually changed)."""
    n = state.config.num_players
    frozen = {observer}
    if state.phase in (Phase.WIN_DECLARED, Phase.GAME_OVER) and state.winner is not None:
        frozen.add(state.winner)
    free = [s for s in range(n) if s not in frozen]
    pool = [chit for s in free for chit in state.hands[s]]
    sizes = [len(state.hands[s]) for s in free]
    for _ in range(50):
        rng.shuffle(pool)
        hands = list(state.hands)
        at = 0
        for seat, size in zip(free, sizes):
            hands[seat] = tuple(pool[at : at + size])
            at += size
        changed = any(hands[s] != state.hands[s] for s in free)
        streaks = []
        for seat, name, count in state.pass_streaks:
            if seat == observer:
                streaks.append((seat, name, count))
            else:
                others = [x for x in sorted({c.name for c in build_deck(n)}) if x != name]
                streaks.append((seat, rng.choice(others), rng.randint(1, 8)))
        twin = replace(state, hands=tuple(hands), pass_streaks=tuple(streaks))
        try:
            check_invariants(twin)
        except Exception:
            continue
        return twin, changed or twin.pass_streaks != state.pass_streaks
    return state, False


def walk(config, rng: random.Random, max_steps: int = 60):
    """Yield successive states of a random game that only declines and passes
    (never claims), so claim-validity (a public fact) cannot differ between a
    state and its hidden twin."""
    state = new_game(config).state
    yield state
    for _ in range(max_steps):
        if state.phase is not Phase.INITIAL_CLAIMS and state.phase is not Phase.PASSING:
            return
        seat = state.decision_seat
        if state.phase is Phase.INITIAL_CLAIMS:
            action = DeclineAction(seat)
        else:
            action = PassAction(seat, rng.choice(state.hands[seat]))
        result = apply_action(state, action)
        assert isinstance(result, Accepted)
        state = result.state
        yield state


def all_values(obj):
    """Every leaf of a nested dict/list structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from all_values(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from all_values(value)
    else:
        yield obj


__all__ = [
    "SEED",
    "PLAYER_COUNTS",
    "seeded_config",
    "winning_state",
    "with_hidden_changes",
    "walk",
    "all_values",
    "json",
]
