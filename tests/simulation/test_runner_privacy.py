"""Privacy and protocol boundaries of the runner (M8 Stage 3): agents see only their own
observation and legal actions, and never anything the host knows."""

from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest
from observations.support import PLAYER_COUNTS, SEED, with_hidden_changes

import chitai.simulation.runner as runner_module
from chitai.engine import ClaimAction, DeclineAction, Phase, ReactAction
from chitai.observations import NamePassAction, Observation, legal_actions_for, observe
from chitai.simulation import AgentSpec, game_seed

from .runner_support import (
    COMPLETING_GAME,
    claim_policy,
    crafted_start,
    play,
    rule_policy,
    sim_config,
    stall_policy,
)

ALLOWED = (ClaimAction, DeclineAction, ReactAction, NamePassAction)


def _recording(order):
    def policy(observation, legal, call):
        order.append((observation, legal))
        return rule_policy(observation, legal, call)

    return policy


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_agents_get_exactly_the_observation_and_legal_actions_of_the_deciding_seat(n):
    order: list = []
    config = sim_config(n, ["r"] * n, batch_seed=SEED)
    result, steps, _ = play(config, COMPLETING_GAME, {"r": _recording(order)})
    assert result.completed and len(order) == len(steps)  # no faults: one call per engine action
    for (observation, legal), step in zip(order, steps):
        seat = step.action.seat
        assert type(observation) is Observation and type(legal) is tuple
        assert observation == observe(step.state, seat) and legal == legal_actions_for(step.state, seat)
        assert observation.my_seat == seat and observation.my_turn is True
        assert all(type(a) in ALLOWED and a.seat == seat for a in legal)


def test_nothing_the_host_knows_reaches_an_agent():
    order: list = []
    config = sim_config(4, ["r"] * 4, batch_seed=SEED)
    play(config, COMPLETING_GAME, {"r": _recording(order)})
    secrets = {str(SEED), str(game_seed(SEED, COMPLETING_GAME))}
    for observation, legal in order:
        text = repr(observation) + repr(legal)
        assert not any(secret in text for secret in secrets)
        assert "Chit(" not in text and "copy" not in text and "timeout_chit" not in text
        assert not any(hasattr(a, "chit") for a in legal)


def test_an_observation_does_not_change_when_only_hidden_information_changes():
    order: list = []
    config = sim_config(5, ["r"] * 5, batch_seed=SEED)
    _, steps, _ = play(config, COMPLETING_GAME, {"r": _recording(order)})
    rng = random.Random(7)
    checked = changed = 0
    for (observation, _), step in zip(order, steps):
        if step.state.phase is not Phase.PASSING:
            continue
        twin, differs = with_hidden_changes(step.state, step.action.seat, rng)
        checked += 1
        changed += bool(differs)
        assert observe(twin, step.action.seat) == observation
    assert checked > 20 and changed > 0


def test_the_factory_receives_only_a_lineup_entry():
    received = []

    def factory(spec):
        received.append(spec)
        return runner_module.build_agent(spec)

    runner_module._run_game(sim_config(4, batch_seed=SEED), COMPLETING_GAME, factory, runner_module.new_game)
    assert len(received) == 4 and all(type(spec) is AgentSpec for spec in received)
    assert not any(str(SEED) in repr(spec) for spec in received)


def test_the_agent_is_only_ever_called_with_the_observation_and_the_legal_actions():
    tree = ast.parse(Path(runner_module.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "choose_action"]
    assert len(calls) == 1
    assert [a.id for a in calls[0].args] == ["observation", "legal"] and not calls[0].keywords


def test_an_agent_cannot_mutate_what_the_next_agent_sees():
    seen = []

    def policy(observation, legal, call):
        seen.append(observation)
        try:
            observation.my_seat = 99  # frozen dataclass
        except Exception:
            pass
        return claim_policy(observation, legal, call)

    play(sim_config(4, ["r"] * 4), 0, {"r": policy}, crafted_start(set()))
    assert all(o.my_seat in range(4) for o in seen)
