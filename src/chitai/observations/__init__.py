"""Player-specific observations, legal actions and event views (Milestone 7).

This package sits *above* the engine: it reads engine state and events and never
changes engine behaviour. It is the privacy boundary for agents and clients.
"""

from .events import observe_event, observe_events
from .legal import (
    AgentAction,
    NamePassAction,
    action_to_dict,
    legal_actions_for,
    to_engine_action,
)
from .observation import Observation, observe

__all__ = [
    "AgentAction",
    "NamePassAction",
    "Observation",
    "action_to_dict",
    "legal_actions_for",
    "observe",
    "observe_event",
    "observe_events",
    "to_engine_action",
]
