"""Per-seat event views (M7): public stream plus only legitimately observed private data."""

from __future__ import annotations

import json
import random
from dataclasses import replace

import pytest
from engine.helpers import do_pass, false_claim_ready

from chitai.engine import (
    AttemptDrawn,
    ChitPassed,
    ClaimAction,
    DealEvent,
    DecisionTimedOut,
    Event,
    PassAction,
    ReactAction,
    apply_action,
    new_game,
    timeout_action,
)
from chitai.observations import observe_event, observe_events

from .support import (
    PLAYER_COUNTS,
    SEED,
    all_values,
    seeded_config,
    to_passing,
    walk,
    winning_state,
    with_hidden_changes,
)


def _all_event_classes():
    seen, stack = [], [Event]
    while stack:
        cls = stack.pop()
        seen.append(cls)
        stack.extend(cls.__subclasses__())
    return seen


@pytest.fixture
def no_debug_view(monkeypatch):
    """Make every `debug_view` raise, so any use by the observation layer fails."""

    def boom(self):
        raise AssertionError("debug_view() must never be used for an agent-facing view")

    for cls in _all_event_classes():
        if "debug_view" in cls.__dict__:
            monkeypatch.setattr(cls, "debug_view", boom)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_deal_event_gives_each_seat_only_its_own_hand_by_name(n, no_debug_view):
    result = new_game(seeded_config(n))
    (deal,) = result.events
    public = deal.public_view()
    assert "hands" not in public and "my_hand" not in public
    for seat in range(n):
        view = observe_event(deal, seat)
        assert view["my_hand"] == sorted(c.name for c in deal.hands[seat])
        assert {k: v for k, v in view.items() if k != "my_hand"} == public
        assert "copy" not in json.dumps(view)
    assert observe_event(deal, None) == public


def test_deal_event_rejects_a_seat_outside_the_game():
    (deal,) = new_game(seeded_config(4)).events
    for bad in (4, 9, -1, True, "0", 1.0):
        with pytest.raises(ValueError):
            observe_event(deal, bad)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_passed_chit_is_visible_to_sender_and_receiver_only(n, no_debug_view):
    state = to_passing(seeded_config(n))
    sender = state.decision_seat
    chit = state.hands[sender][0]
    result = apply_action(state, PassAction(sender, chit))
    (event,) = result.events
    assert isinstance(event, ChitPassed)
    receiver = event.to_seat
    for seat in range(n):
        view = observe_event(event, seat)
        if seat in (sender, receiver):
            assert view["chit_name"] == chit.name  # positive control
        else:
            assert "chit_name" not in view
            assert view == event.public_view()
        assert "chit" not in view and "copy" not in json.dumps(view)
        assert view["from_seat"] == sender and view["to_seat"] == receiver
    assert observe_event(event, None) == event.public_view()


def test_bystander_view_is_identical_whatever_chit_was_passed():
    state = to_passing(seeded_config(5))
    sender = state.decision_seat
    bystander = (sender + 2) % 5
    views = set()
    for chit in state.hands[sender]:
        (event,) = apply_action(state, PassAction(sender, chit)).events
        views.add(json.dumps(observe_event(event, bystander), sort_keys=True))
    assert len(views) == 1


def test_claim_events_stay_public_and_never_reveal_a_hand(no_debug_view):
    config = seeded_config(4)
    cases = [
        apply_action(false_claim_ready(config, "initial"), ClaimAction(0)),
        apply_action(false_claim_ready(config, "receive"), ClaimAction(1)),
        apply_action(false_claim_ready(config, "return"), ClaimAction(0)),
        apply_action(winning_state(4), ReactAction(1)),
    ]
    claims = [e for r in cases[:3] for e in r.events if e.type in ("initial_claim_made", "claim_made")]
    assert len(claims) == 3
    for event in claims:
        for seat in (None, event.seat, (event.seat + 1) % 4):
            view = observe_event(event, seat)
            assert view == event.public_view()
            assert set(view) == {"type", "seq", "completed_round", "attempt", "seat", "valid"}
    for result in cases:  # no event of any kind carries a revealed hand or a hand-reveal event
        for event in result.events:
            assert "reveal" not in event.type
            for seat in range(4):
                assert "hand" not in observe_event(event, seat) or isinstance(event, DealEvent)


