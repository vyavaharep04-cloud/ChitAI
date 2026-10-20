"""BeliefEstimator: prior, evidence, boundaries, bad transitions, determinism (M9 Stage 1).

The hand-difference method is checked here against the engine's own ground truth
(`ChitPassed` events seen only by the host-side recorder), including the initiator's
first pass, the temporary fifth chit, the initiator's return, and draw redeals.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest
from simulation.support import config_dict

from chitai.agents import RuleBot
from chitai.agents import belief as belief_module
from chitai.agents.belief import (
    DEFAULT_EPSILON,
    INACTIVE,
    NO_CHANGE,
    RECEIVED,
    UNRECONSTRUCTABLE,
    BeliefEstimator,
    validate_epsilon,
)
from chitai.engine import CHITS_PER_HAND, COPIES_PER_NAME, ChitPassed, DealEvent, chit_names_for
from chitai.simulation import SimulationConfig
from chitai.simulation.runner import run_game

NAMES = tuple(chit_names_for(4))  # four names
A, B, C, D = NAMES


def fresh(epsilon=DEFAULT_EPSILON, hand=(A, A, B, C), names=NAMES):
    estimator = BeliefEstimator(epsilon)
    estimator.start_deal(names, hand, at_deal_start=True)
    return estimator


def normalised(weights):
    total = sum(weights.values())
    return {name: weight / total for name, weight in weights.items()}


# --- constants and construction ------------------------------------------------------------


def test_restated_rule_constants_match_the_engine():
    assert belief_module.CHITS_PER_HAND == CHITS_PER_HAND == 4
    assert belief_module.COPIES_PER_NAME == COPIES_PER_NAME == 4


@pytest.mark.parametrize("bad", [0, 0.0, -0.1, 1.0000001, 2, float("nan"), float("inf")])
def test_epsilon_outside_zero_to_one_is_rejected(bad):
    with pytest.raises(ValueError):
        BeliefEstimator(bad)


@pytest.mark.parametrize("bad", [True, "0.2", None, [0.2]])
def test_epsilon_of_the_wrong_type_is_rejected(bad):
    with pytest.raises(TypeError):
        validate_epsilon(bad)


def test_epsilon_one_and_integers_are_accepted():
    assert BeliefEstimator(1).epsilon == 1.0
    assert BeliefEstimator(0.5).epsilon == 0.5


def test_an_estimator_that_was_never_started_is_inactive_and_inert():
    estimator = BeliefEstimator()
    assert not estimator.active
    assert estimator.probabilities() == {}
    assert estimator.probability(A) == 0.0
    assert estimator.observe_hand((A, A, B, C)) == INACTIVE
    estimator.after_decision((A, A, B, C), A)  # a no-op, never raises
    assert not estimator.active


# --- prior ---------------------------------------------------------------------------------


def test_prior_weights_are_copies_not_held_and_normalised():
    belief = fresh(hand=(A, A, B, C)).probabilities()
    # held 2, 1, 1, 0 -> weights 2, 3, 3, 4 -> total 12
    assert belief == {A: 2 / 12, B: 3 / 12, C: 3 / 12, D: 4 / 12}
    assert sum(belief.values()) == pytest.approx(1.0)


def test_a_name_held_four_times_gets_zero_prior_and_the_rest_stay_normalised():
    belief = fresh(hand=(A, A, A, A)).probabilities()
    assert belief[A] == 0.0
    assert belief[B] == belief[C] == belief[D] == pytest.approx(1 / 3)


def test_prior_is_independent_of_hand_order():
    assert fresh(hand=(C, A, B, A)).probabilities() == fresh(hand=(A, A, B, C)).probabilities()


@pytest.mark.parametrize(
    "hand",
    [
        (A, A, B, C, D),  # five chits: a received chit is mixed in, the dealt hand is unknowable
        (A, B),  # too few
        (),
        (A, A, B, "Nonsense"),  # a name that is not in play
    ],
)
def test_an_unreliable_first_sight_gives_a_uniform_prior(hand):
    estimator = BeliefEstimator()
    estimator.start_deal(NAMES, hand, at_deal_start=True)
    assert estimator.active
    assert estimator.probabilities() == {name: 0.25 for name in NAMES}
    assert estimator.stats()["uniform_priors"] == 1


def test_a_mid_deal_first_sight_gives_a_uniform_prior_even_with_four_chits():
    estimator = BeliefEstimator()
    estimator.start_deal(NAMES, (A, A, B, C), at_deal_start=False)
    assert estimator.probabilities() == {name: 0.25 for name in NAMES}


def test_no_names_means_inactive_not_an_error():
    estimator = BeliefEstimator()
    estimator.start_deal((), (A, A, B, C), at_deal_start=True)
    assert not estimator.active
    assert estimator.probabilities() == {}


# --- evidence ------------------------------------------------------------------------------


def test_receiving_a_name_scales_only_that_weight_by_epsilon_then_normalises():
    estimator = fresh(epsilon=0.2, hand=(A, A, B, C))
    estimator.after_decision((A, A, B, C), None)  # initial decline
    assert estimator.observe_hand((A, A, B, C, B)) == RECEIVED  # received B
    expected = normalised({A: 2, B: 3 * 0.2, C: 3, D: 4})
    assert estimator.probabilities() == pytest.approx(expected)
    assert estimator.last_received == B
    assert sum(estimator.probabilities().values()) == pytest.approx(1.0)


def test_other_names_keep_their_relative_weights():
    estimator = fresh(hand=(A, A, B, C))
    before = estimator.probabilities()
    estimator.after_decision((A, A, B, C), None)
    estimator.observe_hand((A, A, B, C, D))
    after = estimator.probabilities()
    assert after[A] / after[C] == pytest.approx(before[A] / before[C])
    assert after[D] < before[D]


def test_repeated_receipts_keep_lowering_the_same_name_and_never_go_negative():
    estimator = fresh(hand=(A, A, B, C))
    hand = [A, A, B, C]
    last = estimator.probability(D)
    for _ in range(5):
        estimator.after_decision(tuple(hand), None)
        estimator.observe_hand(tuple(hand + [D]))
        assert estimator.probability(D) < last
        last = estimator.probability(D)
        # D is passed on again, so the next decision starts from four chits plus one D again
        estimator.after_decision(tuple(hand + [D]), D)
    assert all(p >= 0 for p in estimator.probabilities().values())


def test_epsilon_one_ignores_the_evidence():
    estimator = fresh(epsilon=1.0)
    before = estimator.probabilities()
    estimator.after_decision((A, A, B, C), None)
    assert estimator.observe_hand((A, A, B, C, D)) == RECEIVED
    assert estimator.probabilities() == pytest.approx(before)


def test_a_pass_is_subtracted_before_the_next_comparison():
    """Non-initiator cycle: hold 5, pass one (the received one or an old one), later hold 5 again."""
    estimator = fresh(hand=(A, A, B, C))
    estimator.after_decision((A, A, B, C), None)
    estimator.observe_hand((A, A, B, C, D))  # received D
    estimator.after_decision((A, A, B, C, D), C)  # passed C: now A A B D
    assert estimator.observe_hand((A, A, B, D, B)) == RECEIVED
    assert estimator.last_received == B


def test_the_initiator_first_pass_is_no_change_then_the_return_is_a_receipt():
    """Initiator: decline holding 4, first pass holding 4 (nothing arrived), return holding 4 after
    passing one (3 in transit)."""
    estimator = fresh(hand=(A, A, B, C))
    estimator.after_decision((A, A, B, C), None)  # initial decline
    assert estimator.observe_hand((A, A, B, C)) == NO_CHANGE  # INITIATOR_FIRST_PASS
    assert estimator.last_received is None
    before = estimator.probabilities()
    estimator.after_decision((A, A, B, C), C)  # passes C, holds A A B
    assert estimator.observe_hand((A, A, B, D)) == RECEIVED  # INITIATOR_RETURN brings D
    assert estimator.last_received == D
    assert estimator.probability(D) < before[D]


# --- invalid or unreconstructable transitions ---------------------------------------------


@pytest.mark.parametrize(
    "hand",
    [
        (A, B, C, D),  # a chit vanished and another appeared
        (A, A, B),  # a chit vanished
        (A, A, B, C, D, D),  # two chits arrived
        (A, A, B, C, "Nonsense"),  # unknown name
        (A, A, A, A, A),  # more copies than exist
        (),
    ],
)
def test_an_unreconstructable_transition_leaves_the_belief_untouched(hand):
    estimator = fresh()
    estimator.after_decision((A, A, B, C), None)
    before = estimator.probabilities()
    assert estimator.observe_hand(hand) == UNRECONSTRUCTABLE
    assert estimator.probabilities() == before
    assert estimator.last_received is None
    assert estimator.stats()["unreconstructable"] == 1


def test_a_pass_that_does_not_match_the_hand_makes_the_next_comparison_unreconstructable():
    estimator = fresh()
    estimator.after_decision((A, A, B, C), D)  # claims to have passed D, which was not held
    before = estimator.probabilities()
    assert estimator.observe_hand((A, A, B, C, D)) == UNRECONSTRUCTABLE
    assert estimator.probabilities() == before


def test_a_forced_unknown_pass_is_survivable_and_the_next_decision_resynchronises():
    """A host timeout passes a chit the agent never learns. The comparison after it cannot be
    trusted; once the agent records its next decision the following one can."""
    estimator = fresh()
    estimator.after_decision((A, A, B, C), None)
    estimator.observe_hand((A, A, B, C, B))  # received B: hand A A B B C
    # the agent faulted; the host timed out and passed an unknown chit (here a B)
    estimator.after_decision((A, A, B, B, C), A)  # the agent's own record of its intended pass
    snapshot = estimator.probabilities()
    assert estimator.observe_hand((A, A, B, C, D, D)) == UNRECONSTRUCTABLE
    assert estimator.probabilities() == snapshot
    estimator.after_decision((A, A, B, C, D, D), None)  # resync (hand is what it is)
    assert estimator.observe_hand((A, A, B, C, D, D)) == NO_CHANGE


def test_a_corrupted_expectation_never_corrupts_the_belief_later():
    estimator = fresh()
    estimator.after_decision(("junk",), A)  # unusable record
    assert estimator.observe_hand((A, A, B, C)) == UNRECONSTRUCTABLE
    estimator.after_decision((A, A, B, C), None)
    assert estimator.observe_hand((A, A, B, C, C)) == RECEIVED
    assert sum(estimator.probabilities().values()) == pytest.approx(1.0)


def test_underflow_to_zero_falls_back_to_the_prior_and_is_counted():
    estimator = fresh(hand=(A, A, B, C))
    estimator._weights = {name: 0.0 for name in NAMES}  # a corrupted state, injected on purpose
    estimator.after_decision((A, A, B, C), None)
    assert estimator.observe_hand((A, A, B, C, B)) == RECEIVED
    assert estimator.probabilities() == fresh(hand=(A, A, B, C)).probabilities()
    assert estimator.stats()["normalisation_resets"] == 1


def test_very_long_runs_stay_finite_and_normalised():
    estimator = fresh(epsilon=1e-3)
    for _ in range(2000):
        estimator.after_decision((A, A, B, C), None)
        estimator.observe_hand((A, A, B, C, D))
    probabilities = estimator.probabilities()
    assert all(0.0 <= p <= 1.0 for p in probabilities.values())
    assert sum(probabilities.values()) == pytest.approx(1.0)


# --- deal and attempt boundaries -----------------------------------------------------------


def test_a_new_deal_discards_the_old_belief_completely():
    estimator = fresh(hand=(A, A, B, C))
    estimator.after_decision((A, A, B, C), None)
    estimator.observe_hand((A, A, B, C, D))
    assert estimator.probabilities() != fresh(hand=(A, A, B, C)).probabilities()
    estimator.start_deal(NAMES, (B, B, C, D), at_deal_start=True)
    assert estimator.probabilities() == fresh(hand=(B, B, C, D)).probabilities()
    # and the old expectation is gone: the new deal's first comparison is judged on the new hand
    estimator.after_decision((B, B, C, D), None)
    assert estimator.observe_hand((A, A, B, C, D)) == UNRECONSTRUCTABLE


def test_a_new_deal_also_discards_the_old_expected_hand():
    """Even if a comparison were attempted before the next decision is recorded, it is judged
    against the new deal's first hand, never against the previous deal's leftover record."""
    estimator = fresh(hand=(A, A, B, C))
    estimator.after_decision((A, A, B, C), None)  # old record: A A B C
    estimator.start_deal(NAMES, (B, B, C, D), at_deal_start=True)
    assert estimator.observe_hand((B, B, C, D)) == NO_CHANGE


# --- determinism and totality ---------------------------------------------------------------


def _scripted_run():
    estimator = fresh()
    hand = [A, A, B, C]
    estimator.after_decision(tuple(hand), None)
    for name in (D, B, D, C, A, D):
        estimator.observe_hand(tuple(hand + [name]))
        estimator.after_decision(tuple(hand + [name]), name)
    return estimator.probabilities(), estimator.stats()


def test_the_same_inputs_always_give_exactly_the_same_belief():
    assert _scripted_run() == _scripted_run()


def test_no_input_can_make_the_estimator_raise():
    rng = random.Random(20261019)
    junk = [A, B, C, D, "Nonsense", None, 7, "", (A,)]
    estimator = BeliefEstimator()
    for _ in range(3000):
        action = rng.choice(["start", "observe", "after"])
        hand = tuple(rng.choice(junk) for _ in range(rng.randint(0, 7)))
        if action == "start":
            names = tuple(rng.choice(junk) for _ in range(rng.randint(0, 5)))
            estimator.start_deal(names, hand, rng.random() < 0.5)
        elif action == "observe":
            estimator.observe_hand(hand)
        else:
            estimator.after_decision(hand, rng.choice(junk))
        probabilities = estimator.probabilities()
        if estimator.active:
            assert sum(probabilities.values()) == pytest.approx(1.0)
            assert all(0.0 <= p <= 1.0 for p in probabilities.values())


# --- ground truth against the real engine ---------------------------------------------------


class _Recorder:
    """Host-side observer: keeps the engine's private events (ground truth) for the test only."""

    def __init__(self):
        self.batches = []

    def opening(self, events):
        self.batches.append(list(events))

    def accepted(self, events):
        self.batches.append(list(events))

    def fault(self, *args):
        pass


