"""Milestone 6: host-issued timeouts (§3A.3, §3A.5, §3A.7).

The engine has no clock. A timeout is a `TimeoutAction(seat)` the host issues when its
own timer expires; these tests never sleep and never look at elapsed time.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import replace

import pytest

from chitai.engine import (
    DEAL,
    TIMEOUT,
    TIMEOUT_KIND_FINAL_REACTION,
    Accepted,
    ClaimAction,
    ConfigError,
    DealEvent,
    DecisionKind,
    DecisionTimedOut,
    DeclineAction,
    GameCompleted,
    GameConfig,
    InitialClaimDeclined,
    InitialClaimsResolved,
    PassAction,
    Phase,
    PlayerReacted,
    ReactAction,
    Rejected,
    RejectionReason,
    RoundCompleted,
    TimeoutAction,
    ValidWinScored,
    ChitPassed,
    apply_action,
    check_invariants,
    derive_seed,
    make_rng,
    legal_actions,
    new_game,
    pending_reactors,
    timeout_action,
    timeout_chit,
)

from .helpers import (
    all_names_json_free,
    deal_from_names,
    decline_to_passing,
    do_pass,
    make_config,
    start,
    start_deal,
    to_passing,
)
from .test_valid_win import claim_ready, win

PLAYER_COUNTS = [4, 5, 6, 7, 8]
PASS_KINDS = ["first_pass", "receive", "return"]


def timeout(state, seat=None):
    seat = state.decision_seat if seat is None else seat
    result = apply_action(state, TimeoutAction(seat))
    assert isinstance(result, Accepted), result
    return result


def without_seq(view: dict) -> dict:
    return {k: v for k, v in view.items() if k != "seq"}


def passing_state(config, kind):
    """A PASSING state at the requested decision kind (no claim is made)."""
    state = to_passing(config)
    if kind == "first_pass":
        return state
    state, _ = do_pass(state)
    if kind == "receive":
        return state
    assert kind == "return"
    for _ in range(config.num_players - 1):
        state, _ = do_pass(state, state.hands[state.decision_seat][-1])
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    return state


# --- configuration -----------------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [0.001, 0.5, 1, 7.5, 14.999, 15, 15.0])
def test_pass_timeouts_up_to_fifteen_seconds_are_accepted(seconds):
    assert make_config(seed=1).pass_timeout_seconds == 15.0
    config = GameConfig(num_players=4, num_rounds=4, seed=1, pass_timeout_seconds=seconds)
    assert config.pass_timeout_seconds == seconds


@pytest.mark.parametrize(
    "seconds", [0, 0.0, -1, -0.001, 15.0001, 16, 1e9, math.inf, -math.inf, math.nan, True, False, "5", None]
)
def test_invalid_pass_timeouts_are_rejected(seconds):
    with pytest.raises(ConfigError):
        GameConfig(num_players=4, num_rounds=4, seed=1, pass_timeout_seconds=seconds)


def test_the_timeout_duration_never_changes_engine_behaviour():
    # The engine has no clock, so the configured duration is the host's timer value only.
    fast = GameConfig(num_players=4, num_rounds=4, seed=3, pass_timeout_seconds=0.25)
    slow = GameConfig(num_players=4, num_rounds=4, seed=3, pass_timeout_seconds=15)
    a, b = to_passing(fast), to_passing(slow)
    assert timeout_chit(a) == timeout_chit(b)


# --- availability -------------------------------------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_timeout_is_available_at_every_single_decision_point(n):
    state = start(make_config(n))
    for _ in range(n):  # every initial opportunity
        assert timeout_action(state) == TimeoutAction(state.decision_seat)
        state = apply_action(state, DeclineAction(state.decision_seat)).state
    for kind in PASS_KINDS:
        passing = passing_state(make_config(n), kind)
        assert timeout_action(passing) == TimeoutAction(passing.decision_seat)


def test_no_timeout_is_available_after_the_game_is_over():
    config = make_config(4, rounds=4)
    _, result = win(config, "initial", completed_round=3)
    final = result.state
    while final.phase is Phase.WIN_DECLARED:
        final = apply_action(final, ReactAction(pending_reactors(final)[0])).state
    assert final.phase is Phase.GAME_OVER
    assert timeout_action(final) is None
    rejected = apply_action(final, TimeoutAction(0))
    assert isinstance(rejected, Rejected) and rejected.reason is RejectionReason.PHASE_NOT_ACCEPTING


def test_legal_actions_are_unchanged_by_timeouts():
    state = passing_state(make_config(4), "receive")
    assert not any(isinstance(a, TimeoutAction) for a in legal_actions(state))
    initial = start(make_config(4))
    assert legal_actions(initial) == (ClaimAction(0), DeclineAction(0))


# --- initial claim timeout --------------------------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_an_initial_claim_timeout_resolves_exactly_like_a_decline(n):
    state = start(make_config(n))
    declined = apply_action(state, DeclineAction(state.decision_seat))
    timed_out = timeout(state)
    # The only differences are the marker event and the sequence number it consumes.
    assert timed_out.state == replace(declined.state, next_seq=declined.state.next_seq + 1)
    marker, *rest = timed_out.events
    assert isinstance(marker, DecisionTimedOut)
    assert marker.seat == state.decision_seat
    assert marker.decision_kind == DecisionKind.INITIAL_CLAIM.value
    assert marker.seq == state.next_seq
    assert [without_seq(e.debug_view()) for e in rest] == [
        without_seq(e.debug_view()) for e in declined.events
    ]
    assert isinstance(rest[0], InitialClaimDeclined)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_timing_out_every_initial_opportunity_starts_passing_without_a_claim(n):
    config = make_config(n)
    state = start(config)
    seats = []
    events = []
    for _ in range(n):
        seats.append(state.decision_seat)
        result = timeout(state)
        events.extend(result.events)
        state = result.state
    assert seats == [(state.initiator + i) % n for i in range(n)]  # initiator first, clockwise
    assert state.phase is Phase.PASSING
    assert state.decision_kind is DecisionKind.INITIATOR_FIRST_PASS
    assert state.decision_seat == state.initiator
    assert state.scores == (0,) * n and state.winner is None and state.false_claimant is None
    assert any(isinstance(e, InitialClaimsResolved) for e in events)
    assert [e.seq for e in events] == list(range(1, 1 + len(events)))


def test_a_timeout_never_claims_even_when_the_hand_matches():
    config = make_config(4)
    state = start(config, matching={0, 1, 2, 3})  # every seat holds four of a name
    for _ in range(4):
        result = timeout(state)
        state = result.state
        assert not any(type(e).__name__.endswith("ClaimMade") for e in result.events)
    assert state.phase is Phase.PASSING and state.winner is None


def test_an_initial_timeout_for_the_wrong_seat_is_rejected_without_change():
    state = start(make_config(4))
    wrong = (state.decision_seat + 1) % 4
    result = apply_action(state, TimeoutAction(wrong))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.NOT_DECISION_POINT
    assert state == start(make_config(4))


# --- forced passes ------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", PASS_KINDS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_forced_pass_is_a_legal_physical_chit_from_the_decision_hand(n, kind):
    state = passing_state(make_config(n), kind)
    seat = state.decision_seat
    expected_size = 5 if kind == "receive" else 4
    assert len(state.hands[seat]) == expected_size
    chosen = timeout_chit(state)
    assert chosen in state.hands[seat]
    result = timeout(state)
    marker, passed = result.events
    assert isinstance(marker, DecisionTimedOut) and isinstance(passed, ChitPassed)
    assert marker.decision_kind == state.decision_kind.value
    assert passed.chit == chosen and passed.from_seat == seat
    assert chosen not in result.state.hands[seat]
    assert chosen in result.state.hands[(seat + 1) % n]
    check_invariants(result.state)


@pytest.mark.parametrize("kind", PASS_KINDS)
def test_a_forced_pass_is_the_ordinary_pass_of_the_chosen_chit(kind):
    state = passing_state(make_config(5), kind)
    chosen = timeout_chit(state)
    ordinary = apply_action(state, PassAction(state.decision_seat, chosen))
    forced = timeout(state)
    assert forced.state == replace(ordinary.state, next_seq=ordinary.state.next_seq + 1)
    assert [without_seq(e.debug_view()) for e in forced.events[1:]] == [
        without_seq(e.debug_view()) for e in ordinary.events
    ]


def test_a_forced_pass_never_claims_even_when_holding_a_winning_hand():
    config = make_config(4)
    ready = claim_ready(config, "receive")  # the receiver holds four of a name plus one
    assert len(ready.hands[ready.decision_seat]) == 5
    result = timeout(ready)
    assert result.state.phase is Phase.PASSING
    assert not any(type(e).__name__.endswith("ClaimMade") for e in result.events)
    assert result.state.winner is None


@pytest.mark.parametrize("kind", PASS_KINDS)
def test_the_forced_choice_is_deterministic_for_the_same_seed_and_state(kind):
    first = passing_state(make_config(6, seed=11), kind)
    second = passing_state(make_config(6, seed=11), kind)
    assert first == second
    assert timeout_chit(first) == timeout_chit(second) == timeout_chit(first)
    assert timeout(first).events == timeout(second).events


def test_the_forced_choice_depends_on_the_seed():
    choices = {timeout_chit(passing_state(make_config(4, seed=s), "receive")) for s in range(40)}
    assert len(choices) > 1


def test_the_forced_choice_does_not_depend_on_the_order_hand_chits_arrived_in():
    state = passing_state(make_config(5, seed=2), "receive")
    seat = state.decision_seat
    hands = list(state.hands)
    hands[seat] = tuple(reversed(hands[seat]))
    shuffled = replace(state, hands=tuple(hands))
    assert timeout_chit(shuffled) == timeout_chit(state)


def test_the_forced_choice_is_uniform_over_the_five_physical_chits_of_a_receiver():
    trials = 2000
    counts = Counter()
    for seed in range(trials):
        state = passing_state(make_config(4, seed=seed), "receive")
        # Same crafted hands for every seed: only the seed varies, so only the stream differs.
        counts[state.hands[state.decision_seat].index(timeout_chit(state))] += 1
    assert len(counts) == 5
    for position, seen in counts.items():
        assert 0.15 * trials < seen < 0.25 * trials, (position, counts)


def test_the_forced_choice_is_uniform_over_the_four_chits_of_the_initiator():
    trials = 2000
    counts = Counter()
    for seed in range(trials):
        state = passing_state(make_config(4, seed=seed), "first_pass")
        counts[timeout_chit(state)] += 1
    assert len(counts) == 4
    for seen in counts.values():
        assert 0.19 * trials < seen < 0.31 * trials, counts


def test_two_copies_of_one_name_are_separate_equally_likely_choices():
    # Seat 0 (the initiator) holds two Sun and two Moon: the uniform choice is over the four
    # physical instances, so each copy is chosen about a quarter of the time.
    trials = 2000
    counts = Counter()
    for seed in range(trials):
        config = make_config(4, seed=seed)
        deal = deal_from_names(
            config,
            [
                ["Sun", "Sun", "Moon", "Moon"],
                ["Sun", "Sun", "Star", "Star"],
                ["Moon", "Moon", "Cloud", "Cloud"],
                ["Star", "Star", "Cloud", "Cloud"],
            ],
        )
        state = decline_to_passing(start_deal(config, deal))
        counts[timeout_chit(state)] += 1
    assert set(counts) == set(state.hands[0])
    for seen in counts.values():
        assert 0.19 * trials < seen < 0.31 * trials, counts


@pytest.mark.parametrize("kind", PASS_KINDS)
def test_the_forced_choice_is_drawn_from_the_documented_timeout_stream(kind):
    # Pinned derivation: SHA-256 stream (master seed, "timeout", completed round, attempt, next seq)
    # over the sorted hand. Python's built-in hash() is never involved.
    state = passing_state(make_config(5, seed=77), kind)
    rng = make_rng(77, TIMEOUT, state.completed_rounds, state.attempt, state.next_seq)
    assert timeout_chit(state) == rng.choice(sorted(state.hands[state.decision_seat]))
    assert TIMEOUT == "timeout" and TIMEOUT != DEAL


def test_a_timeout_uses_its_own_stream_and_is_a_pure_function_of_the_state():
    assert derive_seed(5, TIMEOUT, 0, 1, 7) != derive_seed(5, DEAL, 0, 1)
    config = make_config(4, seed=9)
    state = passing_state(config, "receive")
    other = passing_state(make_config(4, seed=10), "first_pass")
    expected = timeout_chit(state)
    timeout_chit(other)  # interleaved calls on other states change nothing
    timeout(other)
    assert timeout_chit(state) == expected
    assert timeout(state).events == timeout(state).events


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_forced_passes_follow_the_clockwise_cycle_and_keep_every_invariant(n):
    state = to_passing(make_config(n, seed=4))
    receivers = []
    for _ in range(3 * n):
        before = state.decision_seat
        result = timeout(state)
        state = result.state
        check_invariants(state)
        if state.phase is not Phase.PASSING:
            break
        receivers.append((before, state.decision_seat))
    assert all(to == (frm + 1) % n for frm, to in receivers)


def test_forced_pass_events_keep_chit_names_private_and_sequence_contiguous():
    state = passing_state(make_config(5, seed=6), "receive")
    result = timeout(state)
    assert [e.seq for e in result.events] == [state.next_seq, state.next_seq + 1]
    assert result.state.next_seq == state.next_seq + 2
    for event in result.events:
        assert all_names_json_free(event.public_view())
        json.dumps(event.debug_view())
    marker = result.events[0]
    assert marker.public_view() == {
        "type": "decision_timed_out",
        "seq": state.next_seq,
        "completed_round": 0,
        "attempt": 1,
        "seat": state.decision_seat,
        "decision_kind": "non_initiator_receive",
    }
    # The chit identity appears only in the private pass event.
    assert result.events[1].debug_view()["chit"]["name"]
    assert "chit" not in result.events[1].public_view()


def test_a_forced_pass_by_the_wrong_seat_is_rejected_without_change():
    state = passing_state(make_config(4), "receive")
    for seat in range(4):
        if seat != state.decision_seat:
            result = apply_action(state, TimeoutAction(seat))
            assert isinstance(result, Rejected) and result.reason is RejectionReason.NOT_DECISION_POINT


@pytest.mark.parametrize("bad", [-1, 4, 99, True, False, 1.0, "0", None])
def test_a_timeout_with_an_invalid_seat_is_rejected_without_change(bad):
    for state in (start(make_config(4)), passing_state(make_config(4), "receive")):
        before = state
        result = apply_action(state, TimeoutAction(bad))
        assert isinstance(result, Rejected) and result.reason is RejectionReason.INVALID_SEAT
        assert state == before


def test_timeout_chit_exists_only_at_a_passing_decision():
    with pytest.raises(ValueError):
        timeout_chit(start(make_config(4)))


def test_rejected_timeouts_do_not_consume_sequence_numbers_or_streaks():
    state = passing_state(make_config(4), "receive")
    state = replace(state, pass_streaks=((0, state.hands[0][0].name, 3),))
    wrong = (state.decision_seat + 1) % 4
    result = apply_action(state, TimeoutAction(wrong))
    assert isinstance(result, Rejected)
    assert state.pass_streaks == ((0, state.hands[0][0].name, 3),)
    accepted = timeout(state)
    assert accepted.events[0].seq == state.next_seq


# --- final reaction timeout ---------------------------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_no_reaction_timeout_applies_while_several_non_winners_remain(n):
    config = make_config(n)
    ready, result = win(config, "initial")
    state = result.state
    reactors = list(pending_reactors(state))
    while len(reactors) > 1:
        assert timeout_action(state) is None
        for seat in range(n):
            rejected = apply_action(state, TimeoutAction(seat))
            assert isinstance(rejected, Rejected)
            assert rejected.reason is RejectionReason.TIMEOUT_NOT_AVAILABLE
        snapshot = state
        state = apply_action(state, ReactAction(reactors.pop(0))).state
        assert snapshot.reaction_order == state.reaction_order[:-1]
    assert timeout_action(state) == TimeoutAction(reactors[0])


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_the_rejection_while_several_remain_changes_nothing(n):
    _, result = win(make_config(n), "receive")
    state = result.state
    snapshot = state
    rejected = apply_action(state, TimeoutAction(pending_reactors(state)[0]))
    assert isinstance(rejected, Rejected)
    assert rejected.reason is RejectionReason.TIMEOUT_NOT_AVAILABLE
    assert state == snapshot and state.reaction_order == ()


@pytest.mark.parametrize("position", ["initial", "receive", "return"])
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_the_last_reaction_timeout_resolves_exactly_like_an_explicit_reaction(n, position):
    config = make_config(n)
    _, result = win(config, position)
    state = result.state
    for seat in pending_reactors(state)[:-1]:
        state = apply_action(state, ReactAction(seat)).state
    (last,) = pending_reactors(state)
    explicit = apply_action(state, ReactAction(last))
    timed = timeout(state, last)
    assert timed.state == replace(explicit.state, next_seq=explicit.state.next_seq + 1)
    marker, *rest = timed.events
    assert isinstance(marker, DecisionTimedOut)
    assert marker.decision_kind == TIMEOUT_KIND_FINAL_REACTION and marker.seat == last
    assert [without_seq(e.debug_view()) for e in rest] == [
        without_seq(e.debug_view()) for e in explicit.events
    ]
    types = [type(e) for e in timed.events]
    assert types[:4] == [DecisionTimedOut, PlayerReacted, ValidWinScored, RoundCompleted]
    assert types[4] in (DealEvent, GameCompleted)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_timed_out_last_reaction_scores_one_and_leaves_scoring_unchanged(n):
    config = make_config(n)
    _, result = win(config, "initial")
    state = result.state
    order = list(pending_reactors(state))
    for seat in order[:-1]:
        state = apply_action(state, ReactAction(seat)).state
    scored = [e for e in timeout(state, order[-1]).events if isinstance(e, ValidWinScored)][0]
    assert scored.reaction_order == tuple(order)
    assert scored.score_changes[order[-1]] == 1
    assert scored.score_changes[state.winner] == n
    assert sum(scored.score_changes) == n * (n + 1) // 2


def test_a_timeout_cannot_invent_or_reorder_reactions():
    _, result = win(make_config(4), "initial")
    state = result.state
    first, second, third = pending_reactors(state)
    state = apply_action(state, ReactAction(third)).state
    state = apply_action(state, ReactAction(first)).state
    # `second` is last, so only it may time out; the others have already reacted.
    assert apply_action(state, TimeoutAction(first)).reason is RejectionReason.ALREADY_REACTED
    assert apply_action(state, TimeoutAction(third)).reason is RejectionReason.ALREADY_REACTED
    assert apply_action(state, TimeoutAction(state.winner)).reason is RejectionReason.WINNER_CANNOT_REACT
    assert state.reaction_order == (third, first)
    final = timeout(state, second)
    scored = [e for e in final.events if isinstance(e, ValidWinScored)][0]
    assert scored.reaction_order == (third, first, second)


def test_timeouts_are_rejected_in_the_reaction_phase_for_invalid_and_foreign_seats():
    _, result = win(make_config(4), "initial")
    state = result.state
    for seat in pending_reactors(state)[:-1]:
        state = apply_action(state, ReactAction(seat)).state
    snapshot = state
    for bad in (-1, 4, True, None, "1"):
        assert apply_action(state, TimeoutAction(bad)).reason is RejectionReason.INVALID_SEAT
    assert state == snapshot


def test_the_final_reaction_marker_is_public_and_carries_no_chit():
    _, result = win(make_config(4), "return")
    state = result.state
    for seat in pending_reactors(state)[:-1]:
        state = apply_action(state, ReactAction(seat)).state
    marker = timeout(state, pending_reactors(state)[0]).events[0]
    assert marker.public_view()["decision_kind"] == "final_reaction"
    assert all_names_json_free(marker.public_view())


# --- whole-game behaviour -----------------------------------------------------------------------


def test_a_timeout_game_is_reproducible_and_keeps_invariants_at_every_step():
    def play(seed):
        state = new_game(make_config(5, rounds=5, seed=seed)).state
        log = []
        for _ in range(400):
            if state.phase is Phase.GAME_OVER:
                break
            result = timeout(state)
            check_invariants(result.state)
            log.extend(e.debug_view() for e in result.events)
            state = result.state
            if state.phase is Phase.WIN_DECLARED:  # cannot happen: timeouts never claim
                raise AssertionError("a timeout produced a win")
        return state, log

    state_a, log_a = play(21)
    state_b, log_b = play(21)
    assert state_a == state_b and log_a == log_b
    assert play(22)[1] != log_a
    seqs = [entry["seq"] for entry in log_a]
    assert seqs == list(range(1, len(seqs) + 1))  # seq 0 is the opening DealEvent
