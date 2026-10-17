"""Shared test helpers for engine tests (M2, M3, M4)."""

from __future__ import annotations

import json

from chitai.engine import (
    CHIT_NAMES,
    Accepted,
    Chit,
    ClaimAction,
    DeclineAction,
    Deal,
    PassAction,
    GameConfig,
    apply_action,
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


def deal_from_names(config: GameConfig, names_per_seat, completed_round: int = 0) -> Deal:
    """A deal where seat i holds the chit names `names_per_seat[i]` (a list of
    four names); physical copies are assigned in order. Must use each of the N
    names exactly four times overall."""
    next_copy: dict[str, int] = {}
    hands = []
    for names in names_per_seat:
        hand = []
        for name in names:
            hand.append(Chit(name, next_copy.get(name, 0)))
            next_copy[name] = next_copy.get(name, 0) + 1
        hands.append(tuple(hand))
    return Deal(
        completed_round=completed_round,
        attempt=1,
        initiator=initiator_for_round(config, completed_round),
        hands=tuple(hands),
    )


def start_deal(config: GameConfig, deal: Deal):
    result = start_from_deal(config, deal)
    assert isinstance(result, Accepted)
    return result.state


def decline_to_passing(state):
    """Decline every initial opportunity; returns the first-pass state."""
    for _ in range(state.config.num_players):
        result = apply_action(state, DeclineAction(state.decision_seat))
        assert isinstance(result, Accepted)
        state = result.state
    return state


def to_passing(config: GameConfig, matching=frozenset(), completed_round: int = 0):
    return decline_to_passing(start(config, matching, completed_round))


def do_pass(state, chit=None, name: str | None = None):
    """Have the decision seat pass `chit`, or its first chit named `name`, or its
    first chit. Returns (state, events)."""
    hand = state.hands[state.decision_seat]
    if chit is None:
        chit = next(c for c in hand if name is None or c.name == name)
    result = apply_action(state, PassAction(state.decision_seat, chit))
    assert isinstance(result, Accepted), result
    return result.state, result.events


def all_names_json_free(view: dict) -> bool:
    """True when no chit name appears anywhere in a JSON rendering of `view`."""
    text = json.dumps(view)
    return not any(name in text for name in CHIT_NAMES)


# --- M4: forcing false claims -----------------------------------------------------------

CLAIM_POSITIONS = ("initial", "receive", "return")


def hand_matches(hand) -> bool:
    return len({chit.name for chit in hand}) == 1


def false_claim_ready(config: GameConfig, position: str, completed_round: int = 0, attempt: int = 1):
    """A state in which `state.decision_seat` is about to make an eligible claim
    that is guaranteed false. `position` is "initial" (initial claim phase),
    "receive" (a non-initiator holding five) or "return" (the initiator when
    the chit comes back). The deal has no matching seat, so no hand can match."""
    deal = crafted_deal(config, matching=set(), completed_round=completed_round, attempt=attempt)
    state = start_deal(config, deal)
    if position == "initial":
        return state
    state = decline_to_passing(state)
    if position == "receive":
        state, _ = do_pass(state)
        return state
    assert position == "return"
    for _ in range(config.num_players):
        state, _ = do_pass(state)
    assert state.decision_seat == state.initiator and len(state.hands[state.initiator]) == 4
    return state


def play_false_claim_rounds(config: GameConfig):
    """Play a whole game in which every round ends in a false claim, using the
    real seeded deals: at each initial opportunity a seat claims if its hand does
    not match and declines if it does. Returns (final_state, events, claimants).
    Fails if a round reaches ordinary passing (every seat held a matching hand)."""
    from chitai.engine import Phase, new_game

    result = new_game(config)
    state, events, claimants = result.state, list(result.events), []
    while state.phase is not Phase.GAME_OVER:
        assert state.phase is Phase.INITIAL_CLAIMS, state.phase
        seat = state.decision_seat
        if hand_matches(state.hands[seat]):
            action = DeclineAction(seat)
        else:
            action = ClaimAction(seat)
            claimants.append(seat)
        step = apply_action(state, action)
        assert isinstance(step, Accepted), step
        state = step.state
        events.extend(step.events)
    return state, events, claimants


__all__ = [
    "CLAIM_POSITIONS",
    "false_claim_ready",
    "play_false_claim_rounds",
    "hand_matches",
    "ClaimAction",
    "DeclineAction",
    "make_config",
    "crafted_deal",
    "start",
    "decline_all_but",
    "deal_from_names",
    "start_deal",
    "decline_to_passing",
    "to_passing",
    "do_pass",
    "all_names_json_free",
]
