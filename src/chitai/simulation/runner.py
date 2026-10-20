"""The single-game simulation runner (M8 Stage 3).

`run_game(config, game_index)` plays one complete AI-only game and returns a
`GameResult`. It connects the authoritative engine, the privacy-safe observations,
the agents and the Stage 2 configuration, seeds and result records. It builds no
rules of its own: every rule, score and ranking input comes from the engine.

Host responsibilities (PROJECT_CONTEXT.md §9 question 32, M7's boundary text):

* An agent receives only ``observe(state, seat)`` and ``legal_actions_for(state,
  seat)`` for the seat that must decide, and is asked exactly once per decision.
  It never receives the state, the configuration, a seed, an event or a rejection.
* The host validates every answer before the engine sees it. An agent exception,
  ``None``, an unknown object, a subclass, another seat's action, an illegal action
  or a timeout is an *agent fault* (never a game action). A fault is resolved
  through the engine's host-issued timeout where the engine allows one, and is
  counted apart from that timeout. There are no retries and no error callback.
* In the reaction phase the faulty seat is deferred (it is never asked again for
  the same win); if the only pending seats have all faulted and two or more remain,
  the engine offers no timeout and the game stops as `agent_fault_unresolvable`.
* An engine rejection of an action the runner itself built from validated input is
  a runner or engine bug and raises `RunnerError`; it is never an agent fault.
* The engine has no draw cap and no action cap. Both are enforced here, and both
  are required configuration values with no default. A capped or unresolvable game
  is *stopped*: scores stay as they were after the last completed round, and the
  record carries no ranks, ties or winners.

Reaction order is an *experimental policy*: a seeded permutation (`seeds`) decides
which pending seat is asked first. It is not a model of human reaction speed, and
the runner never reacts on a seat's behalf. No agent slowness is simulated either:
a host timeout is issued only to resolve an agent fault, and
``pass_timeout_seconds`` is carried into the engine configuration without any
timing existing in the simulator.

Recording (M8 Stage 4): `run_game(..., recorder=...)` accepts an optional *host-side*
observer with three methods: ``opening(events)`` with the opening deal's engine events,
``accepted(events)`` after every accepted action, and ``fault(seat, kind, completed_round,
attempt)`` when an agent fault is classified. It receives the engine's own (private)
events, so it must write public streams only through `observations.observe_event`. It is
never given to an agent, it must not influence the game, and an exception it raises
propagates (a host bug). The result is identical with and without a recorder.

Randomness: none here. Reaction order and deals come from `seeds` and the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import Any

from ..agents import Agent, MindBot, RuleBot
from ..engine import (
    Accepted,
    AttemptDrawn,
    ClaimAction,
    DealEvent,
    DeclineAction,
    DecisionTimedOut,
    FalseClaimPenalized,
    GameConfig,
    PassAction,
    Phase,
    ReactAction,
    Rejected,
    RoundCompleted,
    TimeoutAction,
    ValidWinScored,
    ROUND_OUTCOME_FALSE_CLAIM,
    ROUND_OUTCOME_VALID_WIN,
    apply_action,
    new_game,
    pending_reactors,
    timeout_action,
)
from ..observations import (
    NamePassAction,
    legal_actions_for,
    observe,
    to_engine_action,
)
from .config import AgentSpec, SimulationConfig, SimulationConfigError, canonical_json
from .results import (
    STATUS_ACTION_CAP_REACHED,
    STATUS_AGENT_FAULT_UNRESOLVABLE,
    STATUS_COMPLETED,
    STATUS_DRAW_CAP_REACHED,
    GameResult,
    RoundResult,
    SeatResult,
    final_ranks,
    tie_flags,
)
from .seeds import game_seed, reaction_order_for_state, seat_assignment, seated_lineup

AGENT_TYPES = MappingProxyType({"mindbot": MindBot, "rulebot": RuleBot})
"""The agent types a lineup may name (`AgentSpec.agent_type`)."""

# The only classes an agent may return (exact classes; subclasses are faults) and the
# only classes the engine may be handed by the runner.
_AGENT_ACTION_TYPES = (ClaimAction, DeclineAction, ReactAction, NamePassAction)
_ENGINE_ACTION_TYPES = (ClaimAction, DeclineAction, ReactAction, PassAction)

# Internal fault categories: used for control flow and tests only, never recorded.
FAULT_EXCEPTION = "exception"
FAULT_NOT_AN_ACTION = "not_an_action"
FAULT_TIMEOUT_CHOICE = "timeout_choice"
FAULT_BAD_FIELD = "bad_field"
FAULT_WRONG_SEAT = "wrong_seat"
FAULT_ILLEGAL = "illegal"


class RunnerError(RuntimeError):
    """A runner or engine failure that is not an agent's fault (never recorded as one)."""


