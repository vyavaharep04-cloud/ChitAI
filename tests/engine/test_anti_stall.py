"""Milestone 6: anti-stall draws (§3A.6; PROJECT_CONTEXT.md §9 question 4).

The tenth consecutive pass of one chit *name* by one player ends the attempt as a draw. The
tenth chit is not delivered. A draw redeals without consuming a completed round, keeps the
initiator and every score, increments the attempt number and clears all streaks.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace

import pytest

from chitai.engine import (
    CONSECUTIVE_PASS_LIMIT,
    Accepted,
    AttemptDrawn,
    Chit,
    ChitPassed,
    ClaimAction,
    ClaimMade,
    DealEvent,
    DecisionKind,
    DecisionTimedOut,
    DeclineAction,
    GameCompleted,
    InitialClaimsResolved,
    InvariantViolation,
    PassAction,
    Phase,
    ReactAction,
    Rejected,
    RejectionReason,
    RoundCompleted,
    TimeoutAction,
    apply_action,
    check_invariants,
    deal_round,
    new_game,
    pending_reactors,
    timeout_chit,
    update_pass_streaks,
)

from .helpers import (
    all_names_json_free,
    crafted_deal,
    deal_from_names,
    decline_to_passing,
    do_pass,
    hand_matches,
    make_config,
    start_deal,
    to_passing,
)

PLAYER_COUNTS = [4, 5, 6, 7, 8]
PASS_KINDS = ["first_pass", "receive", "return"]


def passing_state(config, kind):
    state = to_passing(config)
    if kind == "first_pass":
        return state
    state, _ = do_pass(state)
    if kind == "receive":
        return state
    for _ in range(config.num_players - 1):
        state, _ = do_pass(state, state.hands[state.decision_seat][-1])
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    return state


def forward_pass(state):
    """Pass on the chit that just arrived (the first pass: the first chit held). Everyone doing
    this circulates one physical chit, so every seat passes the same name every cycle."""
    hand = state.hands[state.decision_seat]
    chit = hand[0] if state.decision_kind is DecisionKind.INITIATOR_FIRST_PASS else hand[-1]
    return do_pass(state, chit)


def play_cycles(state, cycles):
    events = []
    for _ in range(cycles * state.config.num_players):
        state, step = forward_pass(state)
        events.extend(step)
    return state, events


def accepted(state, action):
    result = apply_action(state, action)
    assert isinstance(result, Accepted), result
    return result


def with_streaks(state, *entries):
    return replace(state, pass_streaks=tuple(entries))


def contiguous(events, first):
    return [e.seq for e in events] == list(range(first, first + len(events)))


# --- the pure streak function -------------------------------------------------------------------


def test_the_first_pass_starts_a_streak_of_one():
    assert update_pass_streaks((), 2, "Sun") == (((2, "Sun", 1),), 1)


def test_the_same_name_by_the_same_seat_extends_the_streak():
    streaks, count = update_pass_streaks(((2, "Sun", 4),), 2, "Sun")
    assert streaks == ((2, "Sun", 5),) and count == 5


def test_a_different_name_restarts_that_seats_streak_at_one():
    streaks, count = update_pass_streaks(((2, "Sun", 9),), 2, "Moon")
    assert streaks == ((2, "Moon", 1),) and count == 1
    # ... and the name that was reset starts from one again, not from the old count.
    streaks, count = update_pass_streaks(streaks, 2, "Sun")
    assert streaks == ((2, "Sun", 1),) and count == 1


def test_another_seats_pass_never_touches_a_streak():
    before = ((0, "Sun", 6), (3, "Moon", 2))
    after, count = update_pass_streaks(before, 1, "Sun")
    assert count == 1
    assert after == ((0, "Sun", 6), (1, "Sun", 1), (3, "Moon", 2))
    # A seat passing a *different* name never resets anyone else, either.
    after, _ = update_pass_streaks(before, 3, "Sun")
    assert (0, "Sun", 6) in after and (3, "Sun", 1) in after


def test_streaks_are_kept_sorted_by_seat_with_one_entry_per_seat():
    streaks = ()
    for seat in (3, 0, 2, 0, 3, 1):
        streaks, _ = update_pass_streaks(streaks, seat, "Sun")
    assert [s for s, _, _ in streaks] == [0, 1, 2, 3]
    assert dict((s, c) for s, _, c in streaks) == {0: 2, 1: 1, 2: 1, 3: 2}


def test_the_streak_function_does_not_modify_its_input():
    before = ((0, "Sun", 6),)
    update_pass_streaks(before, 0, "Sun")
    assert before == ((0, "Sun", 6),)


def test_the_limit_is_ten():
    assert CONSECUTIVE_PASS_LIMIT == 10


# --- streaks inside the engine ------------------------------------------------------------------


def test_streaks_are_empty_until_a_pass_is_made():
    config = make_config(4)
    state = start_deal(config, crafted_deal(config))
    assert state.pass_streaks == ()
    assert decline_to_passing(state).pass_streaks == ()


def test_a_pass_records_the_name_not_the_physical_copy():
    state = to_passing(make_config(4))
    chit = state.hands[state.decision_seat][0]
    seat = state.decision_seat
    state, _ = do_pass(state, chit)
    assert state.pass_streaks == ((seat, chit.name, 1),)


def test_each_seat_has_its_own_streak_and_other_passes_do_not_increment_it():
    config = make_config(4)
    state = to_passing(config)
    state, _ = forward_pass(state)  # seat 0 passes
    state, _ = forward_pass(state)  # seat 1 passes the same name
    state, _ = forward_pass(state)  # seat 2 passes the same name
    names = {name for _, name, _ in state.pass_streaks}
    assert len(names) == 1
    assert [(s, c) for s, _, c in state.pass_streaks] == [(0, 1), (1, 1), (2, 1)]


def test_a_different_name_resets_only_the_passing_seats_streak():
    config = make_config(4)
    state = passing_state(config, "receive")
    seat = state.decision_seat
    other_name = next(c for c in state.hands[seat] if c.name != state.hands[seat][-1].name)
    state = with_streaks(state, (0, "Sun", 4), (seat, other_name.name, 5))
    state, _ = do_pass(state, state.hands[seat][-1])  # pass the received chit: a different name
    streaks = dict((s, (n, c)) for s, n, c in state.pass_streaks)
    assert streaks[0] == ("Sun", 4)  # untouched
    assert streaks[seat][1] == 1  # restarted
    assert streaks[seat][0] != other_name.name


def test_a_forced_timeout_pass_counts_like_any_other_pass():
    state = passing_state(make_config(4, seed=3), "receive")
    chit = timeout_chit(state)
    seat = state.decision_seat
    state = with_streaks(state, (seat, chit.name, 4))
    after = accepted(state, TimeoutAction(seat)).state
    assert dict((s, (n, c)) for s, n, c in after.pass_streaks)[seat] == (chit.name, 5)


# --- the draw: exactly at the threshold ---------------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_nine_consecutive_same_name_passes_do_not_draw_and_the_tenth_does(n):
    config = make_config(n, seed=2)
    state, events = play_cycles(to_passing(config), 9)
    assert state.phase is Phase.PASSING and state.attempt == 1
    assert not any(isinstance(e, AttemptDrawn) for e in events)
    assert len(state.pass_streaks) == n  # every seat passed the circulating name nine times
    assert {c for _, _, c in state.pass_streaks} == {9}
    assert len({name for _, name, _ in state.pass_streaks}) == 1
    initiator = state.decision_seat
    assert initiator == state.initiator and state.decision_kind is DecisionKind.INITIATOR_RETURN

    before = state
    result = accepted(state, PassAction(initiator, state.hands[initiator][-1]))
    drawn, deal = result.events
    assert isinstance(drawn, AttemptDrawn) and isinstance(deal, DealEvent)
    assert drawn.seat == initiator and drawn.consecutive_passes == 10
    assert drawn.attempt == 1 and drawn.completed_round == 0
    assert not any(isinstance(e, ChitPassed) for e in result.events)  # the tenth chit is not delivered
    assert result.state.attempt == 2
    assert result.state.pass_streaks == ()
    check_invariants(result.state)
    assert before.pass_streaks != ()  # the input state was not modified


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_draw_redeals_the_next_attempt_with_everything_else_preserved(n):
    config = make_config(n, rounds=2 * n, seed=5)
    base = start_deal(config, crafted_deal(config, completed_round=1))
    scores = tuple(range(n, 0, -1))  # one valid-win round: the winner scores N, the rest N-1 ... 1
    base = replace(base, scores=scores)
    state = decline_to_passing(base)
    state = replace(state, pass_streaks=((state.decision_seat, state.hands[state.decision_seat][0].name, 9),))
    chit = state.hands[state.decision_seat][0]
    result = accepted(state, PassAction(state.decision_seat, chit))
    new = result.state
    assert new.completed_rounds == state.completed_rounds == 1  # no completed round consumed
    assert new.attempt == state.attempt + 1  # attempts are tracked separately
    assert new.initiator == state.initiator
    assert new.scores == state.scores  # no score added or removed
    assert new.hands == deal_round(config, 1, 2).hands  # the seeded redeal for (round, attempt + 1)
    assert new.hands != state.hands
    assert new.phase is Phase.INITIAL_CLAIMS
    assert new.decision_seat == new.initiator and new.decision_kind is DecisionKind.INITIAL_CLAIM
    assert new.initial_claims_resolved == 0
    assert new.winner is None and new.false_claimant is None and new.reaction_order == ()
    assert new.pass_streaks == ()
    assert new.next_seq == state.next_seq + 2
    assert contiguous(result.events, state.next_seq)
    assert not any(isinstance(e, (RoundCompleted, GameCompleted)) for e in result.events)


@pytest.mark.parametrize("round_index", [0, 1, 2, 3, 4, 5, 6, 7])
def test_the_initiator_is_unchanged_for_every_rotation_position(round_index):
    config = make_config(4, rounds=8, seed=1)
    state = decline_to_passing(start_deal(config, crafted_deal(config, completed_round=round_index)))
    seat = state.decision_seat
    assert seat == round_index % 4
    state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
    new = accepted(state, PassAction(seat, state.hands[seat][0])).state
    assert new.initiator == round_index % 4 == state.initiator
    assert new.completed_rounds == round_index


@pytest.mark.parametrize("kind", PASS_KINDS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_the_draw_applies_at_every_pass_decision_point(n, kind):
    state = passing_state(make_config(n), kind)
    seat = state.decision_seat
    chit = state.hands[seat][0]
    at_eight = accepted(with_streaks(state, (seat, chit.name, 8)), PassAction(seat, chit)).state
    assert at_eight.phase is Phase.PASSING and at_eight.attempt == 1  # nine: still no draw
    assert dict((s, c) for s, _, c in at_eight.pass_streaks)[seat] == 9
    result = accepted(with_streaks(state, (seat, chit.name, 9)), PassAction(seat, chit))
    assert isinstance(result.events[0], AttemptDrawn) and result.state.attempt == 2


def test_the_tenth_chit_is_not_delivered_so_its_receiver_never_gets_a_claim_opportunity():
    config = make_config(4)
    # Seat 1 holds three Sun; seat 0 holds the fourth. Delivering it would give seat 1 four of a name.
    deal = deal_from_names(
        config,
        [
            ["Sun", "Moon", "Moon", "Moon"],
            ["Sun", "Sun", "Sun", "Star"],
            ["Moon", "Star", "Star", "Star"],
            ["Cloud", "Cloud", "Cloud", "Cloud"],
        ],
    )
    state = decline_to_passing(start_deal(config, deal))
    sun = next(c for c in state.hands[0] if c.name == "Sun")

    delivered = accepted(with_streaks(state, (0, "Sun", 8)), PassAction(0, sun)).state  # control: the ninth
    assert delivered.decision_seat == 1 and len(delivered.hands[1]) == 5
    assert apply_action(delivered, ClaimAction(1)).state.phase is Phase.WIN_DECLARED  # a real winning claim

    drawn = accepted(with_streaks(state, (0, "Sun", 9)), PassAction(0, sun)).state  # the tenth
    assert drawn.phase is Phase.INITIAL_CLAIMS and drawn.winner is None
    assert drawn.attempt == 2 and all(len(h) == 4 for h in drawn.hands)
    assert apply_action(drawn, ClaimAction(1)).reason is RejectionReason.NOT_DECISION_POINT


@pytest.mark.parametrize("copy", [0, 1, 2, 3])
def test_a_pass_of_any_physical_copy_of_the_name_extends_the_streak(copy):
    config = make_config(4)
    deal = deal_from_names(
        config,
        [["Sun", "Sun", "Sun", "Sun"], ["Moon"] * 4, ["Star"] * 4, ["Cloud"] * 4],
    )
    state = decline_to_passing(start_deal(config, deal))
    state = with_streaks(state, (0, "Sun", 9))  # nine passes of the name, whichever copies they were
    chit = Chit("Sun", copy)
    assert chit in state.hands[0]
    result = accepted(state, PassAction(0, chit))
    assert isinstance(result.events[0], AttemptDrawn) and result.events[0].chit == chit


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_streaks_follow_the_name_across_different_physical_copies_organically(n):
    config = make_config(n, seed=8)
    deal = crafted_deal(config, matching={0})  # the initiator holds all four copies of one name
    state = decline_to_passing(start_deal(config, deal))
    initiator = state.decision_seat
    sent = []
    for cycle in range(9):
        # The initiator sends a different physical copy of its name each cycle; everyone else forwards.
        held = state.hands[initiator]
        target = Chit(deal.hands[initiator][0].name, cycle % 4)
        state, _ = do_pass(state, target if target in held else held[-1])
        sent.append(target)
        for _ in range(n - 1):
            state, _ = do_pass(state, state.hands[state.decision_seat][-1])
    assert len({c.copy for c in sent}) == 4  # all four physical copies were used
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    assert dict((s, c) for s, _, c in state.pass_streaks)[initiator] == 9
    result = accepted(state, PassAction(initiator, state.hands[initiator][0]))
    assert isinstance(result.events[0], AttemptDrawn) and result.events[0].consecutive_passes == 10


def test_the_streak_resets_when_the_name_changes_so_ten_total_is_not_enough():
    config = make_config(4)
    state = to_passing(config)
    seat = state.decision_seat
    first = state.hands[seat][0]
    other = next(c for c in state.hands[seat] if c.name != first.name)
    state = with_streaks(state, (seat, first.name, 9))
    state, _ = do_pass(state, other)  # a different name: the streak restarts at one
    assert dict((s, (n, c)) for s, n, c in state.pass_streaks)[seat] == (other.name, 1)


# --- the draw is a transition of the attempt only ----------------------------------------------


def test_streaks_restart_from_one_in_the_new_attempt():
    config = make_config(4, seed=6)
    state = passing_state(config, "first_pass")
    seat = state.decision_seat
    state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
    new = accepted(state, PassAction(seat, state.hands[seat][0])).state
    new = decline_to_passing(new)
    assert new.pass_streaks == ()
    new, _ = forward_pass(new)
    assert [c for _, _, c in new.pass_streaks] == [1]


def test_a_second_draw_gives_attempt_three_and_the_matching_seeded_deal():
    config = make_config(4, seed=12)
    state = to_passing(config)
    for expected_attempt in (2, 3):
        seat = state.decision_seat
        state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
        result = accepted(state, PassAction(seat, state.hands[seat][0]))
        assert result.state.attempt == expected_attempt
        assert result.events[1].attempt == expected_attempt
        assert result.state.hands == deal_round(config, 0, expected_attempt).hands
        state = decline_to_passing(result.state)
    assert state.completed_rounds == 0


def test_completed_rounds_and_attempts_are_tracked_separately_through_a_whole_round():
    config = make_config(4, rounds=4, seed=14)
    state = to_passing(config)
    for draw in range(2):  # two draws: attempt 3 of round 0
        seat = state.decision_seat
        state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
        state = accepted(state, PassAction(seat, state.hands[seat][0])).state
        if draw == 0:
            state = decline_to_passing(state)
    assert (state.completed_rounds, state.attempt) == (0, 3)
    assert state.phase is Phase.INITIAL_CLAIMS
    # The round now completes by a false claim; the next round starts at attempt 1.
    while hand_matches(state.hands[state.decision_seat]):
        state = accepted(state, DeclineAction(state.decision_seat)).state
    claimant = state.decision_seat
    result = accepted(state, ClaimAction(claimant))
    completed = [e for e in result.events if isinstance(e, RoundCompleted)][0]
    deal = result.events[-1]
    assert (completed.completed_round, completed.attempt, completed.rounds_completed) == (0, 3, 1)
    assert isinstance(deal, DealEvent) and (deal.completed_round, deal.attempt) == (1, 1)
    assert (result.state.completed_rounds, result.state.attempt, result.state.initiator) == (1, 1, 1)
    assert result.state.scores[claimant] == -3 and sum(result.state.scores) == -3


def test_scores_are_unchanged_by_a_draw_even_with_nonzero_totals():
    config = make_config(4, rounds=8, seed=3)
    base = start_deal(config, crafted_deal(config, completed_round=2))
    base = replace(base, scores=(4, 0, 2, 1))  # a valid win (4,3,2,1) then a false claim by seat 1 (-3)
    state = decline_to_passing(base)
    seat = state.decision_seat
    state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
    result = accepted(state, PassAction(seat, state.hands[seat][0]))
    assert result.state.scores == (4, 0, 2, 1)
    assert not [e for e in result.events if "score" in e.type]


def test_after_a_draw_a_normal_game_continues_and_every_invariant_holds():
    config = make_config(5, seed=17)
    state = to_passing(config)
    seat = state.decision_seat
    state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
    state = accepted(state, PassAction(seat, state.hands[seat][0])).state
    for _ in range(5):
        state = accepted(state, DeclineAction(state.decision_seat)).state
        check_invariants(state)
    assert state.phase is Phase.PASSING and state.attempt == 2
    state, _ = play_cycles(state, 2)
    check_invariants(state)


# --- a forced pass can end the attempt too -----------------------------------------------------


@pytest.mark.parametrize("kind", PASS_KINDS)
def test_a_timeout_forced_tenth_pass_draws_after_the_timeout_marker(kind):
    state = passing_state(make_config(5, seed=4), kind)
    seat = state.decision_seat
    chit = timeout_chit(state)
    state = with_streaks(state, (seat, chit.name, 9))
    result = accepted(state, TimeoutAction(seat))
    marker, drawn, deal = result.events
    assert isinstance(marker, DecisionTimedOut) and isinstance(drawn, AttemptDrawn) and isinstance(deal, DealEvent)
    assert drawn.chit == chit and drawn.seat == seat
    assert contiguous(result.events, state.next_seq)
    assert result.state.attempt == 2 and result.state.pass_streaks == ()
    assert result.state.next_seq == state.next_seq + 3
    check_invariants(result.state)


# --- events and privacy ------------------------------------------------------------------------


def test_the_draw_event_hides_the_chit_name_from_the_public_view():
    state = passing_state(make_config(4), "receive")
    seat = state.decision_seat
    chit = state.hands[seat][0]
    result = accepted(with_streaks(state, (seat, chit.name, 9)), PassAction(seat, chit))
    drawn, deal = result.events
    assert drawn.public_view() == {
        "type": "attempt_drawn",
        "seq": state.next_seq,
        "completed_round": 0,
        "attempt": 1,
        "seat": seat,
        "reason": "repeated_pass",
        "consecutive_passes": 10,
    }
    for event in result.events:
        assert all_names_json_free(event.public_view())
        json.dumps(event.debug_view())
    assert drawn.debug_view()["chit"] == {"name": chit.name, "copy": chit.copy}
    assert deal.public_view()["initiator"] == state.initiator and "hands" not in deal.public_view()


def test_draw_events_carry_the_attempt_that_ended_and_the_deal_carries_the_next():
    state = passing_state(make_config(4), "first_pass")
    seat = state.decision_seat
    state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
    drawn, deal = accepted(state, PassAction(seat, state.hands[seat][0])).events
    assert (drawn.completed_round, drawn.attempt) == (0, 1)
    assert (deal.completed_round, deal.attempt) == (0, 2)
    assert deal.seq == drawn.seq + 1


def test_a_game_with_a_draw_has_one_contiguous_event_sequence():
    config = make_config(4, seed=19)
    opening = new_game(config)
    state, log = opening.state, list(opening.events)
    for _ in range(4):
        step = accepted(state, DeclineAction(state.decision_seat))
        state, log = step.state, log + list(step.events)
    seat = state.decision_seat
    state = with_streaks(state, (seat, state.hands[seat][0].name, 9))
    step = accepted(state, PassAction(seat, state.hands[seat][0]))
    state, log = step.state, log + list(step.events)
    for _ in range(4):
        step = accepted(state, DeclineAction(state.decision_seat))
        state, log = step.state, log + list(step.events)
    assert [e.seq for e in log] == list(range(len(log)))
    assert state.next_seq == len(log)
    assert [type(e).__name__ for e in log if isinstance(e, (AttemptDrawn, DealEvent, InitialClaimsResolved))] == [
        "DealEvent", "InitialClaimsResolved", "AttemptDrawn", "DealEvent", "InitialClaimsResolved",
    ]


# --- rejected actions leave streaks and state untouched ----------------------------------------


@pytest.mark.parametrize("kind", PASS_KINDS)
def test_rejected_actions_never_mutate_streaks_or_state(kind):
    state = passing_state(make_config(5, seed=2), kind)
    seat = state.decision_seat
    other = (seat + 1) % 5
    state = with_streaks(state, (seat, state.hands[seat][0].name, 9), (other, "Moon", 4))
    snapshot = state
    unheld = next(c for c in [Chit(n, k) for n in ("Sun", "Moon", "Star", "Cloud", "Flame") for k in range(4)] if c not in state.hands[seat])
    attempts = [
        PassAction(other, state.hands[other][0]),  # not the decision seat
        PassAction(seat, unheld),  # a chit the seat does not hold
        PassAction(-1, unheld),
        DeclineAction(seat),  # no decline during passing
        ReactAction(seat),  # no reaction outside a win
        TimeoutAction(other),
        TimeoutAction(99),
    ]
    if state.decision_kind is DecisionKind.INITIATOR_FIRST_PASS:
        attempts.append(ClaimAction(seat))  # no claim opportunity at the first pass
    for action in attempts:
        result = apply_action(state, action)
        assert isinstance(result, Rejected), action
        assert state == snapshot and state.pass_streaks == snapshot.pass_streaks
    assert snapshot.next_seq == state.next_seq


def test_a_rejected_pass_does_not_advance_a_streak_that_is_about_to_draw():
    state = to_passing(make_config(4))
    seat = state.decision_seat
    name = state.hands[seat][0].name
    state = with_streaks(state, (seat, name, 9))
    bad = apply_action(state, PassAction(seat, Chit("Cloud", 9)))
    assert isinstance(bad, Rejected) and bad.reason is RejectionReason.CHIT_NOT_HELD
    assert state.pass_streaks == ((seat, name, 9),)  # still nine, not ten
    again = accepted(state, PassAction(seat, state.hands[seat][0]))
    assert isinstance(again.events[0], AttemptDrawn)  # the valid action still draws exactly once


# --- invariants ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "streaks",
    [
        ((0, "Sun", 0),),
        ((0, "Sun", 10),),
        ((0, "Sun", 11),),
        ((0, "Sun", -1),),
        ((0, "Sun", True),),
        ((4, "Sun", 1),),
        ((-1, "Sun", 1),),
        ((0, "Nope", 1),),
        ((1, "Sun", 1), (0, "Sun", 1)),
        ((1, "Sun", 1), (1, "Moon", 1)),
        ((0, "Sun"),),
        ((0, "Sun", 1, 2),),
        [(0, "Sun", 1)],
        ["bad"],
        None,
    ],
)
def test_corrupted_streaks_are_detected(streaks):
    state = to_passing(make_config(4))
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, pass_streaks=streaks))


def test_valid_streak_shapes_pass_the_invariant():
    state = to_passing(make_config(4))
    check_invariants(replace(state, pass_streaks=((0, "Sun", 1), (3, "Cloud", 9))))
    check_invariants(replace(state, pass_streaks=()))


def test_streaks_must_be_empty_while_initial_claims_are_open():
    config = make_config(4)
    state = start_deal(config, crafted_deal(config))
    with pytest.raises(InvariantViolation):
        check_invariants(replace(state, pass_streaks=((0, "Sun", 1),)))


def test_streaks_must_be_empty_in_a_finished_game():
    config = make_config(4, rounds=4)
    from .test_valid_win import win

    _, result = win(config, "initial", completed_round=3)
    final = result.state
    while final.phase is Phase.WIN_DECLARED:
        final = accepted(final, ReactAction(pending_reactors(final)[0])).state
    assert final.phase is Phase.GAME_OVER and final.pass_streaks == ()
    with pytest.raises(InvariantViolation):
        check_invariants(replace(final, pass_streaks=((0, "Sun", 1),)))


def test_a_win_in_the_final_round_after_passing_ends_the_game_with_cleared_streaks():
    from .test_valid_win import claim_ready

    config = make_config(4, rounds=4)
    ready = claim_ready(config, "return", completed_round=3)
    assert ready.pass_streaks != ()  # passes were made on the way to the claim
    final = accepted(ready, ClaimAction(ready.decision_seat)).state
    while final.phase is Phase.WIN_DECLARED:
        final = accepted(final, ReactAction(pending_reactors(final)[0])).state
    assert final.phase is Phase.GAME_OVER and final.pass_streaks == ()
    check_invariants(final)


def test_streaks_are_cleared_when_a_round_is_won_after_passing():
    from .test_valid_win import claim_ready

    config = make_config(4)
    ready = claim_ready(config, "return")
    assert ready.pass_streaks != ()  # passes were made on the way
    won = accepted(ready, ClaimAction(ready.decision_seat)).state
    while won.phase is Phase.WIN_DECLARED:
        won = accepted(won, ReactAction(pending_reactors(won)[0])).state
    assert won.pass_streaks == () and won.attempt == 1  # the next round starts clean


# --- seeded random play against an independent oracle --------------------------------------------


def oracle_streaks(expected):
    return tuple(sorted((seat, name, count) for seat, (name, count) in expected.items()))


def walk(seed, n, steps):
    """Biased random play: mostly forward the received chit, so draws are common; sometimes
    deviate or time out. Returns (final state, flat debug log, number of draws)."""
    rng = random.Random(seed)
    config = make_config(n, rounds=n, seed=seed)
    result = new_game(config)
    state, log = result.state, [e.debug_view() for e in result.events]
    expected, draws = {}, 0
    for _ in range(steps):
        if state.phase is Phase.GAME_OVER:
            break
        roll = rng.random()
        if state.phase is Phase.INITIAL_CLAIMS:
            action = ClaimAction(state.decision_seat) if roll < 0.01 else DeclineAction(state.decision_seat)
        elif state.phase is Phase.PASSING:
            seat = state.decision_seat
            hand = state.hands[seat]
            if roll < 0.03:
                action = TimeoutAction(seat)
            elif roll < 0.06:
                action = PassAction(seat, rng.choice(hand))
            else:
                action = PassAction(seat, hand[0] if state.decision_kind is DecisionKind.INITIATOR_FIRST_PASS else hand[-1])
        else:  # WIN_DECLARED
            pending = pending_reactors(state)
            if len(pending) == 1 and roll < 0.5:
                action = TimeoutAction(pending[0])
            else:
                action = ReactAction(rng.choice(pending))
        result = apply_action(state, action)
        assert isinstance(result, Accepted), (action, result)
        for event in result.events:
            if isinstance(event, (DealEvent, GameCompleted)):
                expected = {}
            elif isinstance(event, ChitPassed):
                name, count = expected.get(event.from_seat, (None, 0))
                expected[event.from_seat] = (event.chit.name, count + 1 if name == event.chit.name else 1)
                assert expected[event.from_seat][1] < CONSECUTIVE_PASS_LIMIT
            elif isinstance(event, AttemptDrawn):
                draws += 1
                name, count = expected[event.seat]
                assert (name, count + 1) == (event.chit.name, CONSECUTIVE_PASS_LIMIT)
                assert event.consecutive_passes == CONSECUTIVE_PASS_LIMIT
            elif isinstance(event, ClaimMade):
                pass
        assert result.state.pass_streaks == oracle_streaks(expected), (seed, n)
        assert [e.seq for e in result.events] == list(range(state.next_seq, result.state.next_seq))
        check_invariants(result.state)
        log.extend(e.debug_view() for e in result.events)
        state = result.state
    return state, log, draws


@pytest.mark.parametrize("n", [4, 6, 8])
def test_random_biased_play_matches_an_independent_streak_oracle(n):
    total_draws = 0
    for seed in range(8):
        _, _, draws = walk(seed, n, 1500)
        total_draws += draws
    assert total_draws > 0  # the walk really does exercise draws


def test_random_play_is_reproducible_for_the_same_seed():
    a = walk(5, 4, 800)
    b = walk(5, 4, 800)
    assert a[0] == b[0] and a[1] == b[1]
    assert walk(6, 4, 800)[1] != a[1]
