"""Agents (Milestone 8). One interface, one baseline: RuleBot.

An agent is a pure decision-maker that sees only what a player may know: its own
`Observation` and its own legal-action tuple (see `chitai.observations`). It never
touches the engine, the game state, the seed or any log. MindBot (M9) is RuleBot plus
tie-break-only behavioural inference; it keeps its own memory between calls.
"""

from .base import Agent
from .belief import BeliefEstimator
from .mindbot import MindBot
from .rulebot import RuleBot, is_claimable

__all__ = ["Agent", "BeliefEstimator", "MindBot", "RuleBot", "is_claimable"]