# --- agents ---------------------------------------------------------------------------------


def build_agent(spec: AgentSpec) -> Agent:
    """A fresh agent for a lineup entry. Raises `SimulationConfigError` for an unknown
    type or an invalid configuration, before any game is played."""
    if not isinstance(spec, AgentSpec):
        raise SimulationConfigError(f"build_agent needs an AgentSpec, got {type(spec).__name__}")
    constructor = AGENT_TYPES.get(spec.agent_type)
    if constructor is None:
        known = ", ".join(sorted(AGENT_TYPES))
        raise SimulationConfigError(f"unknown agent_type {spec.agent_type!r} (known: {known})")
    try:
        return constructor(**spec.to_dict()["agent_config"])
    except (TypeError, ValueError) as error:
        raise SimulationConfigError(
            f"invalid agent_config for agent_type {spec.agent_type!r}: {error}"
        ) from error


class _Seated:
    """An agent plus the description captured once, at setup, for the result record."""

    __slots__ = ("agent", "agent_type", "agent_version", "config_json")

    def __init__(self, agent: Agent, agent_type: str, agent_version: str, config_json: str) -> None:
        self.agent = agent
        self.agent_type = agent_type
        self.agent_version = agent_version
        self.config_json = config_json


def _seat_agent(factory: Callable[[AgentSpec], Agent], spec: AgentSpec) -> _Seated:
    """Build, check and describe one agent. Every failure is a configuration error."""
    try:
        agent = factory(spec)
    except SimulationConfigError:
        raise
    except Exception as error:
        raise SimulationConfigError(
            f"agent factory failed for agent_type {spec.agent_type!r}: {error}"
        ) from error
    label = f"agent for agent_type {spec.agent_type!r}"
    if not isinstance(agent, Agent) or not callable(getattr(agent, "choose_action", None)):
        raise SimulationConfigError(f"the {label} does not implement the Agent protocol")
    try:
        agent_type, agent_version, agent_config = agent.agent_type, agent.agent_version, agent.agent_config
        if type(agent_type) is not str or type(agent_version) is not str:
            raise SimulationConfigError(f"the {label} must have a string agent_type and agent_version")
        config_json = canonical_json(agent_config)  # the effective config, captured now
    except SimulationConfigError:
        raise
    except Exception as error:
        raise SimulationConfigError(f"the {label} has no valid agent_config: {error}") from error
    return _Seated(agent, agent_type, agent_version, config_json)


# --- decisions ------------------------------------------------------------------------------


def _validate_choice(state: Any, seat: int, choice: object) -> Any:
    """The engine action for an agent's answer, or a `FAULT_*` string.

    Runs before `apply_action`. Hardens `to_engine_action` (which accepts any object
    that merely compares equal to a legal action) with exact-class and field-type
    checks. Never builds an action for a seat other than `seat`.
    """
    if type(choice) is TimeoutAction:
        return FAULT_TIMEOUT_CHOICE
    if type(choice) not in _AGENT_ACTION_TYPES:
        return FAULT_NOT_AN_ACTION
    if type(choice.seat) is not int:
        return FAULT_BAD_FIELD
    if type(choice) is NamePassAction and type(choice.chit_name) is not str:
        return FAULT_BAD_FIELD
    if choice.seat != seat:
        return FAULT_WRONG_SEAT
    action = to_engine_action(state, choice)
    if action is None:
        return FAULT_ILLEGAL
    if type(action) not in _ENGINE_ACTION_TYPES or action.seat != seat:
        raise RunnerError("the translation of a validated agent action is not an engine action")
    return action


