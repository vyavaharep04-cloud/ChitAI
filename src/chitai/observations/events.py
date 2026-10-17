"""Per-seat views of engine events (M7, PROJECT_CONTEXT.md §3A.8, §4, §6).

Every view starts from the event's `public_view()` and adds only what the seat
is entitled to learn. `debug_view()` is never used here: it is the private
record of the whole table and must not reach an agent or a client.

Private additions (the only ones):
* `DealEvent`: the seat's own dealt hand as `my_hand` (chit names, sorted).
* `ChitPassed`: `chit_name`, only for the sender and the receiver. A bystander
  sees who passed to whom, never the chit (§3A.8). A timeout-forced pass is
  shown to its sender and receiver the same way.

Deliberately *not* added (owner decisions, §9 Q6, Q30): claim events keep their
public form (claimant and validity, no hand) and there is no hand-reveal event;
`DecisionTimedOut` and `AttemptDrawn` stay public with their existing schema
and never reveal the forced or triggering chit, to anyone, including the
passer. `seat=None` gives the purely public stream (a spectator).

Views are JSON-serializable dicts. The global `seq` is kept, so streams for
different seats stay comparable.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..engine import ChitPassed, DealEvent, Event


def observe_event(event: Event, seat: int | None) -> dict[str, Any]:
    """The view of `event` for `seat` (None: public only).

    `seat` is supplied by the host. A non-integer or negative seat, or a seat
    that is not a player of a `DealEvent`'s game, raises `ValueError`.
    """
    view = dict(event.public_view())
    if seat is None:
        return view
    if type(seat) is not int or seat < 0:
        raise ValueError("seat must be None or a non-negative integer")
    if isinstance(event, DealEvent):
        if seat >= len(event.hands):
            raise ValueError("seat is not a player of this game")
        view["my_hand"] = sorted(chit.name for chit in event.hands[seat])
    elif isinstance(event, ChitPassed) and seat in (event.from_seat, event.to_seat):
        view["chit_name"] = event.chit.name
    return view


def observe_events(events: Iterable[Event], seat: int | None) -> tuple[dict[str, Any], ...]:
    """`observe_event` for each event, in order."""
    return tuple(observe_event(event, seat) for event in events)
