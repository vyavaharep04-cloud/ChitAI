"""MindBot: equivalence with inference off, tie-break-only inference, legality, boundaries,
determinism and privacy (M9 Stage 1)."""

from __future__ import annotations

import ast
import functools
import itertools
import json
import random
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from simulation.support import config_dict

import chitai.agents as agents_pkg
from chitai.agents import Agent, MindBot, RuleBot
from chitai.engine import ClaimAction, DeclineAction, ReactAction, chit_names_for
from chitai.observations import NamePassAction
from chitai.simulation import SimulationConfig
from chitai.simulation.runner import run_game

from .support import PLAYER_COUNTS, phase_states, view

NAMES = tuple(chit_names_for(4))
A, B, C, D = NAMES

VARIANTS = [
    {"avoid_draw": avoid, "non_target_order": order}
    for avoid, order in itertools.product((True, False), ("most_copies", "fewest_copies"))
]


# --- synthetic observations (agent-visible fields only) --------------------------------------


@functools.lru_cache(maxsize=None)
def _base(num_players=4, seat=1):
    state_obs, _ = view(phase_states(num_players)["initial"], 0)
    return replace(state_obs, my_seat=seat, chit_names=tuple(chit_names_for(num_players)))


def obs_initial(hand, key=(0, 1), seat=1, base=None):
    base = base or _base(seat=seat)
    observation = replace(
        base,
        my_seat=seat,
        phase="initial_claims",
        decision_kind="initial_claim",
        completed_rounds=key[0],
        attempt=key[1],
        my_hand=tuple(sorted(hand)),
        my_pass_streak_name=None,
        my_pass_streak_count=0,
    )
    return observation, (ClaimAction(seat), DeclineAction(seat))


def obs_passing(hand, kind, key=(0, 1), seat=1, base=None, streak=(None, 0)):
    base = base or _base(seat=seat)
    observation = replace(
        base,
        my_seat=seat,
        phase="passing",
        decision_kind=kind,
        completed_rounds=key[0],
        attempt=key[1],
        my_hand=tuple(sorted(hand)),
        my_pass_streak_name=streak[0],
        my_pass_streak_count=streak[1],
    )
    claim = (ClaimAction(seat),) if kind != "initiator_first_pass" else ()
    return observation, claim + tuple(NamePassAction(seat, name) for name in sorted(set(hand)))


def obs_reaction(hand, key=(0, 1), seat=1, base=None):
    base = base or _base(seat=seat)
    observation = replace(
        base, my_seat=seat, phase="win_declared", decision_kind=None,
        completed_rounds=key[0], attempt=key[1], my_hand=tuple(sorted(hand)),
    )  # fmt: skip
    return observation, (ReactAction(seat),)


def run_script(bot, script):
    """Feed (observation, legal) pairs in order; return the chosen actions."""
    return [bot.choose_action(observation, legal) for observation, legal in script]


def tie_script():
    """Seat 1: dealt A A B C, declines, then receives B (hand A A B B C: a tie between A and B)."""
    return [
        obs_initial((A, A, B, C)),
        obs_passing((A, A, B, B, C), "non_initiator_receive"),
    ]


# --- interface -------------------------------------------------------------------------------


def test_mindbot_satisfies_the_agent_interface_and_describes_itself_in_json():
    bot = MindBot()
    assert isinstance(bot, Agent)
    assert (bot.agent_type, bot.agent_version) == ("mindbot", "1")
    assert json.loads(json.dumps(bot.agent_config)) == {
        "avoid_draw": True,
        "non_target_order": "most_copies",
        "use_inference": True,
        "epsilon": 0.2,
    }
    assert MindBot(use_inference=False, epsilon=0.5).agent_config["use_inference"] is False


def test_agent_config_holds_no_game_data_and_no_counters():
    bot = MindBot()
    run_script(bot, tie_script())
    assert set(bot.agent_config) == {"avoid_draw", "non_target_order", "use_inference", "epsilon"}
    assert bot.diagnostics()["decisions"] == 2  # counters live elsewhere


def test_invalid_configuration_is_rejected():
    with pytest.raises(TypeError):
        MindBot(use_inference="yes")
    with pytest.raises(TypeError):
        MindBot(avoid_draw="yes")
    with pytest.raises(ValueError):
        MindBot(non_target_order="random")
    with pytest.raises(ValueError):
        MindBot(epsilon=0)
    with pytest.raises(ValueError):
        MindBot(epsilon=1.5)