def test_valid_claim_is_public_as_valid_in_every_view():
    from chitai.engine import Deal, build_deck, start_from_deal

    config = seeded_config(4)
    deck = build_deck(4)
    hands = tuple(tuple(c for c in deck if c.name == deck[4 * s].name) for s in range(4))
    state = start_from_deal(config, Deal(0, 1, 0, hands)).state
    (claim, *_) = apply_action(state, ClaimAction(0)).events
    assert all(observe_event(claim, s)["valid"] is True for s in (None, 0, 1, 2, 3))


def test_timeout_marker_is_public_and_reveals_no_chit_even_to_the_forced_passer(no_debug_view):
    state = to_passing(seeded_config(4))
    host_timeout = timeout_action(state)
    result = apply_action(state, host_timeout)
    marker, passed = result.events
    assert isinstance(marker, DecisionTimedOut) and isinstance(passed, ChitPassed)
    for seat in range(4):
        assert observe_event(marker, seat) == marker.public_view()
        assert "chit_name" not in observe_event(marker, seat)
    assert observe_event(marker, None)["decision_kind"] == "initiator_first_pass"
    # the forced pass itself follows the ordinary pass rule: sender and receiver learn the chit
    assert observe_event(passed, passed.from_seat)["chit_name"] == passed.chit.name
    assert observe_event(passed, passed.to_seat)["chit_name"] == passed.chit.name
    assert "chit_name" not in observe_event(passed, (passed.to_seat + 1) % 4)


def test_initial_claim_and_final_reaction_timeouts_are_public_markers():
    state = new_game(seeded_config(4)).state
    marker = apply_action(state, timeout_action(state)).events[0]
    assert marker.public_view()["decision_kind"] == "initial_claim"
    assert all(observe_event(marker, s) == marker.public_view() for s in range(4))
    won = winning_state(4)
    pending = [s for s in range(4) if s != won.winner]
    won = apply_action(won, ReactAction(pending[0])).state
    won = apply_action(won, ReactAction(pending[1])).state
    marker = apply_action(won, timeout_action(won)).events[0]
    assert observe_event(marker, 0)["decision_kind"] == "final_reaction"
    assert observe_event(marker, 0) == marker.public_view()


def _drawn(n=4):
    state = to_passing(seeded_config(n))
    seat = state.decision_seat
    chit = state.hands[seat][0]
    nine = replace(state, pass_streaks=((seat, chit.name, 9),))
    return seat, chit, apply_action(nine, PassAction(seat, chit))


def test_draw_event_is_public_and_the_tenth_chit_is_never_revealed(no_debug_view):
    seat, chit, result = _drawn()
    drawn, deal = result.events
    assert isinstance(drawn, AttemptDrawn) and isinstance(deal, DealEvent)
    assert not any(isinstance(e, ChitPassed) for e in result.events)
    for viewer in (None, 0, 1, 2, 3):
        view = observe_event(drawn, viewer)
        assert view == drawn.public_view()
        assert set(view) == {"type", "seq", "completed_round", "attempt", "seat", "reason", "consecutive_passes"}
        assert chit.name not in json.dumps(view)  # not even the passer (seat) learns it from the event
    assert observe_event(drawn, seat) == observe_event(drawn, (seat + 1) % 4)
    # the redeal gives each seat its new hand only
    assert observe_event(deal, seat)["my_hand"] == sorted(c.name for c in deal.hands[seat])
    assert deal.attempt == 2 and observe_event(deal, None) == deal.public_view()


