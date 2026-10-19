"""RuleBot: the transparent, deterministic baseline agent (M8, PROJECT_CONTEXT.md §2).

RuleBot is a pure function of the `Observation` and the legal-action tuple it is
handed. It uses no randomness, no clock, no memory between calls, no hidden
state and no inference about opponents (that is Milestone 9). It never builds an
action: it returns an element of the tuple it was given.

Decisions
---------
* Reaction offered: react (the only legal action).
* Claim opportunity (initial, receive or return): claim exactly when some chit
  name is held four times, which is the engine's validity rule for all three
  positions (all four of four, or four of five). Otherwise decline (initial
  phase) or pass. RuleBot never makes a false claim.
* Passing, "commit to target": the target is the most frequently held name
  (ties go to the earlier name in `observation.chit_names`). RuleBot passes a
  name other than the target whenever one is legal; the target is passed only
  when nothing else is legal.
* Among non-target names the order of preference is set by `non_target_order`.
  PROVISIONAL (owner decision D5): both variants exist only so Stage 3 can
  measure them; the unused one is to be removed once the owner chooses.
* Draw avoidance (`avoid_draw`, default on): RuleBot reads its own anti-stall
  streak from the observation. When one more pass of the same name would be the
  tenth, it prefers any other legal name.

Duplicate names are handled purely by name. RuleBot counts repeats in `my_hand`
and chooses among one `NamePassAction` per distinct name; it never sees which
physical copy is passed.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..engine import CONSECUTIVE_PASS_LIMIT, ClaimAction, DeclineAction, ReactAction
from ..observations import AgentAction, NamePassAction, Observation

CLAIM_COPIES = 4  # the same name four times: the only possible winning pattern

NON_TARGET_ORDERS = ("most_copies", "fewest_copies")


def is_claimable(my_hand: tuple[str, ...]) -> bool:
    """True when `my_hand` (chit names, with repeats) holds one name four times.

    This is the engine's claim-validity rule at every claim opportunity: all four
    of the initiator's or initial hand, or four of a receiver's five. It is the
    agent's own reading of its observed hand; tests cross-check it against the
    engine's `is_valid_claim` so the two cannot drift apart.
    """
    return max(Counter(my_hand).values(), default=0) >= CLAIM_COPIES


class RuleBot:
    """Deterministic commit-to-target baseline."""

    agent_type = "rulebot"
    agent_version = "1"

    def __init__(self, avoid_draw: bool = True, non_target_order: str = "most_copies") -> None:
        if not isinstance(avoid_draw, bool):
            raise TypeError(f"avoid_draw must be a bool, got {avoid_draw!r}")
        if non_target_order not in NON_TARGET_ORDERS:
            raise ValueError(f"non_target_order must be one of {NON_TARGET_ORDERS}, got {non_target_order!r}")
        self.avoid_draw = avoid_draw
        self.non_target_order = non_target_order
        self.agent_config: dict[str, Any] = {
            "avoid_draw": avoid_draw,
            "non_target_order": non_target_order,
        }

    def choose_action(
        self, observation: Observation, legal_actions: tuple[AgentAction, ...]
    ) -> AgentAction:
        if not legal_actions:
            raise ValueError("no legal action to choose from")

        for action in legal_actions:
            if isinstance(action, ReactAction):
                return action

        if is_claimable(observation.my_hand):
            for action in legal_actions:
                if isinstance(action, ClaimAction):
                    return action

        for action in legal_actions:
            if isinstance(action, DeclineAction):
                return action

        passes = {a.chit_name: a for a in legal_actions if isinstance(a, NamePassAction)}
        if not passes:
            raise ValueError("no usable action: only a claim is offered and the hand cannot claim")
        return passes[self._choose_pass_name(observation, tuple(passes))]

    def _choose_pass_name(self, observation: Observation, legal_names: tuple[str, ...]) -> str:
        order = {name: index for index, name in enumerate(observation.chit_names)}
        counts = Counter(observation.my_hand)

        def canonical(name: str) -> int:
            return order[name]

        held = sorted(counts, key=lambda name: (-counts[name], canonical(name)))
        target = held[0] if held else None

        non_target = [name for name in legal_names if name != target]
        if self.non_target_order == "most_copies":
            non_target.sort(key=lambda name: (-counts[name], canonical(name)))
        else:
            non_target.sort(key=lambda name: (counts[name], canonical(name)))
        ranked = non_target + [name for name in legal_names if name == target]

        if (
            self.avoid_draw
            and observation.my_pass_streak_count >= CONSECUTIVE_PASS_LIMIT - 1
            and observation.my_pass_streak_name in ranked
            and len(ranked) > 1
        ):
            ranked.remove(observation.my_pass_streak_name)
        return ranked[0]
