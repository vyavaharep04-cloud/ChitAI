"""Agent faults, host timeouts and reaction handling (M8 Stage 3).

A fault must never reach the engine, never change the game except through the host-issued
timeout the engine itself defines, and be counted apart from that timeout.
"""

from __future__ import annotations

import pytest

import chitai.simulation.runner as runner_module
from chitai.engine import (
    Accepted,
    ClaimAction,
    DeclineAction,
    Phase,
    TimeoutAction,
    apply_action,
    new_game,
    timeout_action,
)
from chitai.observations import Observation, legal_actions_for, observe
from chitai.simulation import STATUS_AGENT_FAULT_UNRESOLVABLE

from .runner_support import (
    DECISION_POINTS,
    FAULT_KINDS,
    Scripted,
    Trigger,
    bad_choice,
    crafted_start,
    misbehaving_policy,
    never_rejected,
    opening_state,
    play,
    replay,
    rule_policy,
    sim_config,
)

EXPECTED_KIND = {
    "raise": runner_module.FAULT_EXCEPTION,
    "none": runner_module.FAULT_NOT_AN_ACTION,
    "object": runner_module.FAULT_NOT_AN_ACTION,
    "engine_pass": runner_module.FAULT_NOT_AN_ACTION,
    "subclass": runner_module.FAULT_NOT_AN_ACTION,
    "wrong_seat": runner_module.FAULT_WRONG_SEAT,
    "bad_seat_type": runner_module.FAULT_BAD_FIELD,
    "bad_name_type": runner_module.FAULT_BAD_FIELD,
    "timeout": runner_module.FAULT_TIMEOUT_CHOICE,
    "unheld_name": runner_module.FAULT_ILLEGAL,
    "illegal": runner_module.FAULT_ILLEGAL,
}


def _first_state():
    return crafted_start(set())(sim_config(4).game_config(1)).state


@pytest.mark.parametrize("kind", FAULT_KINDS)
def test_every_kind_of_bad_answer_is_classified_as_a_fault_before_the_engine(kind, monkeypatch):
    monkeypatch.setattr(runner_module, "apply_action", lambda *a: pytest.fail("a fault reached the engine"))
    state = _first_state()
    seat = state.decision_seat
    agent = Scripted("x", lambda o, legal, call: bad_choice(kind, o, legal))
    assert runner_module._decide(state, seat, agent) == EXPECTED_KIND[kind]


def test_a_good_answer_becomes_the_engine_action_and_is_never_rewritten():
    state = _first_state()
    decision = runner_module._decide(state, state.decision_seat, Scripted("x", rule_policy))
    assert decision == DeclineAction(state.decision_seat) and type(decision) is DeclineAction


def test_a_timeout_the_engine_would_issue_is_not_something_an_agent_may_choose():
    state = _first_state()
    host = timeout_action(state)
    assert isinstance(host, TimeoutAction)
    agent = Scripted("x", lambda o, legal, call: host)
    assert runner_module._decide(state, state.decision_seat, agent) == runner_module.FAULT_TIMEOUT_CHOICE


# --- faults at every decision point -----------------------------------------------------------------


def _scenario(point):
    """(start, matching) for a decision point: reactions need a crafted valid win."""
    return crafted_start({0}) if point.startswith("reaction") else crafted_start(set())


def _run_pair(point, kind):
    start = _scenario(point)
    config = sim_config(4, ["m"] * 4, actions=600)
    baseline, base_steps, _ = play(config, 0, {"m": rule_policy}, start)
    trigger = Trigger(DECISION_POINTS[point])
    result, steps, agents = play(config, 0, {"m": misbehaving_policy(kind, trigger)}, start)
    assert len(trigger.fired) == 1, f"the {point} decision never occurred"
    return config, start, baseline, base_steps, result, steps, agents, trigger.fired[0][0]


@pytest.mark.parametrize("point", ["initial_claim", "initiator_first_pass", "non_initiator_receive", "initiator_return", "reaction_final"])
@pytest.mark.parametrize("kind", FAULT_KINDS)
def test_a_fault_is_resolved_by_the_host_timeout_and_changes_nothing_else(point, kind):
    config, start, _, base_steps, result, steps, agents, seat = _run_pair(point, kind)

    # The game before the fault is identical to the fault-free game.
    split = next(i for i, (a, b) in enumerate(zip(steps, base_steps)) if a.action != b.action or a.state != b.state)
    assert steps[:split] == base_steps[:split]
    # At the fault the engine saw exactly its own host timeout, accepted.
    state = steps[split].state
    assert steps[split].action == timeout_action(state) == TimeoutAction(seat)
    assert steps[split].result == apply_action(state, TimeoutAction(seat))
    assert never_rejected(steps)
    assert replay(opening_state(config, 0, start), steps) == [s for s in steps][-1].result.state

    # One fault and one timeout, on the faulty seat only; nobody else is touched.
    for record in result.seats:
        assert (record.agent_faults, record.timeouts) == ((1, 1) if record.seat == seat else (0, 0))
    # The agent was asked once for the decision and was told nothing about what went wrong.
    for agent in agents:
        for observation, legal in agent.calls:
            assert type(observation) is Observation and type(legal) is tuple