def test_public_stream_equals_public_views_and_keeps_global_sequence():
    rng = random.Random(1)
    config = seeded_config(5)
    state = new_game(config).state
    events = list(new_game(config).events)
    for _ in range(12):
        seat = state.decision_seat
        from chitai.engine import DeclineAction

        action = DeclineAction(seat) if state.phase.value == "initial_claims" else PassAction(seat, rng.choice(state.hands[seat]))
        result = apply_action(state, action)
        state = result.state
        events.extend(result.events)
    public = observe_events(events, None)
    assert list(public) == [e.public_view() for e in events]
    for seat in range(5):
        per_seat = observe_events(events, seat)
        assert [v["seq"] for v in per_seat] == [e.seq for e in events]
        for view, event in zip(per_seat, events):
            extra = set(view) - set(event.public_view())
            assert extra <= {"my_hand", "chit_name"}
            assert all(view[k] == v for k, v in event.public_view().items())


def test_views_are_json_serializable_primitives_without_seed_or_copy_ids():
    rng = random.Random(2)
    events = list(new_game(seeded_config(6)).events)
    state = new_game(seeded_config(6)).state
    for _ in range(14):
        seat = state.decision_seat
        from chitai.engine import DeclineAction

        action = DeclineAction(seat) if state.phase.value == "initial_claims" else PassAction(seat, rng.choice(state.hands[seat]))
        result = apply_action(state, action)
        state = result.state
        events.extend(result.events)
    for seat in (None, 0, 3, 5):
        for view in observe_events(events, seat):
            assert json.loads(json.dumps(view)) == view
            text = json.dumps(view)
            assert str(SEED) not in text and "copy" not in text and "Chit(" not in text
            assert all(leaf is None or type(leaf) in (str, int, float, bool) for leaf in all_values(view))


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_hidden_twins_produce_identical_event_streams_for_a_bystander(n):
    """Walk a game; at every step compare what the observer sees in the real game
    and in a hidden twin of the same state. Equal unless the observer is the
    sender or receiver of that pass."""
    rng = random.Random(100 + n)
    checked_bystander = checked_party = 0
    for observer in range(n):
        previous = None
        for state in walk(seeded_config(n), rng, 30):
            if previous is not None:
                previous_state, action = previous
                twin_state, changed = with_hidden_changes(previous_state, observer, rng)
                seat = previous_state.decision_seat
                real = apply_action(previous_state, action)
                if previous_state.phase.value == "initial_claims":
                    twin = apply_action(twin_state, action)
                else:
                    index = previous_state.hands[seat].index(action.chit)
                    twin = apply_action(twin_state, PassAction(seat, twin_state.hands[seat][index]))
                if any(isinstance(e, AttemptDrawn) for e in real.events + twin.events):
                    previous = None
                    continue
                v_real = observe_events(real.events, observer)
                v_twin = observe_events(twin.events, observer)
                party = any(
                    isinstance(e, ChitPassed) and observer in (e.from_seat, e.to_seat) for e in real.events
                )
                if party:
                    checked_party += 1
                    assert all("chit_name" in v for v in v_real if v["type"] == "chit_passed")
                else:
                    checked_bystander += 1
                    assert v_real == v_twin
            if state.phase.value in ("initial_claims", "passing"):
                seat = state.decision_seat
                if state.phase.value == "initial_claims":
                    from chitai.engine import DeclineAction

                    previous = (state, DeclineAction(seat))
                else:
                    previous = (state, PassAction(seat, rng.choice(state.hands[seat])))
            else:
                previous = None
    assert checked_bystander > 0 and checked_party > 0


def test_a_party_can_see_a_difference_that_a_bystander_cannot_positive_control():
    state = to_passing(seeded_config(4))
    sender = state.decision_seat
    names = sorted({c.name for c in state.hands[sender]})
    assert len(names) >= 2
    views = {}
    for name in names[:2]:
        (event,) = do_pass(state, name=name)[1]
        views[name] = (observe_event(event, sender), observe_event(event, (sender + 2) % 4))
    a, b = views[names[0]], views[names[1]]
    assert a[0] != b[0]  # the sender sees which chit
    assert a[1] == b[1]  # a bystander cannot tell