class _Probe(RuleBot):
    """A RuleBot that also runs the estimator exactly as MindBot does, and logs what it read."""

    def __init__(self, log, **kwargs):
        super().__init__(**kwargs)
        self.estimator = BeliefEstimator()
        self.key = None
        self.log = log

    def choose_action(self, observation, legal_actions):
        outcome = None
        key = (observation.completed_rounds, observation.attempt)
        if observation.phase in ("initial_claims", "passing"):
            starts = observation.phase == "initial_claims"
            if starts or key != self.key or not self.estimator.active:
                self.key = key
                self.estimator.start_deal(observation.chit_names, observation.my_hand, starts)
                outcome = "start"
            else:
                outcome = self.estimator.observe_hand(observation.my_hand)
        choice = super().choose_action(observation, legal_actions)
        if outcome is not None:
            passed = getattr(choice, "chit_name", None)
            self.estimator.after_decision(observation.my_hand, passed)
            self.log.append((observation.my_seat, key, observation.decision_kind, outcome, self.estimator.last_received))
        return choice


def _play(num_players, game_index, avoid_draw):
    log = []
    recorder = _Recorder()
    spec = {"agent_type": "rulebot", "agent_config": {"avoid_draw": avoid_draw}}
    config = SimulationConfig.from_dict(
        config_dict(
            lineup=[spec] * num_players,
            num_players=num_players,
            num_rounds=num_players,
            game_count=4,
            batch_seed=11,
            max_draw_restarts_per_round=50,
            max_actions_per_attempt=300,
        )
    )
    result = run_game(config, game_index, agent_factory=lambda s: _Probe(log, **s.to_dict()["agent_config"]), recorder=recorder)
    return result, log, recorder