@pytest.mark.parametrize("kind", FAULT_KINDS)
def test_a_nonfinal_reaction_fault_defers_the_seat_to_the_end_of_the_win(kind):
    config, start, baseline, base_steps, result, steps, agents, seat = _run_pair("reaction_nonfinal", kind)
    expected = baseline.rounds[0].reaction_order
    faulty_first = expected[0]
    assert seat == faulty_first, "the first pending seat in the seeded order is asked first"
    order = result.rounds[0].reaction_order
    # the others keep their seeded relative order, the faulty seat reacts last, by host timeout
    assert order == expected[1:] + (seat,)
    timeout_steps = [step for step in steps if isinstance(step.action, TimeoutAction)]
    assert [step.action for step in timeout_steps] == [TimeoutAction(seat)]
    assert result.rounds[0].score_changes[seat] == 1  # last reactor scores 1
    for record in result.seats:
        assert (record.agent_faults, record.timeouts) == ((1, 1) if record.seat == seat else (0, 0))
    # it was never asked a second time for this win
    asked = [o for o, _ in agents[seat].calls if o.phase == "win_declared" and (o.completed_rounds, o.attempt) == (0, 1)]
    assert len(asked) == 1
    assert never_rejected(steps) and result.rounds[0].outcome == "valid_win"


def test_two_faulty_reactors_among_three_leave_no_safe_timeout_and_stop_the_game():
    trigger = Trigger(lambda o: o.phase == "win_declared", limit=2)
    policies = {"m": misbehaving_policy("raise", trigger)}
    config = sim_config(4, ["m"] * 4)
    result, steps, agents = play(config, 0, policies, crafted_start({0}))
    assert result.status == STATUS_AGENT_FAULT_UNRESOLVABLE
    assert (result.completed_rounds, result.stopped_attempt, result.rounds) == (0, 1, ())
    assert all(s.score == 0 for s in result.seats) and result.winning_seats == ()
    assert sum(s.agent_faults for s in result.seats) == 2 and sum(s.timeouts for s in result.seats) == 0
    # one claim and exactly one valid reaction were accepted; nobody was asked twice
    assert [type(step.action).__name__ for step in steps] == ["ClaimAction", "ReactAction"]
    for agent in agents:
        assert len([o for o, _ in agent.calls if o.phase == "win_declared"]) <= 1
    assert steps[-1].result.state.phase is Phase.WIN_DECLARED


def test_every_pending_reactor_faulting_stops_without_any_reaction():
    trigger = Trigger(lambda o: o.phase == "win_declared", limit=3)
    result, steps, _ = play(sim_config(4, ["m"] * 4), 0, {"m": misbehaving_policy("none", trigger)}, crafted_start({0}))
    assert result.status == STATUS_AGENT_FAULT_UNRESOLVABLE and result.actions == 1
    assert sum(s.agent_faults for s in result.seats) == 3


def test_a_faulty_seat_asked_last_is_resolved_by_timeout_when_it_is_the_only_one_left():
    # Seats that fault and are deferred do not block the win as long as only one remains.
    trigger = Trigger(lambda o: o.phase == "win_declared", limit=1)
    result, steps, _ = play(sim_config(4, ["m"] * 4), 0, {"m": misbehaving_policy("object", trigger)}, crafted_start({0}))
    assert result.rounds[0].outcome == "valid_win" and result.status != STATUS_AGENT_FAULT_UNRESOLVABLE


def test_a_fault_never_triggers_a_retry():
    calls = []

    def policy(observation, legal, call):
        calls.append((observation.my_seat, observation.completed_rounds, observation.attempt, observation.phase, observation.decision_kind, observation.my_hand))
        return None  # always faults

    result, steps, _ = play(sim_config(4, ["m"] * 4, actions=30), 0, {"m": policy})
    # every call was a distinct decision of an unchanged-or-advancing state: no state is asked twice
    keys = [(s.state, s.action) for s in steps]
    assert len(set(map(repr, keys))) == len(keys)
    assert result.actions == len(steps) == sum(s.timeouts for s in result.seats) == sum(s.agent_faults for s in result.seats)


def test_exception_details_never_leave_the_runner():
    trigger = Trigger(lambda o: True, limit=1000)
    result, _, _ = play(sim_config(4, ["m"] * 4, actions=20), 0, {"m": misbehaving_policy("raise", trigger)})
    assert "boom" not in repr(result)