def test_it_fails_loudly_exactly_where_rulebot_does():
    observation, _ = obs_passing((A, A, B, C, D), "non_initiator_receive")
    with pytest.raises(ValueError):
        MindBot().choose_action(observation, ())
    with pytest.raises(ValueError):
        MindBot().choose_action(observation, (ClaimAction(1),))  # a lone unusable claim


# --- equivalence with RuleBot when inference is disabled ---------------------------------------


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_disabled_mindbot_equals_rulebot_in_every_engine_phase(n, variant):
    for name, state in phase_states(n).items():
        for seat in range(n):
            observation, legal = view(state, seat)
            if not legal:
                continue
            assert MindBot(use_inference=False, **variant).choose_action(observation, legal) == RuleBot(
                **variant
            ).choose_action(observation, legal), (name, seat)


def _random_hand(rng, size):
    pool = [name for name in NAMES for _ in range(4)]
    return tuple(rng.sample(pool, size))


@pytest.mark.parametrize("variant", VARIANTS)
def test_disabled_mindbot_equals_rulebot_on_thousands_of_random_hands_and_streaks(variant):
    rng = random.Random(7)
    disabled, rule = MindBot(use_inference=False, **variant), RuleBot(**variant)
    for index in range(1500):
        size = rng.choice((4, 5))
        hand = _random_hand(rng, size)
        kind = "non_initiator_receive" if size == 5 else rng.choice(("initiator_return", "initiator_first_pass"))
        streak = (rng.choice(NAMES), rng.randint(1, 9)) if rng.random() < 0.4 else (None, 0)
        observation, legal = obs_passing(hand, kind, key=(index // 7, 1 + index % 3), streak=streak)
        assert disabled.choose_action(observation, legal) == rule.choose_action(observation, legal)
    stats = disabled.diagnostics()
    assert stats["inference_eligible"] == stats["inference_changed_action"] == 0
    assert stats["matched_rulebot"] == stats["decisions"] == 1500
    assert stats["estimator_deals"] == 0  # a disabled agent keeps no estimator state at all


def _lineup(agent_type, config, n):
    return [{"agent_type": agent_type, "agent_config": config}] * n


def _game_config(n, **extra):
    return SimulationConfig.from_dict(
        config_dict(
            lineup=_lineup("rulebot", {}, n), num_players=n, num_rounds=n, game_count=3, batch_seed=5,
            max_draw_restarts_per_round=50, max_actions_per_attempt=300, **extra,
        )  # fmt: skip
    )


def _outcome(result):
    return (
        result.status,
        result.completed_rounds,
        result.draw_restarts,
        result.actions,
        result.rounds,
        tuple((s.score, s.rank, s.rounds_won, s.false_claims, s.timeouts, s.agent_faults) for s in result.seats),
    )


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("n", [4, 6])
def test_whole_games_with_disabled_mindbot_are_identical_to_rulebot_games(n, variant):
    config = _game_config(n)
    for game_index in range(3):
        rule = run_game(config, game_index, agent_factory=lambda spec: RuleBot(**variant))
        mind = run_game(config, game_index, agent_factory=lambda spec: MindBot(use_inference=False, **variant))
        assert _outcome(mind) == _outcome(rule), game_index


# --- inference changes only the target tie-break ---------------------------------------------


def test_belief_breaks_a_target_tie_against_the_name_the_predecessor_seems_to_collect():
    """Hand A A B B C is a tie between A and B. B was just received, so B is the *less* likely
    predecessor target; MindBot collects B and passes A. RuleBot takes A (canonical) and passes B."""
    rule_choice = run_script(RuleBot(), tie_script())[-1]
    mind = MindBot()
    mind_choice = run_script(mind, tie_script())[-1]
    assert rule_choice == NamePassAction(1, B)
    assert mind_choice == NamePassAction(1, A)
    stats = mind.diagnostics()
    assert (stats["inference_eligible"], stats["inference_changed_action"]) == (1, 1)
    assert stats["matched_rulebot"] == 1  # the initial decline matched


def test_with_inference_disabled_the_same_sequence_gives_rulebots_choice():
    bot = MindBot(use_inference=False)
    assert run_script(bot, tie_script())[-1] == NamePassAction(1, B)
    assert not bot.estimator.active


def test_no_tie_means_no_inference_and_rulebots_choice():
    """A A A B C has a unique most-held name; the belief cannot matter."""
    bot = MindBot()
    script = [obs_initial((A, A, A, B)), obs_passing((A, A, A, B, C), "non_initiator_receive")]
    assert run_script(bot, script) == run_script(RuleBot(), script)
    assert bot.diagnostics()["inference_eligible"] == 0


def test_when_the_belief_has_no_opinion_the_canonical_tie_break_is_kept():
    """Epsilon 1 ignores evidence, so equal prior weights tie and RuleBot's order decides."""
    bot = MindBot(epsilon=1.0)
    assert run_script(bot, tie_script())[-1] == RuleBot().choose_action(*tie_script()[-1])
    assert bot.diagnostics()["inference_changed_action"] == 0
    assert bot.diagnostics()["inference_eligible"] == 1


def test_claims_declines_and_reactions_are_never_changed():
    bot = MindBot()
    # a claimable five-chit hand claims; an unclaimable initial hand declines; reactions react
    assert bot.choose_action(*obs_initial((A, A, A, A))) == ClaimAction(1)
    assert bot.choose_action(*obs_initial((A, A, B, B), key=(0, 2))) == DeclineAction(1)
    assert bot.choose_action(*obs_passing((A, A, A, A, B), "non_initiator_receive", key=(0, 2))) == ClaimAction(1)
    assert bot.choose_action(*obs_reaction((A, A, A, A), key=(0, 2))) == ReactAction(1)


def _forced(variant, target):
    class Forced(RuleBot):
        def _choose_target(self, observation, counts, held):
            return target

    return Forced(**variant)


class Checked(MindBot):
    """MindBot that proves, on every decision, that inference acted as a tie-break only."""

    checked = 0
    changed = 0

    def choose_action(self, observation, legal_actions):
        choice = super().choose_action(observation, legal_actions)
        variant = {"avoid_draw": self.avoid_draw, "non_target_order": self.non_target_order}
        baseline = RuleBot(**variant).choose_action(observation, legal_actions)
        assert choice in legal_actions
        type(self).checked += 1
        if choice != baseline:
            type(self).changed += 1
            assert isinstance(choice, NamePassAction) and isinstance(baseline, NamePassAction)
            counts = Counter(observation.my_hand)
            top = max(counts.values())
            tied = [name for name in counts if counts[name] == top]
            assert len(tied) >= 2, "an action changed without a target tie"
            # the choice is exactly RuleBot's logic run with some tied name as the target
            assert any(_forced(variant, name).choose_action(observation, legal_actions) == choice for name in tied)
        if (
            isinstance(choice, NamePassAction)
            and self.avoid_draw
            and observation.my_pass_streak_count >= 9
            and len(legal_actions) > 1
            and sum(isinstance(a, NamePassAction) for a in legal_actions) > 1
        ):
            assert choice.chit_name != observation.my_pass_streak_name  # draw avoidance preserved
        return choice


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("n", [4, 5, 7])
def test_across_real_games_inference_only_ever_breaks_target_ties_and_stays_legal(n, variant):
    Checked.checked = Checked.changed = 0
    config = _game_config(n)
    for game_index in range(3):
        result = run_game(config, game_index, agent_factory=lambda spec: Checked(**variant))
        assert all(seat.agent_faults == 0 for seat in result.seats)  # every answer was legal
    assert Checked.checked > 100


def test_the_tie_break_property_is_not_vacuous_inference_does_change_some_real_decisions():
    Checked.checked = Checked.changed = 0
    config = _game_config(5)
    for game_index in range(3):
        run_game(config, game_index, agent_factory=lambda spec: Checked())
    assert Checked.changed > 0


def test_random_valid_but_inconsistent_observation_streams_never_raise_and_stay_legal():
    rng = random.Random(99)
    for variant in VARIANTS:
        bot = MindBot(**variant)
        for step in range(1500):
            kind = rng.choice(("initial", "first", "receive", "return", "react"))
            key = (rng.randint(0, 2), rng.randint(1, 3))
            if kind == "initial":
                observation, legal = obs_initial(_random_hand(rng, 4), key)
            elif kind == "react":
                observation, legal = obs_reaction(_random_hand(rng, 4), key)
            else:
                size = 5 if kind == "receive" else 4
                streak = (rng.choice(NAMES), rng.randint(1, 9)) if rng.random() < 0.3 else (None, 0)
                name = {"first": "initiator_first_pass", "receive": "non_initiator_receive", "return": "initiator_return"}[kind]
                observation, legal = obs_passing(_random_hand(rng, size), name, key, streak=streak)
            choice = bot.choose_action(observation, legal)
            assert choice in legal


# --- deal and attempt boundaries ---------------------------------------------------------------


def _prior_for(hand):
    from chitai.agents import BeliefEstimator

    estimator = BeliefEstimator()
    estimator.start_deal(NAMES, hand, True)
    return estimator.probabilities()


def test_every_new_attempt_new_round_and_new_initial_claim_resets_the_belief():
    bot = MindBot()
    run_script(bot, tie_script())
    assert bot.estimator.probabilities() != _prior_for((A, A, B, C))
    # a draw: same round, next attempt
    bot.choose_action(*obs_initial((B, B, C, D), key=(0, 2)))
    assert bot.estimator.probabilities() == _prior_for((B, B, C, D))
    # a completed round: new deal
    bot.choose_action(*obs_initial((A, B, C, D), key=(1, 1)))
    assert bot.estimator.probabilities() == _prior_for((A, B, C, D))
    # same key repeated is still a new deal if it begins with an initial claim (e.g. a reused agent)
    bot.choose_action(*obs_passing((A, B, C, D, D), "non_initiator_receive", key=(1, 1)))
    bot.choose_action(*obs_initial((C, C, D, D), key=(1, 1)))
    assert bot.estimator.probabilities() == _prior_for((C, C, D, D))


def test_a_change_of_attempt_without_an_initial_claim_still_resets_safely():
    bot = MindBot()
    run_script(bot, tie_script())
    bot.choose_action(*obs_passing((A, B, C, D, D), "non_initiator_receive", key=(0, 2)))  # mid-deal
    assert bot.estimator.probabilities() == {name: 0.25 for name in NAMES}
    assert bot.diagnostics()["estimator_uniform_priors"] == 1


def test_a_first_sight_in_the_middle_of_a_deal_starts_uniform_and_then_learns():
    bot = MindBot()
    first, legal = obs_passing((A, A, B, C, D), "non_initiator_receive")
    choice = bot.choose_action(first, legal)
    assert bot.estimator.probabilities() == {name: 0.25 for name in NAMES}
    hand = list(first.my_hand)
    hand.remove(choice.chit_name)  # what it really passed; then the predecessor sends a B
    bot.choose_action(*obs_passing(hand + [B], "non_initiator_receive"))
    assert bot.estimator.probability(B) < 0.25
    assert bot.diagnostics()["estimator_unreconstructable"] == 0


def test_reaction_observations_neither_update_nor_reset_the_belief():
    bot = MindBot()
    run_script(bot, tie_script())
    before = bot.estimator.probabilities()
    stats = bot.estimator.stats()
    bot.choose_action(*obs_reaction((A, A, B, C)))
    assert bot.estimator.probabilities() == before
    assert bot.estimator.stats() == stats


def test_an_unreconstructable_transition_is_survived_without_corrupting_the_belief():
    bot = MindBot()
    run_script(bot, tie_script())  # passed A: the agent's record says its hand is now A B B C
    before = bot.estimator.probabilities()
    # the real hand is not what that record implies (e.g. an unrecorded forced pass)
    observation, legal = obs_passing((B, C, D, D, D), "non_initiator_receive")
    choice = bot.choose_action(observation, legal)
    assert choice in legal
    assert bot.estimator.probabilities() == before
    assert bot.diagnostics()["estimator_unreconstructable"] == 1
    # the agent resynchronised on that observation, so the next transition is readable again
    hand = list(observation.my_hand)
    if isinstance(choice, NamePassAction):
        hand.remove(choice.chit_name)
    bot.choose_action(*obs_passing(hand + [C], "non_initiator_receive"))
    assert bot.diagnostics()["estimator_unreconstructable"] == 1
    assert bot.diagnostics()["estimator_updates"] == 2  # B (first cycle) and now C
    assert bot.estimator.probabilities() != before


# --- determinism -------------------------------------------------------------------------------


def test_identical_call_sequences_give_identical_choices_beliefs_and_diagnostics():
    first, second = MindBot(), MindBot()
    script = tie_script() + [obs_initial((B, B, C, D), key=(0, 2)), obs_passing((B, B, C, D, A), "non_initiator_receive", key=(0, 2))]
    assert run_script(first, script) == run_script(second, script)
    assert first.estimator.probabilities() == second.estimator.probabilities()
    assert first.diagnostics() == second.diagnostics()


def test_whole_games_are_reproducible_and_agents_are_independent_between_games():
    config = _game_config(5)
    first = [run_game(config, g, agent_factory=lambda spec: MindBot()) for g in range(3)]
    second = [run_game(config, g, agent_factory=lambda spec: MindBot()) for g in range(3)]
    assert [_outcome(r) for r in first] == [_outcome(r) for r in second]
    # game 2 played alone equals game 2 played after games 0 and 1 (no state leaks between games)
    alone = run_game(config, 2, agent_factory=lambda spec: MindBot())
    assert _outcome(alone) == _outcome(first[2])


# --- privacy: only the agent-visible fields are read -------------------------------------------

_MINDBOT_OBSERVATION_FIELDS = {"chit_names", "my_hand", "phase", "completed_rounds", "attempt"}
PACKAGE_DIR = Path(agents_pkg.__file__).parent


def test_mindbot_and_the_estimator_read_only_the_declared_observation_fields():
    tree = ast.parse((PACKAGE_DIR / "mindbot.py").read_text(encoding="utf-8"))
    read = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "observation"
    }
    assert read <= _MINDBOT_OBSERVATION_FIELDS, read - _MINDBOT_OBSERVATION_FIELDS
    belief_tree = ast.parse((PACKAGE_DIR / "belief.py").read_text(encoding="utf-8"))
    for node in ast.walk(belief_tree):  # the estimator only ever receives plain names and hands
        if isinstance(node, ast.ImportFrom):
            assert "observations" not in (node.module or ""), node.module
            assert not any(alias.name == "Observation" for alias in node.names)
        if isinstance(node, ast.Name):
            assert node.id not in {"Observation", "observation"}, node.id


def test_changing_every_other_observation_field_changes_nothing():
    """Scores, hand sizes, reaction order, who decides, the initiator, timing settings and the
    winner are public or hidden-adjacent; the agent's behaviour must not depend on any of them."""
    plain = tie_script()
    skewed = [
        (
            replace(
                observation,
                scores=tuple(range(50, 50 + len(observation.scores))),
                hand_sizes=tuple(9 for _ in observation.hand_sizes),
                reaction_order=tuple(reversed(range(observation.num_players))),
                pending_reactors=(0, 1, 2),
                winner=2,
                initiator=3,
                decision_seat=0,
                pass_timeout_seconds=1.5,
                my_turn=False,
            ),
            legal,
        )
        for observation, legal in plain
    ]
    a, b = MindBot(), MindBot()
    assert run_script(a, plain) == run_script(b, skewed)
    assert a.estimator.probabilities() == b.estimator.probabilities()
    assert a.diagnostics() == b.diagnostics()


# --- diagnostics -------------------------------------------------------------------------------


def test_diagnostics_are_consistent_integers_over_real_games():
    config = _game_config(5)
    totals = Counter()
    for game_index in range(3):
        agents = []

        def factory(spec, agents=agents):
            agents.append(MindBot())
            return agents[-1]

        run_game(config, game_index, agent_factory=factory)
        for agent in agents:
            stats = agent.diagnostics()
            assert all(type(value) is int and value >= 0 for value in stats.values())
            assert stats["decisions"] == stats["matched_rulebot"] + stats["inference_changed_action"]
            assert stats["inference_changed_action"] <= stats["inference_eligible"] <= stats["pass_decisions"] <= stats["decisions"]
            assert stats["estimator_unreconstructable"] == 0  # no faults happen in these games
            assert stats["estimator_uniform_priors"] == 0
            assert stats["estimator_normalisation_resets"] == 0
            totals.update(stats)
    assert totals["decisions"] > 0 and totals["inference_eligible"] > 0
    json.dumps(dict(totals))  # serialisable for later aggregation