def _decide(state: Any, seat: int, agent: Agent) -> Any:
    """Ask `agent` once for `seat`; return an engine action or a `FAULT_*` string."""
    observation = observe(state, seat)
    legal = legal_actions_for(state, seat)
    if not legal:
        raise RunnerError(f"seat {seat} has no legal action at its decision point")
    try:
        choice = agent.choose_action(observation, legal)
    except Exception:  # an agent's own failure; nothing about it is recorded or forwarded
        return FAULT_EXCEPTION
    return _validate_choice(state, seat, choice)


def _is_fault(decision: object) -> bool:
    return isinstance(decision, str)


# --- the game loop --------------------------------------------------------------------------


def run_game(
    config: SimulationConfig,
    game_index: int,
    *,
    agent_factory: Callable[[AgentSpec], Agent] = build_agent,
    recorder: Any = None,
) -> GameResult:
    """Play game `game_index` of the batch described by `config`.

    The same ``(config, game_index, agent_factory)`` always gives an equal result.
    Agents are built fresh for this game from the seated lineup. Raises
    `SimulationConfigError` for an invalid `config`/`game_index` or an agent that
    cannot be built, and `RunnerError` for a runner/engine failure. `recorder` is the
    optional host-side observer described in the module docstring.
    """
    return _run_game(config, game_index, agent_factory, new_game, recorder)


