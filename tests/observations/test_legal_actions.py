"""Per-seat, name-based legal actions and the translation to engine actions (M7)."""

from __future__ import annotations

import json
import random
from dataclasses import replace

import pytest
from engine.helpers import false_claim_ready

from chitai.engine import (
    Accepted,
    ClaimAction,
    DeclineAction,
    PassAction,
    Phase,
    ReactAction,
    TimeoutAction,
    apply_action,
    legal_actions,
    timeout_action,
)
from chitai.observations import (
    NamePassAction,
    action_to_dict,
    legal_actions_for,
    to_engine_action,
)

from .support import (
    PLAYER_COUNTS,
    SEED,
    seeded_config,
    to_passing,
    walk,
    winning_state,
    with_hidden_changes,
)
from .test_observation import game_over_state, phase_states


def every_legal(state):
    return {s: legal_actions_for(state, s) for s in range(state.config.num_players)}


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_initial_claim_phase_offers_claim_and_decline_to_the_decision_seat_only(n):
    state = phase_states(n)["initial"]
    for seat, actions in every_legal(state).items():
        if seat == state.decision_seat:
            assert actions == (ClaimAction(seat), DeclineAction(seat))
        else:
            assert actions == ()


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_first_pass_has_no_claim_and_one_pass_per_distinct_name(n):
    state = phase_states(n)["first_pass"]
    seat = state.decision_seat
    actions = legal_actions_for(state, seat)
    names = sorted({c.name for c in state.hands[seat]})
    assert actions == tuple(NamePassAction(seat, name) for name in names)
    assert not any(isinstance(a, (ClaimAction, DeclineAction)) for a in actions)
    assert all(legal_actions_for(state, s) == () for s in range(n) if s != seat)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
@pytest.mark.parametrize("phase", ["receive", "return"])
def test_claim_opportunities_come_with_passes_and_never_a_decline(n, phase):
    state = phase_states(n)[phase]
    seat = state.decision_seat
    actions = legal_actions_for(state, seat)
    assert actions[0] == ClaimAction(seat)
    assert not any(isinstance(a, DeclineAction) for a in actions)
    assert [a.chit_name for a in actions[1:]] == sorted({c.name for c in state.hands[seat]})
    assert all(legal_actions_for(state, s) == () for s in range(n) if s != seat)


def test_claim_is_offered_even_when_the_hand_does_not_match_and_not_when_it_does_at_the_first_pass():
    config = seeded_config(4)
    # no seat matches: still offered at an initial opportunity and at a receive
    assert ClaimAction(0) in legal_actions_for(false_claim_ready(config, "initial"), 0)
    first = to_passing(config)
    assert not any(isinstance(a, ClaimAction) for a in legal_actions_for(first, first.decision_seat))


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_reactions_are_exposed_only_to_pending_non_winners(n):
    won = winning_state(n)
    winner = won.winner
    pending = [s for s in range(n) if s != winner]
    for seat in range(n):
        expected = (ReactAction(seat),) if seat in pending else ()
        assert legal_actions_for(won, seat) == expected
    first, second = pending[0], pending[-1]
    after = apply_action(won, ReactAction(first)).state
    assert legal_actions_for(after, first) == () and legal_actions_for(after, winner) == ()
    assert legal_actions_for(after, second) == (ReactAction(second),)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_game_over_offers_nothing(n):
    over = game_over_state(n)
    assert every_legal(over) == {s: () for s in range(n)}


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_every_returned_action_belongs_to_its_seat_and_is_accepted_by_the_engine(n):
    for state in phase_states(n).values():
        for seat, actions in every_legal(state).items():
            for action in actions:
                assert action.seat == seat
                engine_action = to_engine_action(state, action)
                assert engine_action is not None and engine_action.seat == seat
                assert isinstance(apply_action(state, engine_action), Accepted), action


def test_the_list_is_the_engine_list_filtered_and_relabelled_not_a_second_rule_set():
    rng = random.Random(7)
    for n in (4, 6, 8):
        for state in walk(seeded_config(n), rng, 40):
            engine_by_seat = {s: [a for a in legal_actions(state) if a.seat == s] for s in range(n)}
            for seat in range(n):
                mine = legal_actions_for(state, seat)
                assert len(mine) == len({_label(a) for a in engine_by_seat[seat]})
                translated = {to_engine_action(state, a) for a in mine}
                assert translated <= set(engine_by_seat[seat])
                assert {_label(a) for a in translated} == {_label(a) for a in engine_by_seat[seat]}


def _label(action):
    if isinstance(action, PassAction):
        return ("pass", action.seat, action.chit.name)
    if isinstance(action, NamePassAction):
        return ("pass", action.seat, action.chit_name)
    return (type(action).__name__, action.seat)


def test_no_timeout_is_ever_exposed_or_translatable():
    rng = random.Random(3)
    states = [s for n in (4, 7) for s in walk(seeded_config(n), rng, 25)]
    states += [s for n in (4, 5) for s in phase_states(n).values()]
    for state in states:
        for seat in range(state.config.num_players):
            assert not any(isinstance(a, TimeoutAction) for a in legal_actions_for(state, seat))
            assert to_engine_action(state, TimeoutAction(seat)) is None
    last = apply_action(winning_state(4), ReactAction(1)).state
    last = apply_action(last, ReactAction(2)).state
    assert timeout_action(last) is not None  # the host can time out the last reactor...
    assert all(not isinstance(a, TimeoutAction) for s in range(4) for a in legal_actions_for(last, s))


