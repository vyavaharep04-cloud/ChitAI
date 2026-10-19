"""Simulation building blocks (Milestone 8, Stage 2).

Pure, side-effect-free pieces only: deterministic seeds, seat rotation and the
reaction-order policy (`seeds`), the validated configuration (`config`) and the
result records with termination statuses and ranking (`results`). The runner, the
event log and the batch/CLI layers arrive in later stages.
"""

from .config import (
    CONFIG_SCHEMA_VERSION,
    AgentSpec,
    OutputOptions,
    SimulationConfig,
    SimulationConfigError,
    canonical_json,
)
from .results import (
    ROUND_OUTCOMES,
    STATUS_ACTION_CAP_REACHED,
    STATUS_AGENT_FAULT_UNRESOLVABLE,
    STATUS_COMPLETED,
    STATUS_DRAW_CAP_REACHED,
    STOPPED_STATUSES,
    TERMINATION_STATUSES,
    GameResult,
    ResultError,
    RoundResult,
    SeatResult,
    competition_ranks,
    final_ranks,
    tie_flags,
)
from .runner import AGENT_TYPES, RunnerError, build_agent, run_game
from .seeds import (
    GAME,
    REACTION,
    game_seed,
    lineup_seat,
    reaction_order,
    reaction_order_for_state,
    seat_assignment,
    seated_lineup,
    seed_index,
)

__all__ = [
    "AGENT_TYPES",
    "CONFIG_SCHEMA_VERSION",
    "GAME",
    "REACTION",
    "ROUND_OUTCOMES",
    "STATUS_ACTION_CAP_REACHED",
    "STATUS_AGENT_FAULT_UNRESOLVABLE",
    "STATUS_COMPLETED",
    "STATUS_DRAW_CAP_REACHED",
    "STOPPED_STATUSES",
    "TERMINATION_STATUSES",
    "AgentSpec",
    "GameResult",
    "OutputOptions",
    "ResultError",
    "RoundResult",
    "RunnerError",
    "SeatResult",
    "SimulationConfig",
    "SimulationConfigError",
    "build_agent",
    "canonical_json",
    "competition_ranks",
    "final_ranks",
    "game_seed",
    "lineup_seat",
    "reaction_order",
    "reaction_order_for_state",
    "run_game",
    "seat_assignment",
    "seated_lineup",
    "seed_index",
    "tie_flags",
]
