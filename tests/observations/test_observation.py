"""Observation correctness and privacy of the serialized form (M7)."""

from __future__ import annotations

import dataclasses
import json
import random
from dataclasses import replace

import pytest
from engine.helpers import false_claim_ready

from chitai.engine import (
    Chit,
    ClaimAction,
    DecisionKind,
    GameState,
    Phase,
    ReactAction,
    apply_action,
)
from chitai.observations import Observation, observe

from .support import (
    PLAYER_COUNTS,
    SEED,
    all_values,
    crafted_deal,
    seeded_config,
    start_deal,
    to_passing,
    winning_state,
    with_hidden_changes,
)

EXPECTED_FIELDS = {
    "my_seat", "num_players", "num_rounds", "pass_timeout_seconds", "chit_names",
    "completed_rounds", "attempt", "initiator", "phase", "decision_seat", "decision_kind",
    "scores", "hand_sizes", "my_hand", "my_pass_streak_name", "my_pass_streak_count",
    "winner", "reaction_order", "pending_reactors", "my_turn",
}  # fmt: skip


def game_over_state(n):
    config = seeded_config(n)
    state = start_deal(config, crafted_deal(config, completed_round=n - 1))
    result = apply_action(state, ClaimAction(state.decision_seat))  # a false claim in the last round
    assert result.state.phase is Phase.GAME_OVER
    return result.state


def phase_states(n):
    config = seeded_config(n)
    return {
        "initial": false_claim_ready(config, "initial"),
        "first_pass": to_passing(config),
        "receive": false_claim_ready(config, "receive"),
        "return": false_claim_ready(config, "return"),
        "win_declared": winning_state(n),
        "game_over": game_over_state(n),
    }


def test_the_allowlist_of_observation_fields_is_exactly_the_reviewed_one():
    assert {f.name for f in dataclasses.fields(Observation)} == EXPECTED_FIELDS
    assert set(observe(to_passing(seeded_config(4)), 0).to_dict()) == EXPECTED_FIELDS


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_public_and_private_fields_in_every_phase(n):
    for name, state in phase_states(n).items():
        for seat in range(n):
            obs = observe(state, seat)
            assert obs.my_seat == seat and obs.num_players == n
            assert obs.num_rounds == n and obs.pass_timeout_seconds == 15.0
            assert len(obs.chit_names) == n
            assert obs.completed_rounds == state.completed_rounds and obs.attempt == state.attempt
            assert obs.initiator == state.initiator and obs.phase == state.phase.value
            assert obs.decision_seat == state.decision_seat
            assert obs.scores == state.scores
            assert obs.hand_sizes == tuple(len(h) for h in state.hands)
            assert obs.my_hand == tuple(sorted(c.name for c in state.hands[seat])), name
            assert obs.winner == state.winner


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_decision_kind_and_hand_sizes_follow_the_passing_table(n):
    states = phase_states(n)
    assert observe(states["initial"], 0).decision_kind == DecisionKind.INITIAL_CLAIM.value
    first = observe(states["first_pass"], 1)
    assert first.decision_kind == DecisionKind.INITIATOR_FIRST_PASS.value
    assert first.hand_sizes == (4,) * n
    recv = states["receive"]
    obs = observe(recv, 3 % n)
    assert obs.decision_kind == DecisionKind.NON_INITIATOR_RECEIVE.value
    assert sorted(obs.hand_sizes) == sorted([3, 5] + [4] * (n - 2))
    ret = observe(states["return"], 0)
    assert ret.decision_kind == DecisionKind.INITIATOR_RETURN.value and ret.hand_sizes == (4,) * n


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_my_turn_is_true_only_for_the_seat_that_can_act(n):
    state = to_passing(seeded_config(n))
    assert [observe(state, s).my_turn for s in range(n)] == [s == state.decision_seat for s in range(n)]
    over = game_over_state(n)
    assert not any(observe(over, s).my_turn for s in range(n))


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_reaction_phase_fields(n):
    won = winning_state(n)
    winner = won.winner
    obs = observe(won, (winner + 1) % n)
    assert obs.phase == "win_declared" and obs.winner == winner
    assert obs.decision_seat is None and obs.decision_kind is None
    assert obs.reaction_order == () and winner not in obs.pending_reactors
    assert len(obs.pending_reactors) == n - 1
    pending = [s for s in range(n) if s != winner]
    after = apply_action(won, ReactAction(pending[1])).state
    assert observe(after, winner).reaction_order == (pending[1],)
    assert pending[1] not in observe(after, winner).pending_reactors
    assert [observe(after, s).my_turn for s in range(n)] == [
        s in observe(after, 0).pending_reactors for s in range(n)
    ]


