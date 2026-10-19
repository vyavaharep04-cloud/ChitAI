"""Shared helpers for the runner tests (M8 Stage 3).

Scripted agents implement the real `Agent` protocol and return an element of the
tuple they are given unless a test deliberately makes one misbehave. An engine spy
records every `apply_action` call the runner makes, so tests can replay the exact
accepted actions through the plain engine and compare.
"""

from __future__ import annotations

from collections import namedtuple
from contextlib import contextmanager
from dataclasses import replace
from unittest import mock

import chitai.simulation.runner as runner_module
from chitai.agents import RuleBot
from chitai.engine import (
    Accepted,
    Chit,
    ClaimAction,
    DeclineAction,
    PassAction,
    ReactAction,
    Rejected,
    TimeoutAction,
    apply_action,
    new_game,
    start_from_deal,
)
from chitai.observations import NamePassAction
from chitai.simulation import SimulationConfig, build_agent

from engine.helpers import crafted_deal

# Arbitrary fixture values for tests: the caps have no default and these are not proposals.
BIG_ACTIONS = 4000
BIG_DRAWS = 1000
BATCH_SEED = 2026
# Pinned: with BATCH_SEED, rotate_seats False and generous caps, game 0 of an all-RuleBot
# lineup completes for every player count 4..8 (found by running; see test_runner_games).
COMPLETING_GAME = 0

Step = namedtuple("Step", "state action result")

_RULEBOT = RuleBot()


# --- agents -----------------------------------------------------------------------------------


class Scripted:
    """An agent whose decisions come from `policy(observation, legal, call_number)`.

    Records every call as `(observation, legal)` so tests can inspect exactly what the
    agent was given.
    """

    agent_type = "scripted"
    agent_version = "1"

    def __init__(self, role: str, policy) -> None:
        self.agent_config = {"role": role}
        self.policy = policy
        self.calls: list[tuple] = []

    def choose_action(self, observation, legal_actions):
        self.calls.append((observation, legal_actions))
        return self.policy(observation, legal_actions, len(self.calls))


def rule_policy(observation, legal, call):
    return _RULEBOT.choose_action(observation, legal)


def stall_policy(observation, legal, call):
    """Never claims; passes the alphabetically first legal name (stalls into draws)."""
    for action in legal:
        if isinstance(action, (ReactAction, DeclineAction)):
            return action
    return next(a for a in legal if isinstance(a, NamePassAction))


def claim_policy(observation, legal, call):
    """Claims whenever a claim is offered, matching hand or not (a false claim is legal)."""
    for action in legal:
        if isinstance(action, ClaimAction):
            return action
    return stall_policy(observation, legal, call)


class Sneaky(DeclineAction):
    """A subclass that claims to equal everything: `to_engine_action` alone would accept it."""

    def __eq__(self, other):
        return True

    __hash__ = None


def bad_choice(kind: str, observation, legal):
    """A deliberately wrong answer of the named kind for this decision."""
    seat = observation.my_seat
    if kind == "raise":
        raise RuntimeError(f"boom {observation.my_hand}")  # text must never reach anyone
    if kind == "none":
        return None
    if kind == "object":
        return "claim"
    if kind == "engine_pass":
        return PassAction(seat, Chit("Sun", 0))  # an engine action: never agent-selectable
    if kind == "wrong_seat":
        return replace(_RULEBOT.choose_action(observation, legal), seat=(seat + 1) % observation.num_players)
    if kind == "bad_seat_type":
        return ClaimAction(float(seat))
    if kind == "bad_name_type":
        return NamePassAction(seat, 7)
    if kind == "timeout":
        return TimeoutAction(seat)
    if kind == "subclass":
        return Sneaky(seat)
    if kind == "unheld_name":
        return NamePassAction(seat, "No Such Chit")
    if kind == "illegal":
        if observation.phase == "initial_claims":
            return NamePassAction(seat, observation.my_hand[0])  # passing before the claims resolve
        if observation.phase == "passing":
            return DeclineAction(seat)  # there is no decline during passing
        return ClaimAction(seat)  # no claim exists in the reaction phase
    raise ValueError(kind)


FAULT_KINDS = (
    "raise", "none", "object", "engine_pass", "wrong_seat", "bad_seat_type", "bad_name_type",
    "timeout", "subclass", "unheld_name", "illegal",
)  # fmt: skip