def test_actions_are_independent_of_hand_order_and_of_hidden_information():
    rng = random.Random(11)
    for n in (4, 5, 8):
        for state in phase_states(n).values():
            for seat in range(n):
                twin, _ = with_hidden_changes(state, seat, rng)
                assert legal_actions_for(twin, seat) == legal_actions_for(state, seat)
    state = false_claim_ready(seeded_config(5), "receive")
    flipped = replace(state, hands=tuple(tuple(reversed(h)) for h in state.hands))
    assert legal_actions_for(flipped, state.decision_seat) == legal_actions_for(state, state.decision_seat)


def test_name_pass_translates_to_a_held_physical_chit_of_that_name():
    state = false_claim_ready(seeded_config(4), "receive")
    seat = state.decision_seat
    for action in legal_actions_for(state, seat):
        if isinstance(action, NamePassAction):
            engine_action = to_engine_action(state, action)
            assert isinstance(engine_action, PassAction)
            assert engine_action.chit in state.hands[seat] and engine_action.chit.name == action.chit_name
            copies = [c.copy for c in state.hands[seat] if c.name == action.chit_name]
            assert engine_action.chit.copy == min(copies)


def test_translation_rejects_everything_that_is_not_a_legal_action_for_that_seat():
    state = false_claim_ready(seeded_config(6), "receive")  # five chits, six names: one is always unheld
    seat = state.decision_seat
    other = (seat + 1) % 6
    held = state.hands[seat][0].name
    unheld = next(n for n in ("Sun", "Moon", "Star", "Cloud", "Flame", "Wave") if all(c.name != n for c in state.hands[seat]))
    bad = [
        NamePassAction(other, held),  # another seat's pass
        NamePassAction(seat, unheld),  # a name the seat does not hold
        NamePassAction(seat, "Nonexistent"),
        NamePassAction(seat, None),
        NamePassAction(True, held),
        NamePassAction(-1, held),
        NamePassAction(99, held),
        ClaimAction(other),
        DeclineAction(seat),  # no decline during passing
        ReactAction(seat),  # no reaction outside the reaction phase
        PassAction(seat, state.hands[seat][0]),  # engine-level pass: not an agent action
        TimeoutAction(seat),
        None,
        "pass",
        42,
    ]
    for action in bad:
        assert to_engine_action(state, action) is None, action
    assert to_engine_action(state, ClaimAction(seat)) == ClaimAction(seat)


def test_translation_refuses_actions_after_the_decision_moved_on():
    state = false_claim_ready(seeded_config(4), "receive")
    seat = state.decision_seat
    name = legal_actions_for(state, seat)[1]
    moved = apply_action(state, to_engine_action(state, name)).state
    assert to_engine_action(moved, name) is None  # no longer this seat's decision


def test_a_full_game_can_be_played_through_the_agent_interface_only():
    rng = random.Random(5)
    config = seeded_config(4, rounds=4)
    from chitai.engine import new_game

    state = new_game(config).state
    steps = 0
    while state.phase is not Phase.GAME_OVER and steps < 3000:
        steps += 1
        seat = (
            state.decision_seat
            if state.decision_seat is not None
            else rng.choice([s for s in range(4) if legal_actions_for(state, s)])
        )
        actions = legal_actions_for(state, seat)
        assert actions
        choice = rng.choice(actions)
        result = apply_action(state, to_engine_action(state, choice))
        assert isinstance(result, Accepted)
        state = result.state
    assert state.phase is Phase.GAME_OVER


def test_invalid_seat_is_a_host_error():
    state = to_passing(seeded_config(4))
    for bad in (-1, 4, True, None, "0"):
        with pytest.raises(ValueError):
            legal_actions_for(state, bad)


def test_action_serialization_has_no_copy_id_and_no_seed():
    state = false_claim_ready(seeded_config(4), "receive")
    seat = state.decision_seat
    dicts = [action_to_dict(a) for a in legal_actions_for(state, seat)]
    text = json.dumps(dicts)
    assert "copy" not in text and str(SEED) not in text and "Chit(" not in text
    assert dicts[0] == {"type": "claim", "seat": seat}
    assert all(d["type"] == "pass" and set(d) == {"type", "seat", "chit_name"} for d in dicts[1:])
    assert action_to_dict(DeclineAction(1)) == {"type": "decline", "seat": 1}
    assert action_to_dict(ReactAction(2)) == {"type": "react", "seat": 2}
    with pytest.raises(TypeError):
        action_to_dict(TimeoutAction(0))
    with pytest.raises(TypeError):
        action_to_dict(PassAction(0, state.hands[0][0]))


def test_no_engine_pass_action_or_chit_object_appears_in_any_legal_list():
    for n in (4, 8):
        for state in phase_states(n).values():
            for actions in every_legal(state).values():
                for action in actions:
                    assert not isinstance(action, (PassAction, TimeoutAction))
                    assert not hasattr(action, "chit")
                    assert "Chit(" not in repr(action) and "copy" not in repr(action)