def test_game_over_has_no_decision_point_or_pending_reactors():
    obs = observe(game_over_state(4), 2)
    assert obs.phase == "game_over" and obs.decision_seat is None
    assert obs.pending_reactors == () and obs.winner is None and not obs.my_turn


def test_chit_names_are_the_public_names_in_play():
    for n in PLAYER_COUNTS:
        names = observe(to_passing(seeded_config(n)), 0).chit_names
        assert len(names) == n and len(set(names)) == n


def test_invalid_seats_are_rejected_by_the_host_api():
    state = to_passing(seeded_config(4))
    for bad in (-1, 4, True, 1.0, "1", None):
        with pytest.raises(ValueError):
            observe(state, bad)


def test_observation_is_deterministic_and_ignores_hand_order():
    state = false_claim_ready(seeded_config(5), "receive")
    seat = state.decision_seat
    flipped = replace(state, hands=tuple(tuple(reversed(h)) for h in state.hands))
    assert observe(state, seat) == observe(state, seat) == observe(flipped, seat)
    assert observe(state, seat).to_dict() == observe(flipped, seat).to_dict()


def test_own_streak_is_visible_and_other_streaks_are_not():
    state = to_passing(seeded_config(4))
    streaks = ((0, "Sun", 3), (1, "Moon", 5), (3, "Cloud", 9))
    state = replace(state, pass_streaks=streaks)
    assert (observe(state, 0).my_pass_streak_name, observe(state, 0).my_pass_streak_count) == ("Sun", 3)
    assert (observe(state, 1).my_pass_streak_name, observe(state, 1).my_pass_streak_count) == ("Moon", 5)
    assert (observe(state, 2).my_pass_streak_name, observe(state, 2).my_pass_streak_count) == (None, 0)
    for seat in (0, 1):  # changing the other seats' streaks never changes this seat's observation
        mine = observe(state, seat)
        altered = replace(
            state, pass_streaks=tuple(e if e[0] == seat else (e[0], "Star", 1) for e in streaks)
        )
        assert observe(altered, seat) == mine


def test_streak_appears_after_a_real_pass_and_resets_for_the_new_attempt():
    from engine.helpers import do_pass

    state = to_passing(seeded_config(4))
    seat = state.decision_seat
    name = state.hands[seat][0].name
    state, _ = do_pass(state, name=name)
    assert observe(state, seat).my_pass_streak_name == name
    assert observe(state, seat).my_pass_streak_count == 1
    assert observe(state, (seat + 1) % 4).my_pass_streak_name is None


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_hidden_twins_give_identical_observations(n):
    rng = random.Random(n)
    for name, state in phase_states(n).items():
        for seat in range(n):
            twin, changed = with_hidden_changes(state, seat, rng)
            assert changed, (name, seat)
            assert twin.hands != state.hands or twin.pass_streaks != state.pass_streaks
            assert observe(twin, seat) == observe(state, seat), (name, seat)
            assert observe(twin, seat).to_dict() == observe(state, seat).to_dict()


def test_hidden_twin_positive_control_the_observers_own_hand_does_matter():
    state = false_claim_ready(seeded_config(4), "receive")
    seat = state.decision_seat
    other = (seat + 2) % 4
    hands = list(state.hands)
    hands[seat], hands[other] = hands[other], hands[seat]  # swaps sizes too, so also change a size
    changed = replace(state, hands=tuple(hands))
    assert observe(changed, seat) != observe(state, seat)


def test_serialized_observation_is_json_and_contains_only_primitives():
    for n in (4, 8):
        for state in phase_states(n).values():
            for seat in range(n):
                data = observe(state, seat).to_dict()
                assert json.loads(json.dumps(data)) == data
                for leaf in all_values(data):
                    assert leaf is None or type(leaf) in (str, int, float, bool), leaf


def test_no_seed_config_state_copy_ids_or_engine_objects_leak():
    for n in (4, 6, 8):
        for state in phase_states(n).values():
            for seat in range(n):
                obs = observe(state, seat)
                data = obs.to_dict()
                blobs = (json.dumps(data), repr(obs), str(obs))
                for blob in blobs:
                    assert str(SEED) not in blob
                    assert "Chit(" not in blob and "copy" not in blob
                    assert "GameConfig" not in blob and "GameState" not in blob
                forbidden_keys = {"seed", "config", "hands", "state", "copy", "pass_streaks", "debug"}
                assert not forbidden_keys & set(data)
                for field in dataclasses.fields(obs):
                    value = getattr(obs, field.name)
                    assert not isinstance(value, (GameState, Chit)), field.name
                    if isinstance(value, tuple):
                        assert not any(isinstance(x, (GameState, Chit)) for x in value), field.name


def test_observation_is_frozen():
    obs = observe(to_passing(seeded_config(4)), 0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        obs.my_hand = ()  # type: ignore[misc]