class Trigger:
    """Shared by several agents: fires for the first `limit` decisions matching `when`."""

    def __init__(self, when, limit: int = 1) -> None:
        self.when, self.limit, self.fired = when, limit, []

    def __call__(self, observation) -> bool:
        if len(self.fired) < self.limit and self.when(observation):
            self.fired.append((observation.my_seat, observation.completed_rounds, observation.attempt))
            return True
        return False


def misbehaving_policy(kind: str, trigger: Trigger):
    def policy(observation, legal, call):
        if trigger(observation):
            return bad_choice(kind, observation, legal)
        return rule_policy(observation, legal, call)

    return policy


DECISION_POINTS = {
    "initial_claim": lambda o: o.phase == "initial_claims",
    "initiator_first_pass": lambda o: o.decision_kind == "initiator_first_pass",
    "non_initiator_receive": lambda o: o.decision_kind == "non_initiator_receive",
    "initiator_return": lambda o: o.decision_kind == "initiator_return",
    "reaction_nonfinal": lambda o: o.phase == "win_declared" and len(o.pending_reactors) > 1,
    "reaction_final": lambda o: o.phase == "win_declared" and len(o.pending_reactors) == 1,
}


# --- configuration and factories ----------------------------------------------------------------


def sim_config(
    n: int = 4,
    roles=None,
    *,
    rounds: int | None = None,
    draws: int = BIG_DRAWS,
    actions: int = BIG_ACTIONS,
    batch_seed: int = BATCH_SEED,
    game_count: int = 8,
    rotate: bool = False,
    games_per_seed: int = 1,
) -> SimulationConfig:
    """A configuration whose lineup entries are `roles` (`"rulebot"`, a scripted role name, or
    a dict giving the whole entry)."""
    roles = list(roles) if roles is not None else ["rulebot"] * n
    lineup = []
    for role in roles:
        if isinstance(role, dict):
            lineup.append(role)
        elif role == "rulebot":
            lineup.append({"agent_type": "rulebot", "agent_config": {}})
        else:
            lineup.append({"agent_type": "scripted", "agent_config": {"role": role}})
    return SimulationConfig.from_dict(
        {
            "lineup": lineup, "num_players": n, "num_rounds": rounds or n, "batch_seed": batch_seed,
            "game_count": game_count, "games_per_seed": games_per_seed, "rotate_seats": rotate,
            "max_draw_restarts_per_round": draws, "max_actions_per_attempt": actions,
        }
    )  # fmt: skip


def factory_for(policies: dict):
    """An `agent_factory` for lineups made by `sim_config`. `policies` maps a scripted role
    name to a policy. Returns `(factory, created)`; `created` lists every agent built, in order."""
    created: list = []

    def factory(spec):
        if spec.agent_type == "rulebot":
            agent = build_agent(spec)
        else:
            role = spec.agent_config["role"]
            agent = Scripted(role, policies[role])
        created.append(agent)
        return agent

    return factory, created


def crafted_start(matching=frozenset(), completed_round: int = 0):
    """A `start` function for `_run_game`: round 0 from `crafted_deal` (seats in `matching`
    hold four of one name; everyone else a mixed hand). Later rounds use the real seeded deals."""

    def start(game_config):
        return start_from_deal(game_config, crafted_deal(game_config, matching, completed_round))

    return start


def play(config, game_index=0, policies=None, start=new_game):
    """Run one game through the runner core. Returns `(result, steps, created_agents)`, where
    `steps` is every `apply_action` call the runner made."""
    factory, created = factory_for(policies or {})
    steps: list[Step] = []
    real = runner_module.apply_action

    def spy(state, action):
        result = real(state, action)
        steps.append(Step(state, action, result))
        return result

    with mock.patch.object(runner_module, "apply_action", spy):
        result = runner_module._run_game(config, game_index, factory, start)
    return result, steps, created


def replay(opening_state, steps):
    """Feed the logged engine actions to the plain engine; every outcome must equal the logged
    one. Returns the final state."""
    state = opening_state
    for step in steps:
        assert step.state == state
        outcome = apply_action(state, step.action)
        assert outcome == step.result
        assert isinstance(outcome, Accepted)
        state = outcome.state
    return state


def opening_state(config: SimulationConfig, game_index: int = 0, start=new_game):
    """The state the runner starts from, built independently of the runner."""
    from chitai.simulation import game_seed

    seed = game_seed(config.batch_seed, game_index, config.games_per_seed)
    return start(config.game_config(seed)).state


def accepted_events(steps):
    return [event for step in steps if isinstance(step.result, Accepted) for event in step.result.events]


def never_rejected(steps) -> bool:
    return not any(isinstance(step.result, Rejected) for step in steps)
