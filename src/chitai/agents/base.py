"""The agent interface (M8, PROJECT_CONTEXT.md §2, §3A.8).

All agents use the same interface and receive only player-appropriate
information: the `Observation` for their own seat and the tuple of actions that
`legal_actions_for` offers that seat. They return one element of that tuple.
Returning an element, rather than building an action, keeps an agent from acting
for another seat by construction. The host (the simulation runner) still
validates every answer; a wrong answer is a fault, not an intentional choice.

Deliberately not part of the interface in M8: any per-seat event history (M9),
any error callback or retry channel, any access to the engine, the game state,
the configuration or the seed.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..observations import AgentAction, Observation


@runtime_checkable
class Agent(Protocol):
    """What the runner needs from an agent.

    agent_type / agent_version / agent_config describe the agent in logs and
    summaries. `agent_config` holds JSON primitives only and never anything
    about a game in progress.
    """

    agent_type: str
    agent_version: str
    agent_config: dict[str, Any]

    def choose_action(
        self, observation: Observation, legal_actions: tuple[AgentAction, ...]
    ) -> AgentAction:
        """Return one element of `legal_actions` for the observed seat."""
        ...
