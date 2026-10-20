"""MindBot through the real simulation runner and agent registry (M9 Stage 2)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from batch.support import make_config

from chitai.agents import MindBot, RuleBot
from chitai.observations import NamePassAction, Observation
from chitai.simulation import (
    AGENT_TYPES,
    STATUS_COMPLETED,
    TERMINATION_STATUSES,
    AgentSpec,
    SimulationConfigError,
    build_agent,
    run_game,
)

FEWEST = {"non_target_order": "fewest_copies"}


def lineup(n, focal_type="mindbot", focal_config=None, others=None):
    """Lineup entry 0 is the focal agent; the other n-1 are identical RuleBots."""
    focal = {"agent_type": focal_type, "agent_config": {**FEWEST, **(focal_config or {})}}
    rest = {"agent_type": "rulebot", "agent_config": others if others is not None else FEWEST}
    return [focal] + [rest] * (n - 1)


def config(n=4, focal_type="mindbot", focal_config=None, **overrides):
    settings = {"num_players": n, "num_rounds": n, "game_count": n, "games_per_seed": 1, "batch_seed": 17}
    settings.update(overrides)
    return make_config(lineup=lineup(n, focal_type, focal_config), **settings)


# --- construction through the registry -----------------------------------------------------------


def test_the_registry_holds_both_agent_types_and_rulebot_is_unchanged():
    assert sorted(AGENT_TYPES) == ["mindbot", "rulebot"]
    assert AGENT_TYPES["rulebot"] is RuleBot and AGENT_TYPES["mindbot"] is MindBot


def test_build_agent_makes_a_fresh_mindbot_with_its_effective_configuration():
    first, second = build_agent(AgentSpec("mindbot")), build_agent(AgentSpec("mindbot"))
    assert isinstance(first, MindBot) and first is not second and first.estimator is not second.estimator
    assert first.agent_config == {
        "avoid_draw": True, "non_target_order": "most_copies", "use_inference": True, "epsilon": 0.2,
    }  # fmt: skip
    chosen = build_agent(AgentSpec("mindbot", {**FEWEST, "use_inference": False, "epsilon": 0.5, "avoid_draw": False}))
    assert chosen.agent_config == {
        "avoid_draw": False, "non_target_order": "fewest_copies", "use_inference": False, "epsilon": 0.5,
    }  # fmt: skip


@pytest.mark.parametrize(
    "bad",
    [{"use_inference": "yes"}, {"epsilon": 0}, {"epsilon": 1.5}, {"epsilon": "x"}, {"non_target_order": "random"}, {"surprise": 1}],
)
def test_an_invalid_mindbot_configuration_is_a_configuration_error_before_any_play(bad):
    with pytest.raises(SimulationConfigError, match="invalid agent_config for agent_type 'mindbot'"):
        build_agent(AgentSpec("mindbot", bad))


def test_the_effective_configuration_is_recorded_per_seat_with_defaults_filled_in():
    result = run_game(config(focal_config={"use_inference": False}), 0)
    focal = next(s for s in result.seats if s.lineup_index == 0)
    assert focal.agent_type == "mindbot" and focal.agent_version == "1"
    assert json.loads(focal.agent_config_json) == {
        "avoid_draw": True, "non_target_order": "fewest_copies", "use_inference": False, "epsilon": 0.2,
    }  # fmt: skip


# --- legality and successful play ---------------------------------------------------------------


@pytest.mark.parametrize("n", [4, 5, 7])
@pytest.mark.parametrize("use_inference", [True, False])
def test_games_with_mindbot_complete_with_only_legal_actions_and_no_faults(n, use_inference):
    cfg = config(n, focal_config={"use_inference": use_inference}, game_count=n)
    statuses = []
    for game_index in range(cfg.game_count):
        result = run_game(cfg, game_index)  # an engine rejection of a runner-built action would raise
        statuses.append(result.status)
        assert result.status in TERMINATION_STATUSES
        assert [s.agent_faults for s in result.seats] == [0] * n  # every answer was legal
        assert [s.timeouts for s in result.seats] == [0] * n  # so the host never had to step in
    assert STATUS_COMPLETED in statuses


def test_under_rotation_the_focal_mindbot_plays_every_seat():
    cfg = config(4, game_count=4)
    seats = []
    for game_index in range(4):
        result = run_game(cfg, game_index)
        focal = [s for s in result.seats if s.agent_type == "mindbot"]
        assert len(focal) == 1 and focal[0].lineup_index == 0
        seats.append(focal[0].seat)
    assert sorted(seats) == [0, 1, 2, 3]


def test_a_mixed_lineup_of_mindbot_and_existing_rulebot_configurations_runs():
    mixed = [
        {"agent_type": "mindbot", "agent_config": FEWEST},
        {"agent_type": "rulebot", "agent_config": {"avoid_draw": False, "non_target_order": "most_copies"}},
        {"agent_type": "rulebot"},
        {"agent_type": "rulebot", "agent_config": FEWEST},
    ]
    cfg = make_config(lineup=mixed, game_count=4)
    for game_index in range(4):
        result = run_game(cfg, game_index)
        assert all(s.agent_faults == 0 for s in result.seats)
        by_lineup = {s.lineup_index: s for s in result.seats}
        assert by_lineup[1].agent_config_json == '{"avoid_draw":false,"non_target_order":"most_copies"}'
        assert by_lineup[2].agent_config_json == '{"avoid_draw":true,"non_target_order":"most_copies"}'  # M8 format
        assert by_lineup[3].agent_config_json == '{"avoid_draw":true,"non_target_order":"fewest_copies"}'


def test_rulebot_only_games_are_unchanged_by_the_registration():
    """An all-RuleBot configuration never touches MindBot; its seat records keep the M8 format."""
    result = run_game(make_config(), 0)
    assert {s.agent_type for s in result.seats} == {"rulebot"}
    assert all(s.agent_config_json == '{"avoid_draw":true,"non_target_order":"most_copies"}' for s in result.seats)


# --- determinism -------------------------------------------------------------------------------------


@pytest.mark.parametrize("use_inference", [True, False])
def test_the_same_configuration_and_game_index_give_an_equal_result(use_inference):
    cfg = config(5, focal_config={"use_inference": use_inference}, game_count=5)
    first = [run_game(cfg, g) for g in range(5)]
    second = [run_game(cfg, g) for g in range(5)]
    assert first == second
    assert run_game(cfg, 3) == first[3]  # no state carries over from earlier games


def test_a_different_batch_seed_changes_the_games():
    a = [run_game(config(batch_seed=1), g).game_seed for g in range(4)]
    b = [run_game(config(batch_seed=2), g).game_seed for g in range(4)]
    assert a != b


# --- control versus treatment ---------------------------------------------------------------------------


def _without_agent_identity(result):
    """A result with the three agent-identity fields of every seat blanked out."""
    return replace(
        result, seats=tuple(replace(s, agent_type="", agent_version="", agent_config_json="") for s in result.seats)
    )


@pytest.mark.parametrize("n", [4, 6])
def test_mindbot_with_inference_disabled_plays_games_identical_to_the_rulebot_control(n):
    control = config(n, focal_type="rulebot", game_count=2 * n)
    off = config(n, focal_config={"use_inference": False}, game_count=2 * n)
    for game_index in range(2 * n):
        a, b = run_game(control, game_index), run_game(off, game_index)
        assert b.seats != a.seats  # the agent identity differs ...
        assert _without_agent_identity(b) == _without_agent_identity(a)  # ... nothing else does


def test_control_and_treatment_share_deal_seeds_and_seatings_and_differ_only_in_the_focal_entry():
    n = 5
    control_cfg = config(n, focal_type="rulebot", game_count=10, games_per_seed=n)
    treat_cfg = config(n, game_count=10, games_per_seed=n)
    assert [e for i, e in enumerate(control_cfg.lineup) if i > 0] == [e for i, e in enumerate(treat_cfg.lineup) if i > 0]
    for game_index in range(10):
        a, b = run_game(control_cfg, game_index), run_game(treat_cfg, game_index)
        assert a.game_seed == b.game_seed
        focal_a = next(s for s in a.seats if s.lineup_index == 0)
        focal_b = next(s for s in b.seats if s.lineup_index == 0)
        assert (focal_a.seat, focal_a.agent_type) == (focal_b.seat, "rulebot")
        assert focal_b.agent_type == "mindbot"
        assert [s.agent_config_json for s in a.seats if s.lineup_index > 0] == [
            s.agent_config_json for s in b.seats if s.lineup_index > 0
        ]
    # with games_per_seed = N each deal seed is played from every seat, for both conditions
    first_group = {run_game(treat_cfg, g).game_seed for g in range(n)}
    assert len(first_group) == 1


# --- the privacy boundary is unchanged ----------------------------------------------------------------------


class _Spy(MindBot):
    seen: list = []

    def choose_action(self, observation, legal_actions):
        type(self).seen.append((observation, legal_actions))
        return super().choose_action(observation, legal_actions)


def test_mindbot_only_ever_receives_an_observation_and_agent_actions_through_the_runner():
    _Spy.seen = []
    cfg = config(5, game_count=2)
    for game_index in range(2):
        run_game(cfg, game_index, agent_factory=lambda spec: _Spy(**spec.to_dict()["agent_config"]))
    assert len(_Spy.seen) > 100
    for observation, legal in _Spy.seen:
        assert type(observation) is Observation
        assert all(type(action).__name__ in {"ClaimAction", "DeclineAction", "ReactAction", "NamePassAction"} for action in legal)
        assert all(a.seat == observation.my_seat for a in legal)
        assert not any(hasattr(a, "chit") for a in legal)
        assert any(isinstance(a, NamePassAction) for a in legal) or observation.phase != "passing"
