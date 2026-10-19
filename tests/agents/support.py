"""Shared helpers for agent tests. Reuses the engine and observation test helpers."""

from __future__ import annotations

from engine.helpers import deal_from_names, decline_to_passing, do_pass, start_deal  # noqa: F401
from observations.support import PLAYER_COUNTS, seeded_config, walk, winning_state  # noqa: F401
from observations.test_observation import game_over_state, phase_states  # noqa: F401

from chitai.engine import COPIES_PER_NAME, chit_names_for
from chitai.observations import legal_actions_for, observe


def passing_state(n: int, hands: dict[int, list[str]]):
    """The first-pass state (every initial claim declined) of round 0 in which
    each seat in `hands` holds exactly the given four names and the remaining
    chits are dealt to the other seats in canonical name order."""
    config = seeded_config(n)
    names = chit_names_for(n)
    left = {name: COPIES_PER_NAME for name in names}
    for hand in hands.values():
        assert len(hand) == 4
        for name in hand:
            left[name] -= 1
            assert left[name] >= 0, f"more than four copies of {name}"
    pool = [name for name in names for _ in range(left[name])]
    per_seat = []
    for seat in range(n):
        if seat in hands:
            per_seat.append(list(hands[seat]))
        else:
            per_seat.append(pool[:4])
            pool = pool[4:]
    assert not pool
    return decline_to_passing(start_deal(config, deal_from_names(config, per_seat)))


def view(state, seat: int):
    """The (observation, legal actions) pair the host would hand to `seat`'s agent."""
    return observe(state, seat), legal_actions_for(state, seat)
