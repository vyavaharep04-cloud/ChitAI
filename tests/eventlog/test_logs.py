"""Public event log, private diagnostics and the runner's recorder hook (M8 Stage 4)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest import mock

import pytest
from observations.support import SEED
from simulation.runner_support import (
    BATCH_SEED,
    Scripted,
    Trigger,
    claim_policy,
    crafted_start,
    factory_for,
    misbehaving_policy,
    rule_policy,
    sim_config,
    stall_policy,
)

import chitai.simulation.runner as runner_module
from chitai.engine import CHIT_NAMES, new_game
from chitai.eventlog import GameRecorder, game_end_line, public_event_line
from chitai.observations import observe_event
from chitai.simulation import game_seed, run_game

FORBIDDEN_KEYS = {"hands", "chit", "chit_name", "copy", "timeout_chit", "my_hand", "seed", "game_seed", "debug"}


def recorded_play(config, game_index=0, policies=None, start=new_game, *, private=False):
    """(result, recorder, events) where `events` are the engine events seen by an independent spy."""
    factory, created = factory_for(policies or {})
    recorder = GameRecorder(game_index, private=private)
    events = []
    real = runner_module.apply_action

    def spy(state, action):
        outcome = real(state, action)
        events.extend(getattr(outcome, "events", ()))
        return outcome

    opening_events = []

    def tracking_start(game_config):
        accepted = start(game_config)
        opening_events.extend(accepted.events)
        return accepted

    with mock.patch.object(runner_module, "apply_action", spy):
        result = runner_module._run_game(config, game_index, factory, tracking_start, recorder)
    return result, recorder, opening_events + events, created


def test_the_public_log_is_exactly_the_public_view_of_every_engine_event_in_order():
    config = sim_config(4, ["c"] * 4, batch_seed=SEED)
    result, recorder, events, _ = recorded_play(config, 0, {"c": claim_policy}, crafted_start({0}))
    expected = [public_event_line(0, e) for e in events]
    assert recorder.public_lines == expected and len(expected) >= 10
    for line, event in zip(recorder.public_lines, events):
        record = json.loads(line)
        assert record["record"] == "event" and record["game_index"] == 0
        assert record["event"] == observe_event(event, None)
    seqs = [json.loads(line)["event"]["seq"] for line in recorder.public_lines]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs) and seqs[0] == 0


def test_the_public_log_contains_no_hand_chit_copy_or_seed():
    # A game with a deal, passes, a forced pass, a draw, a valid win and a false claim.
    trigger = Trigger(lambda o: o.phase == "passing")
    policies = {"s": misbehaving_policy("raise", trigger)}
    config = sim_config(4, ["s"] * 4, batch_seed=SEED, draws=5)
    result, recorder, _, _ = recorded_play(config, 0, policies, crafted_start({0}))
    text = "\n".join(recorder.public_lines)
    kinds = {json.loads(line)["event"]["type"] for line in recorder.public_lines}
    assert {"deal", "chit_passed", "decision_timed_out"} <= kinds
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in FORBIDDEN_KEYS, key
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        else:
            assert value not in CHIT_NAMES, value  # no chit name appears as any value

    for line in recorder.public_lines:
        walk(json.loads(line))
    for secret in (str(SEED), str(game_seed(SEED, 0))):
        assert secret not in text
    # chit_passed shows who passed to whom, never the chit
    passed = [json.loads(l)["event"] for l in recorder.public_lines if '"chit_passed"' in l]
    assert passed and all(set(e) == {"type", "seq", "completed_round", "attempt", "from_seat", "to_seat"} for e in passed)


def test_a_draw_is_public_but_never_names_the_chit():
    config = sim_config(4, ["s"] * 4, draws=1)
    result, recorder, _, _ = recorded_play(config, 0, {"s": stall_policy}, private=True)
    draws = [json.loads(l)["event"] for l in recorder.public_lines if '"attempt_drawn"' in l]
    assert draws and all("chit" not in d for d in draws)
    private_draws = [json.loads(l)["event"] for l in recorder.private_lines if '"attempt_drawn"' in l]
    assert private_draws and all("chit" in d for d in private_draws)  # only the private file has it


def test_the_recorder_changes_nothing_about_the_game():
    config = sim_config(4, batch_seed=BATCH_SEED)
    plain = run_game(config, 0)
    for private in (False, True):
        assert run_game(config, 0, recorder=GameRecorder(0, private=private)) == plain


def test_agents_see_the_same_things_with_and_without_a_recorder():
    config = sim_config(4, ["r"] * 4)
    runs = []
    for recorder in (None, GameRecorder(0, private=True)):
        factory, created = factory_for({"r": rule_policy})
        runner_module._run_game(config, 0, factory, new_game, recorder)
        runs.append([(a.calls) for a in created])
    assert runs[0] == runs[1]


def test_the_recorder_is_never_passed_to_an_agent_or_the_factory():
    tree = ast.parse(Path(runner_module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            names = {a.id for a in node.args if isinstance(a, ast.Name)} | {k.value.id for k in node.keywords if isinstance(k.value, ast.Name)}
            callee = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if callee in {"choose_action", "_decide", "agent_factory", "factory", "_seat_agent", "observe", "legal_actions_for"}:
                assert "recorder" not in names, callee


def test_game_end_lines_say_how_a_game_ended_and_carry_no_seed():
    done = run_game(sim_config(4), 0)
    stopped = run_game(sim_config(4, actions=3), 0)
    for result in (done, stopped):
        record = json.loads(game_end_line(result))
        assert record["status"] == result.status and record["actions"] == result.actions
        assert str(result.game_seed) not in game_end_line(result)
    assert json.loads(game_end_line(stopped))["status"] == "action_cap_reached"
    assert json.loads(game_end_line(stopped))["stopped_attempt"] == stopped.stopped_attempt


def test_private_diagnostics_hold_hands_and_fault_kinds_but_never_exception_text():
    trigger = Trigger(lambda o: o.phase == "initial_claims")
    policies = {"m": misbehaving_policy("raise", trigger)}
    result, recorder, _, _ = recorded_play(sim_config(4, ["m"] * 4), 0, policies, crafted_start(set()), private=True)
    faults = [json.loads(l) for l in recorder.private_lines if '"fault"' in l]
    assert faults == [{"record": "fault", "game_index": 0, "seat": 0, "kind": "exception", "completed_round": 0, "attempt": 1}]
    assert "boom" not in "\n".join(recorder.private_lines)
    deal = json.loads(recorder.private_lines[0])
    assert deal["event"]["type"] == "deal" and "hands" in deal["event"]
    # a fault is a host record: it is not a public event
    assert all('"fault"' not in line for line in recorder.public_lines)


def test_nothing_private_is_collected_unless_asked_for():
    recorder = GameRecorder(0)
    run_game(sim_config(4), 0, recorder=recorder)
    assert recorder.public_lines and recorder.private_lines == []
    off = GameRecorder(0, public=False)
    run_game(sim_config(4), 0, recorder=off)
    assert off.public_lines == [] and off.private_lines == []
