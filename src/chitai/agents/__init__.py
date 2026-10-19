"""Agents (Milestone 8). One interface, one baseline: RuleBot.

An agent is a pure decision-maker that sees only what a player may know: its own
`Observation` and its own legal-action tuple (see `chitai.observations`). It never
touches the engine, the game state, the seed or any log. Behavioural-inference
agents (SmartBot, MindBot) belong to Milestone 9.
"""

from .base import Agent
from .rulebot import RuleBot, is_claimable

__all__ = ["Agent", "RuleBot", "is_claimable"]