def _run_game(
    config: SimulationConfig,
    game_index: int,
    agent_factory: Callable[[AgentSpec], Agent],
    start: Callable[[GameConfig], Accepted],
    recorder: Any = None,
) -> GameResult:
    """The runner core. `start(game_config)` returns the opening `Accepted`; tests pass
    a function that starts from a crafted deal. `run_game` passes `new_game`."""
    if not isinstance(config, SimulationConfig):
        raise SimulationConfigError(f"config must be a SimulationConfig, got {type(config).__name__}")
    if type(game_index) is not int or not 0 <= game_index < config.game_count:
        raise SimulationConfigError(
            f"game_index must be an integer in [0, {config.game_count}), got {game_index!r}"
        )

    seed_value = game_seed(config.batch_seed, game_index, config.games_per_seed)
    game_config = config.game_config(seed_value)
    players = config.num_players
    lineup_indices = seat_assignment(players, game_index, config.rotate_seats)
    seated = [
        _seat_agent(agent_factory, spec)
        for spec in seated_lineup(config.lineup, game_index, config.rotate_seats)
    ]

    opening = start(game_config)
    if not isinstance(opening, Accepted):
        raise RunnerError("the opening state could not be created")
    state = opening.state
    if recorder is not None:
        recorder.opening(opening.events)

    max_restarts = config.max_draw_restarts_per_round
    max_actions = config.max_actions_per_attempt
    actions_total = 0
    attempt_actions = 0
    draw_restarts = 0
    timeouts = [0] * players
    faults = [0] * players
    rounds: list[RoundResult] = []
    queue: list[int] | None = None  # the seeded reaction queue of the win in progress
    faulted: set[int] = set()  # membership tests only; never iterated
    deferrals = 0
    status: str | None = None

    while status is None:
        if state.phase in (Phase.INITIAL_CLAIMS, Phase.PASSING):
            seat = state.decision_seat
            decision = _decide(state, seat, seated[seat].agent)
            if _is_fault(decision):
                faults[seat] += 1
                if recorder is not None:
                    recorder.fault(seat, decision, state.completed_rounds, state.attempt)
                decision = timeout_action(state)  # always issuable at a single decision point
                if decision is None:
                    raise RunnerError("no timeout is available at a single decision point")
        elif state.phase is Phase.WIN_DECLARED:
            if queue is None:  # first look at this win: draw the seeded order once
                queue = list(reaction_order_for_state(state))
                faulted = set()
                deferrals = 0
            pending = pending_reactors(state)
            candidates = [s for s in queue if s in pending and s not in faulted]
            if candidates:
                seat = candidates[0]
                decision = _decide(state, seat, seated[seat].agent)
                if _is_fault(decision):
                    faults[seat] += 1
                    if recorder is not None:
                        recorder.fault(seat, decision, state.completed_rounds, state.attempt)
                    faulted.add(seat)  # never asked again for this win (no retries)
                    queue.remove(seat)
                    queue.append(seat)  # the others keep their relative order
                    deferrals += 1
                    if deferrals > players:
                        raise RunnerError("the reaction deferral loop did not terminate")
                    continue  # no engine action, so nothing is counted
            elif len(pending) == 1:
                decision = timeout_action(state)  # the final-reaction timeout
                if decision is None:
                    raise RunnerError("the last pending reactor has no timeout available")
            else:
                status = STATUS_AGENT_FAULT_UNRESOLVABLE
                break
        else:
            raise RunnerError(f"the game is waiting for nobody (phase {state.phase.value})")

        before = state
        outcome = apply_action(state, decision)
        if isinstance(outcome, Rejected):
            # Built from validated input, so this is not an agent fault; say why, never what.
            raise RunnerError(f"the engine rejected a validated action ({outcome.reason.value})")
        state = outcome.state
        if recorder is not None:
            recorder.accepted(outcome.events)
        actions_total += 1
        attempt_actions += 1
        if state.phase is not Phase.WIN_DECLARED:
            queue = None  # the win (if any) ended with this action

        drawn = False
        dealt = False
        score_event = None
        closing = None
        for event in outcome.events:
            if isinstance(event, DecisionTimedOut):
                timeouts[event.seat] += 1
            elif isinstance(event, AttemptDrawn):
                draw_restarts += 1
                drawn = True
            elif isinstance(event, DealEvent):
                dealt = True
            elif isinstance(event, (ValidWinScored, FalseClaimPenalized)):
                score_event = event
            elif isinstance(event, RoundCompleted):
                closing = event
        if closing is not None:
            if score_event is None:
                raise RunnerError("a round completed without a scoring event")
            valid_win = closing.outcome == ROUND_OUTCOME_VALID_WIN
            rounds.append(
                RoundResult(
                    round_index=closing.completed_round,
                    outcome=closing.outcome,
                    initiator=before.initiator,
                    claimant=closing.claimant,
                    attempts=closing.attempt,
                    reaction_order=tuple(score_event.reaction_order) if valid_win else (),
                    score_changes=tuple(score_event.score_changes),
                )
            )
        if dealt:
            attempt_actions = 0

        # Stop checks, in the approved order: game over, draw cap, action cap.
        if state.phase is Phase.GAME_OVER:
            status = STATUS_COMPLETED
        elif drawn and state.attempt - 1 > max_restarts:
            status = STATUS_DRAW_CAP_REACHED
        elif not dealt and attempt_actions >= max_actions:
            status = STATUS_ACTION_CAP_REACHED

    completed = status == STATUS_COMPLETED
    scores = tuple(state.scores)
    ranks = final_ranks(status, scores)
    ties = tie_flags(ranks)
    records = tuple(rounds)
    seat_results = tuple(
        SeatResult(
            seat=seat,
            lineup_index=lineup_indices[seat],
            agent_type=seated[seat].agent_type,
            agent_version=seated[seat].agent_version,
            agent_config_json=seated[seat].config_json,
            score=scores[seat],
            rank=ranks[seat],
            tied=ties[seat],
            rounds_won=sum(r.outcome == ROUND_OUTCOME_VALID_WIN and r.claimant == seat for r in records),
            false_claims=sum(r.outcome == ROUND_OUTCOME_FALSE_CLAIM and r.claimant == seat for r in records),
            timeouts=timeouts[seat],
            agent_faults=faults[seat],
        )
        for seat in range(players)
    )
    return GameResult(
        game_index=game_index,
        game_seed=seed_value,
        status=status,
        num_players=players,
        num_rounds=config.num_rounds,
        completed_rounds=state.completed_rounds,
        stopped_attempt=None if completed else state.attempt,
        draw_restarts=draw_restarts,
        actions=actions_total,
        seats=seat_results,
        rounds=records,
        winning_seats=tuple(s for s in range(players) if ranks[s] == 1) if completed else (),
    )


__all__ = ["AGENT_TYPES", "RunnerError", "build_agent", "run_game"]
