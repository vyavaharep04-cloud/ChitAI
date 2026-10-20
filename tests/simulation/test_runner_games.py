"""Completed games, scoring, valid wins, false claims, ties, determinism, seat rotation and
configuration errors for the single-game runner (M8 Stage 3)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest
from observations.support import PLAYER_COUNTS

import chitai.simulation.runner as runner_module
from chitai.agents import RuleBot
from chitai.engine import (
    ROUND_OUTCOME_FALSE_CLAIM,
    ROUND_OUTCOME_VALID_WIN,
    Accepted,
    ClaimAction,
    GameCompleted,
    Phase,
    Rejected,
    RejectionReason,
    RoundCompleted,
    ValidWinScored,
    apply_action,
    new_game,
)
from chitai.simulation import (
    STATUS_COMPLETED,
    AgentSpec,
    GameResult,
    RunnerError,
    SimulationConfigError,
    build_agent,
    competition_ranks,
    game_seed,
    reaction_order,
    reaction_order_for_state,
    run_game,
    seat_assignment,
)

from .runner_support import (
    BATCH_SEED,
    COMPLETING_GAME,
    accepted_events,
    claim_policy,
    crafted_start,
    never_rejected,
    opening_state,
    play,
    replay,
    rule_policy,
    sim_config,
)

# --- completed RuleBot games ---------------------------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_rulebot_game_completes_and_matches_an_independent_replay(n):
    config = sim_config(n)
    result, steps, _ = play(config, COMPLETING_GAME)

    assert result.status == STATUS_COMPLETED and result.completed
    assert result.completed_rounds == result.num_rounds == n
    assert result.actions == len(steps) and never_rejected(steps)
    # A pure RuleBot game has no faults, no timeouts and no false claims.
    assert all(s.timeouts == 0 and s.agent_faults == 0 and s.false_claims == 0 for s in result.seats)

    final = replay(opening_state(config, COMPLETING_GAME), steps)
    assert final.phase is Phase.GAME_OVER
    assert tuple(s.score for s in result.seats) == final.scores
    events = accepted_events(steps)
    assert [e.final_scores for e in events if isinstance(e, GameCompleted)] == [final.scores]
    completed = [e for e in events if isinstance(e, RoundCompleted)]
    assert len(completed) == len(result.rounds) == n
    for record, event in zip(result.rounds, completed):
        assert (record.round_index, record.outcome, record.claimant) == (
            event.completed_round, event.outcome, event.claimant,
        )  # fmt: skip
        assert record.attempts == event.attempt


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_scores_ranks_and_round_changes_reconcile(n):
    result = run_game(sim_config(n), COMPLETING_GAME)
    scores = tuple(s.score for s in result.seats)
    for seat in result.seats:
        assert seat.score == sum(r.score_changes[seat.seat] for r in result.rounds)
    assert tuple(s.rank for s in result.seats) == competition_ranks(scores)
    assert result.winning_seats == tuple(s.seat for s in result.seats if s.rank == 1)
    assert isinstance(result, GameResult)


def test_a_tie_for_first_is_recorded_not_broken():
    # Pinned: with batch seed 2026, rotation off, game 17 of an all-RuleBot 4-player lineup ends in
    # a tie for first (found by scanning games 0..99 with generous caps).
    result = run_game(sim_config(4, game_count=40), 17)
    assert result.completed and result.tie_for_first is True
    assert len(result.winning_seats) > 1
    assert all(result.seats[s].tied and result.seats[s].rank == 1 for s in result.winning_seats)
    assert tuple(s.rank for s in result.seats) == competition_ranks([s.score for s in result.seats])


# --- valid wins, reactions, false claims ----------------------------------------------------------


def test_a_valid_win_is_scored_by_the_engine_with_the_seeded_reaction_order():
    config = sim_config(4, ["claim"] * 4)
    start = crafted_start({0})
    result, steps, _ = play(config, 0, {"claim": claim_policy}, start)

    first = result.rounds[0]
    assert (first.outcome, first.claimant, first.initiator, first.attempts) == (ROUND_OUTCOME_VALID_WIN, 0, 0, 1)
    # The engine's own event, the record and the pinned seeded permutation all agree.
    scored = [e for e in accepted_events(steps) if isinstance(e, ValidWinScored)][0]
    assert first.reaction_order == scored.reaction_order
    seed = game_seed(BATCH_SEED, 0)
    after_claim = steps[0].result.state  # the first action is seat 0's valid claim
    assert after_claim.phase is Phase.WIN_DECLARED
    assert first.reaction_order == reaction_order(seed, 0, 1, (1, 2, 3)) == reaction_order_for_state(after_claim)
    # Pinned by running (seeded permutation for game seed of batch 2026, game 0): reactions 3, 2, 1.
    assert first.reaction_order == (3, 2, 1) and first.score_changes == (4, 1, 2, 3)
    assert [s.score for s in result.seats] == [4, -2, -1, 0]  # then three false claims of -3
    # reactions are scored in the order the engine accepted them: N-1, N-2, ... 1
    assert [first.score_changes[s] for s in first.reaction_order] == [3, 2, 1]
    assert result.seats[0].rounds_won == 1


def test_the_reaction_order_is_computed_once_per_win(monkeypatch):
    calls = []
    real = runner_module.reaction_order_for_state
    monkeypatch.setattr(runner_module, "reaction_order_for_state", lambda s: calls.append(1) or real(s))
    result, _, _ = play(sim_config(4, ["claim"] * 4), 0, {"claim": claim_policy}, crafted_start({0}))
    wins = [r for r in result.rounds if r.outcome == ROUND_OUTCOME_VALID_WIN]
    assert len(calls) == len(wins) >= 1


def test_a_false_claim_is_a_legal_choice_with_the_engine_penalty_and_no_fault():
    config = sim_config(4, ["claim"] * 4)
    result, steps, _ = play(config, 0, {"claim": claim_policy}, crafted_start(set()))
    assert result.completed and never_rejected(steps)
    false_rounds = [r for r in result.rounds if r.outcome == ROUND_OUTCOME_FALSE_CLAIM]
    assert false_rounds, "an always-claim lineup with no matching hand must false-claim"
    for record in false_rounds:
        assert record.reaction_order == ()
        assert record.score_changes[record.claimant] == -3
        assert sum(abs(c) for i, c in enumerate(record.score_changes) if i != record.claimant) == 0
    assert all(s.agent_faults == 0 and s.timeouts == 0 for s in result.seats)
    assert sum(s.false_claims for s in result.seats) == len(false_rounds)
    assert replay(opening_state(config, 0, crafted_start(set())), steps).scores == tuple(s.score for s in result.seats)


def test_when_every_seat_false_claims_once_all_seats_tie_for_first_and_no_tie_is_broken():
    # Pinned by running: crafted round 0 plus seeded rounds 1..3 all end on the initiator's false
    # claim, so every seat scores -3 and shares rank 1 (raw scores kept, no tie broken).
    result, _, _ = play(sim_config(4, ["claim"] * 4), 0, {"claim": claim_policy}, crafted_start(set()))
    assert [s.score for s in result.seats] == [-3, -3, -3, -3]
    assert [s.rank for s in result.seats] == [1, 1, 1, 1] and all(s.tied for s in result.seats)
    assert result.winning_seats == (0, 1, 2, 3) and result.tie_for_first is True


# --- determinism ------------------------------------------------------------------------------------


def test_the_same_inputs_give_an_equal_result():
    config = sim_config(5)
    assert run_game(config, 0) == run_game(config, 0)


def test_a_different_batch_seed_gives_a_different_game():
    first, second = run_game(sim_config(4, batch_seed=1), 0), run_game(sim_config(4, batch_seed=2), 0)
    assert first.game_seed != second.game_seed and first != second


def test_the_result_is_stable_across_processes_with_different_hash_seeds():
    code = (
        "import sys; sys.path.insert(0, 'tests');"
        "from simulation.runner_support import sim_config;"
        "from chitai.simulation import run_game;"
        "print(repr(run_game(sim_config(4), 0)))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True,
            env={
    **os.environ,
    "PYTHONHASHSEED": str(s),
    "PYTHONPATH": "src",
},
        ).stdout.strip()  # fmt: skip
        for s in (1, 2, 3)
    }
    assert len(outputs) == 1 and next(iter(outputs)) == repr(run_game(sim_config(4), 0))


def test_games_that_share_a_seed_see_identical_deals_whatever_the_lineup():
    rulebots = sim_config(4, games_per_seed=2)
    claimers = sim_config(4, ["claim"] * 4, games_per_seed=2)
    assert game_seed(BATCH_SEED, 0, 2) == game_seed(BATCH_SEED, 1, 2)
    assert opening_state(rulebots, 0) == opening_state(rulebots, 1) == opening_state(claimers, 0)
    a, steps_a, _ = play(rulebots, 0)
    b, steps_b, _ = play(claimers, 1, {"claim": claim_policy})
    assert a.game_seed == b.game_seed and steps_a[0].state == steps_b[0].state


def test_agents_are_built_fresh_for_every_game():
    config = sim_config(4, ["claim"] * 4, game_count=4)
    seen = []

    def factory(spec):
        agent = _Counting()
        seen.append(agent)
        return agent

    first = runner_module._run_game(config, 0, factory, new_game)
    second = runner_module._run_game(config, 0, factory, new_game)
    assert first == second
    assert len(seen) == 8 and len({id(a) for a in seen}) == 8
    # a stateful agent cannot carry anything from one game into the next
    assert all(agent.calls_seen[0] == 1 for agent in seen if agent.calls_seen)


class _Counting:
    agent_type = "counting"
    agent_version = "1"

    def __init__(self):
        self.agent_config = {}
        self.calls_seen = []

    def choose_action(self, observation, legal_actions):
        self.calls_seen.append(len(self.calls_seen) + 1)
        return claim_policy(observation, legal_actions, 0)


# --- seat rotation ---------------------------------------------------------------------------------


def test_seat_records_follow_the_rotation_and_each_entry_visits_each_seat():
    n = 4
    roles = ["a", "b", "c", "d"]
    config = sim_config(n, roles, rotate=True, game_count=8)
    policies = {role: claim_policy for role in roles}
    visited = {role: set() for role in roles}
    for game in range(n):
        result, _, _ = play(config, game, policies, crafted_start(set()))
        assignment = seat_assignment(n, game, True)
        for seat in result.seats:
            assert seat.lineup_index == assignment[seat.seat]
            assert json.loads(seat.agent_config_json) == {"role": roles[seat.lineup_index]}
            visited[roles[seat.lineup_index]].add(seat.seat)
    assert all(seats == set(range(n)) for seats in visited.values())


def test_without_rotation_the_lineup_stays_put():
    roles = ["a", "b", "c", "d"]
    config = sim_config(4, roles, rotate=False, game_count=4)
    for game in (0, 3):
        result, _, _ = play(config, game, {r: claim_policy for r in roles}, crafted_start(set()))
        assert [s.lineup_index for s in result.seats] == [0, 1, 2, 3]


# --- agent construction and configuration errors --------------------------------------------------------


def test_the_effective_configuration_including_defaults_is_recorded():
    config = sim_config(4, [{"agent_type": "rulebot", "agent_config": {"non_target_order": "fewest_copies"}}] * 4)
    result = run_game(config, COMPLETING_GAME)
    for seat in result.seats:
        assert seat.agent_config_json == '{"avoid_draw":true,"non_target_order":"fewest_copies"}'
        assert (seat.agent_type, seat.agent_version) == ("rulebot", "1")


def test_the_recorded_configuration_is_captured_at_setup():
    class Mutating:
        agent_type, agent_version = "mutating", "1"

        def __init__(self):
            self.agent_config = {"role": "m"}

        def choose_action(self, observation, legal_actions):
            self.agent_config["role"] = "changed mid-game"
            return claim_policy(observation, legal_actions, 0)

    result = runner_module._run_game(sim_config(4, ["m"] * 4), 0, lambda spec: Mutating(), new_game)
    assert all(s.agent_config_json == '{"role":"m"}' for s in result.seats)


def test_build_agent_makes_a_fresh_rulebot_with_its_configuration():
    spec = AgentSpec("rulebot", {"avoid_draw": False})
    first, second = build_agent(spec), build_agent(spec)
    assert isinstance(first, RuleBot) and first is not second
    assert first.agent_config == {"avoid_draw": False, "non_target_order": "most_copies"}


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        (AgentSpec("smartbot"), "unknown agent_type 'smartbot' (known: mindbot, rulebot)"),
        (AgentSpec("rulebot", {"non_target_order": "random"}), "invalid agent_config for agent_type 'rulebot'"),
        (AgentSpec("rulebot", {"avoid_draw": "yes"}), "invalid agent_config for agent_type 'rulebot'"),
        (AgentSpec("rulebot", {"surprise": 1}), "invalid agent_config for agent_type 'rulebot'"),
    ],
)
def test_bad_lineups_fail_before_any_gameplay(spec, fragment, monkeypatch):
    monkeypatch.setattr(runner_module, "apply_action", lambda *a: pytest.fail("the engine was reached"))
    config = sim_config(4, [{"agent_type": spec.agent_type, "agent_config": spec.to_dict()["agent_config"]}] * 4)
    with pytest.raises(SimulationConfigError) as caught:
        run_game(config, 0)
    assert fragment in str(caught.value)


def test_a_failing_or_malformed_factory_is_a_configuration_error():
    config = sim_config(4)

    def broken(spec):
        raise RuntimeError("nope")

    class NoConfig:
        agent_type, agent_version = "x", "1"
        agent_config = {"bad": {1, 2}}  # not JSON

        def choose_action(self, observation, legal_actions):
            return None

    class NoMethod:
        agent_type, agent_version, agent_config = "x", "1", {}

    class NumericType(NoConfig):
        agent_type = 5
        agent_config = {}

    for factory in (broken, lambda spec: object(), lambda spec: NoConfig(), lambda spec: NoMethod(), lambda spec: NumericType()):
        with pytest.raises(SimulationConfigError):
            runner_module._run_game(config, 0, factory, new_game)


@pytest.mark.parametrize("bad", [-1, 8, True, 1.0, "0", None])
def test_game_index_must_be_a_real_index_of_the_batch(bad):
    with pytest.raises(SimulationConfigError):
        run_game(sim_config(4, game_count=8), bad)


def test_the_configuration_must_be_a_simulation_config():
    with pytest.raises(SimulationConfigError):
        run_game({"lineup": []}, 0)


def test_an_engine_rejection_of_a_validated_action_is_a_runner_error_not_a_fault(monkeypatch):
    secret = "chit data in a rejection message"
    monkeypatch.setattr(
        runner_module, "apply_action",
        lambda state, action: Rejected(RejectionReason.CHIT_NOT_HELD, secret),
    )  # fmt: skip
    with pytest.raises(RunnerError) as caught:
        run_game(sim_config(4), 0)
    assert "chit_not_held" in str(caught.value) and secret not in str(caught.value)
