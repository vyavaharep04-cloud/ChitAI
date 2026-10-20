"""MindBot: RuleBot with tie-break-only behavioural inference (M9).

MindBot is RuleBot in every respect except one choice. RuleBot collects the most
frequently held chit name and, when several names are equally frequent, takes the first
in canonical order. MindBot instead breaks *that tie only* using its belief about which
name its predecessor is collecting (`belief.BeliefEstimator`): among the equally common
names it collects the one the predecessor is LEAST likely to be collecting, on the
reasoning that a collector withholds its own name, so a name the predecessor is not
hoarding is likelier to come round to MindBot. That reasoning is a hypothesis under
test, not an established fact. MindBot never changes whether it claims, which names
count as the target when counts differ, the order of non-target names, or draw
avoidance. With `use_inference=False` the tie-break reverts to RuleBot's and the agent
is behaviourally identical to RuleBot (and keeps no estimator state).

Information: only the `Observation` and legal-action tuple the runner hands over (the
Agent protocol, M8), plus MindBot's own memory of its previous hand and previous action
between calls. A fresh agent is built per game (runner), and a new deal or attempt is
detected from the observation (the initial-claim decision, or a changed
`(completed_rounds, attempt)`), so no belief survives a deal boundary. Reaction order,
timing, scores, other seats' hand sizes and every other seat's actions are not used.

Diagnostics (`diagnostics()`) are plain counters held by the agent instance. They are
host-side bookkeeping for the experiment, are never part of `agent_config`, and contain no
hidden information: they only count MindBot's own decisions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..observations import AgentAction, NamePassAction, Observation
from .belief import DEFAULT_EPSILON, BeliefEstimator
from .rulebot import RuleBot

_PASSING_PHASES = ("initial_claims", "passing")  # the phases in which a hand is a deal's own


class MindBot(RuleBot):
    """RuleBot whose target tie-break uses a belief about the preceding player."""

    agent_type = "mindbot"
    agent_version = "1"

    def __init__(
        self,
        avoid_draw: bool = True,
        non_target_order: str = "most_copies",
        use_inference: bool = True,
        epsilon: float = DEFAULT_EPSILON,
    ) -> None:
        super().__init__(avoid_draw=avoid_draw, non_target_order=non_target_order)
        if not isinstance(use_inference, bool):
            raise TypeError(f"use_inference must be a bool, got {use_inference!r}")
        self.use_inference = use_inference
        self.estimator = BeliefEstimator(epsilon)  # validates epsilon
        self.agent_config: dict[str, Any] = {
            "avoid_draw": avoid_draw,
            "non_target_order": non_target_order,
            "use_inference": use_inference,
            "epsilon": self.estimator.epsilon,
        }
        self._baseline = RuleBot(avoid_draw=avoid_draw, non_target_order=non_target_order)
        self._deal_key: tuple[int, int] | None = None
        self._counters = {
            "decisions": 0,
            "pass_decisions": 0,
            "inference_eligible": 0,
            "inference_changed_action": 0,
            "matched_rulebot": 0,
        }

    # --- the decision ---------------------------------------------------------------------

    def choose_action(
        self, observation: Observation, legal_actions: tuple[AgentAction, ...]
    ) -> AgentAction:
        baseline = self._baseline.choose_action(observation, legal_actions)  # raises like RuleBot
        tracking = self.use_inference and observation.phase in _PASSING_PHASES
        if tracking:
            self._observe(observation)
        choice = super().choose_action(observation, legal_actions)
        if tracking:
            passed = choice.chit_name if isinstance(choice, NamePassAction) else None
            self.estimator.after_decision(observation.my_hand, passed)

        self._counters["decisions"] += 1
        if isinstance(choice, NamePassAction):
            self._counters["pass_decisions"] += 1
        if choice == baseline:
            self._counters["matched_rulebot"] += 1
        else:
            self._counters["inference_changed_action"] += 1
        return choice

    def _observe(self, observation: Observation) -> None:
        """Start a fresh belief at a deal boundary, otherwise read the hand transition."""
        key = (observation.completed_rounds, observation.attempt)
        starts_deal = observation.phase == "initial_claims"
        if starts_deal or key != self._deal_key or not self.estimator.active:
            self._deal_key = key
            self.estimator.start_deal(observation.chit_names, observation.my_hand, starts_deal)
        else:
            self.estimator.observe_hand(observation.my_hand)

    def _choose_target(
        self, observation: Observation, counts: Counter[str], held: list[str]
    ) -> str | None:
        if not held or not self.use_inference:
            return super()._choose_target(observation, counts, held)
        top = counts[held[0]]
        tied = [name for name in held if counts[name] == top]  # canonical order preserved
        if len(tied) < 2:
            return held[0]
        self._counters["inference_eligible"] += 1
        if not self.estimator.active:
            return held[0]
        belief = self.estimator.probabilities()
        # least likely to be the predecessor's target; exact ties keep canonical order
        return min(tied, key=lambda name: (belief.get(name, 0.0), tied.index(name)))

    # --- diagnostics ----------------------------------------------------------------------

    def diagnostics(self) -> dict[str, int]:
        """Counters of this agent's own decisions plus estimator bookkeeping."""
        return {**self._counters, **{f"estimator_{k}": v for k, v in self.estimator.stats().items()}}


__all__ = ["MindBot"]