def _truth(recorder):
    """Names each seat was really sent, per deal ordinal, from the engine's own events."""
    received, deal = {}, -1
    for batch in recorder.batches:
        for event in batch:
            if isinstance(event, DealEvent):
                deal += 1
            elif isinstance(event, ChitPassed):
                received.setdefault((deal, event.to_seat), []).append(event.chit.name)
    return received


@pytest.mark.parametrize("num_players", [4, 5, 7])
@pytest.mark.parametrize("avoid_draw", [True, False])
def test_reconstructed_receipts_equal_the_engines_ground_truth(num_players, avoid_draw):
    decisions = compared = draws = 0
    for game_index in range(4):
        result, log, recorder = _play(num_players, game_index, avoid_draw)
        draws += result.draw_restarts
        truth = _truth(recorder)
        deals = []
        for _, key, *_ in log:
            if key not in deals:
                deals.append(key)
        seen = {}
        for seat, key, kind, outcome, received in log:
            decisions += 1
            assert outcome != UNRECONSTRUCTABLE, (seat, key, kind)  # no faults, so always readable
            if kind == "initiator_first_pass":
                assert outcome == NO_CHANGE and received is None
            elif kind in ("non_initiator_receive", "initiator_return"):
                assert outcome == RECEIVED and received is not None
                seen.setdefault((deals.index(key), seat), []).append(received)
        for slot, names in seen.items():
            compared += len(names)
            assert names == truth.get(slot, [])[: len(names)], slot
    assert decisions > 0 and compared > 0
    if not avoid_draw and num_players == 4:
        assert draws > 0, "this configuration is expected to exercise draw redeals"


def test_every_decision_kind_that_changes_the_hand_is_exercised():
    kinds = Counter()
    for game_index in range(3):
        _, log, _ = _play(5, game_index, True)
        kinds.update(kind for _, _, kind, *_ in log)
    assert {"initial_claim", "initiator_first_pass", "non_initiator_receive", "initiator_return"} <= set(kinds)
