"""Events: sequencing, public/debug views, and hidden-information safety (§4, §6)."""

import json

import pytest

from chitai.engine import (
    CHIT_NAMES,
    ClaimAction,
    DeclineAction,
    Phase,
    apply_action,
)

from .helpers import all_names_json_free, make_config, start


def _full_game_events(config, matching, claim_seat=None):
    from chitai.engine import start_from_deal

    from .helpers import crafted_deal

    result = start_from_deal(config, crafted_deal(config, matching))
    state, events = result.state, list(result.events)
    while state.phase is Phase.INITIAL_CLAIMS:
        seat = state.decision_seat
        action = ClaimAction(seat) if seat == claim_seat else DeclineAction(seat)
        step = apply_action(state, action)
        state = step.state
        events.extend(step.events)
    return events


@pytest.mark.parametrize("claim_seat", [None, 0, 2])
def test_public_views_never_contain_chit_identities(claim_seat):
    events = _full_game_events(make_config(4), matching={0, 1, 2, 3}, claim_seat=claim_seat)
    assert events
    for event in events:
        assert all_names_json_free(event.public_view()), event.public_view()


def test_public_deal_view_has_no_hands_but_debug_view_does():
    (deal_event, *_) = _full_game_events(make_config(4), matching={0, 1, 2, 3})
    assert "hands" not in deal_event.public_view()
    debug = deal_event.debug_view()
    assert len(debug["hands"]) == 4 and all(len(h) == 4 for h in debug["hands"])
    assert not all_names_json_free(debug)  # debug view does contain identities


def test_claim_event_public_view_states_validity_without_revealing_hand():
    events = _full_game_events(make_config(4), matching={0, 1, 2, 3}, claim_seat=1)
    claim = events[-1]
    assert claim.public_view() == {
        "type": "initial_claim_made",
        "seq": claim.seq,
        "completed_round": 0,
        "attempt": 1,
        "seat": 1,
        "valid": True,
    }
    assert [c["name"] for c in claim.debug_view()["hand"]] == [CHIT_NAMES[1]] * 4


def test_false_claim_event_public_view_says_invalid():
    events = _full_game_events(make_config(4), matching=set(), claim_seat=0)
    claim = next(e for e in events if e.type == "initial_claim_made")
    assert claim.public_view()["valid"] is False


@pytest.mark.parametrize("view", ["public_view", "debug_view"])
def test_views_are_json_serializable(view):
    for event in _full_game_events(make_config(5), matching={0, 1, 2, 3, 4}, claim_seat=3):
        json.dumps(getattr(event, view)())


def test_events_carry_round_and_attempt():
    from chitai.engine import start_from_deal

    from .helpers import crafted_deal

    config = make_config(4, rounds=8)
    result = start_from_deal(config, crafted_deal(config, completed_round=5, attempt=3))
    step = apply_action(result.state, DeclineAction(result.state.decision_seat))
    for event in (*result.events, *step.events):
        assert (event.completed_round, event.attempt) == (5, 3)


def test_rejected_action_produces_no_events_or_sequence_change():
    state = start(make_config(4))
    from chitai.engine import Rejected

    result = apply_action(state, ClaimAction(3))
    assert isinstance(result, Rejected) and not hasattr(result, "events")
    assert state.next_seq == 1
