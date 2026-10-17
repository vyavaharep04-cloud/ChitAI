"""Per-seat, name-based legal actions and their translation to engine actions (M7).

The engine addresses a pass by *physical* chit instance (`PassAction(seat,
Chit(name, copy))`, PROJECT_CONTEXT.md §9 Q10). Agents must never see copy
ids (§9 Q29), so the agent-facing pass is `NamePassAction(seat, chit_name)`.
`to_engine_action` turns an agent action back into the engine action the
authoritative engine understands.

Rule logic is not duplicated here: `legal_actions_for` filters and re-labels the
result of the engine's own `legal_actions`. Whether an action *exists* depends
on phase and position only (§3A.4), so the list never depends on hand contents.

Boundary (M7 versus M8): this module does not authenticate who is acting and
builds no agent-error framework. The M8 runner must (1) construct actions with
the agent's *own* seat, (2) accept an action only if it is `in
legal_actions_for(state, own_seat)`, (3) translate it with `to_engine_action`
and (4) report generic, payload-free errors to the agent when it is not.
`apply_action` trusts `action.seat`, and its rejection messages may echo chit
data, so engine `Rejected` messages must not be forwarded to agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..engine import (
    Action,
    ClaimAction,
    DeclineAction,
    GameState,
    PassAction,
    ReactAction,
    is_valid_seat,
    legal_actions,
)


@dataclass(frozen=True)
class NamePassAction:
    """Pass one chit of the given *name* to the next seat clockwise. Carries no
    physical copy id; the translation to a physical instance is internal."""

    seat: int
    chit_name: str


AgentAction = ClaimAction | DeclineAction | ReactAction | NamePassAction
"""Actions an agent may choose. Claim, decline and react carry only a seat, so
they are the engine's own classes; a timeout is never agent-selectable."""


def _check_seat(state: GameState, seat: object) -> None:
    if not is_valid_seat(state.config, seat):
        raise ValueError("seat must be an integer in [0, num_players)")


def legal_actions_for(state: GameState, seat: int) -> tuple[AgentAction, ...]:
    """The actions available to `seat` right now, by chit name.

    Order is deterministic and independent of hand order: claim, decline or
    react first, then one `NamePassAction` per distinct chit name held, sorted
    by name. Empty when `seat` has nothing to decide (not the decision point,
    not a pending reactor, a terminal or transient phase). Never contains an
    action for another seat or a timeout.
    """
    _check_seat(state, seat)
    claim_like: list[AgentAction] = []
    pass_names: set[str] = set()
    for action in legal_actions(state):
        if action.seat != seat:
            continue
        if isinstance(action, (ClaimAction, DeclineAction, ReactAction)):
            claim_like.append(action)
        elif isinstance(action, PassAction):
            pass_names.add(action.chit.name)
        # any other engine action kind (a timeout) is deliberately dropped
    return tuple(claim_like) + tuple(NamePassAction(seat, name) for name in sorted(pass_names))


def to_engine_action(state: GameState, action: object) -> Action | None:
    """Translate an agent action to the engine action it stands for, or None.

    Returns None unless `action` is exactly one of
    `legal_actions_for(state, action.seat)` (so wrong seat, wrong phase, an
    unheld name, a timeout or any unrecognized object all give None, with no
    message that could echo private data). A `NamePassAction` becomes a
    `PassAction` for the held chit of that name with the lowest copy index.
    Which copy is passed has no game effect (matching is by name) and copy ids
    are never visible to agents, so the choice cannot leak anything.
    """
    if not isinstance(action, (ClaimAction, DeclineAction, ReactAction, NamePassAction)):
        return None
    seat = action.seat
    if type(seat) is not int or not is_valid_seat(state.config, seat):
        return None
    if action not in legal_actions_for(state, seat):
        return None
    if isinstance(action, NamePassAction):
        held = [chit for chit in state.hands[seat] if chit.name == action.chit_name]
        return PassAction(seat, min(held, key=lambda chit: chit.copy))
    return action


def action_to_dict(action: AgentAction) -> dict[str, Any]:
    """A JSON-serializable form of an agent action (no copy id exists to show)."""
    if isinstance(action, NamePassAction):
        return {"type": "pass", "seat": action.seat, "chit_name": action.chit_name}
    if isinstance(action, ClaimAction):
        return {"type": "claim", "seat": action.seat}
    if isinstance(action, DeclineAction):
        return {"type": "decline", "seat": action.seat}
    if isinstance(action, ReactAction):
        return {"type": "react", "seat": action.seat}
    raise TypeError("not an agent-facing action")
