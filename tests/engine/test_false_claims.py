"""M4: false-claim penalties, round completion, and the next round (§3A.5, §3A.6)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import chitai.engine.deal as deal_module
from chitai.engine import (
    Accepted,
    ChitPassed,
    ClaimAction,
    ClaimMade,
    DealEvent,
    DeclineAction,
    FalseClaimPenalized,
    GameCompleted,
    GameConfig,
    InitialClaimMade,
    PassAction,
    Phase,
    Rejected,
    RejectionReason,
    RoundCompleted,
    apply_action,
    check_invariants,
    deal_round,
    initiator_for_round,
    legal_actions,
)

from .helpers import (
    CLAIM_POSITIONS,
    all_names_json_free,
    do_pass,
    false_claim_ready,
    make_config,
    start,
)

PLAYER_COUNTS = [4, 5, 6, 7, 8]


def claim(state):
    result = apply_action(state, ClaimAction(state.decision_seat))
    assert isinstance(result, Accepted), result
    return result


# --- the penalty ---------------------------------------------------------------------------

@pytest.mark.parametrize("position", CLAIM_POSITIONS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_false_claim_penalizes_only_the_claimant_by_n_minus_one(n, position):
    config = make_config(n, rounds=2 * n)
    state = false_claim_ready(config, position)
    claimant = state.decision_seat
    result = claim(state)
    new = result.state
    expected = tuple(-(n - 1) if seat == claimant else 0 for seat in range(n))
    assert new.scores == expected
    penalty = next(e for e in result.events if isinstance(e, FalseClaimPenalized))
    assert penalty.seat == claimant and penalty.penalty == n - 1
    assert penalty.score_changes == expected and penalty.scores == expected
    # every other player receives 0; no winner or reaction score is awarded
    assert all(new.scores[s] == 0 for s in range(n) if s != claimant)
    assert sum(new.scores) == -(n - 1)


@pytest.mark.parametrize("position", CLAIM_POSITIONS)
def test_claim_event_reports_the_false_claim_first(position):
    state = false_claim_ready(make_config(4, rounds=8), position)
    seat = state.decision_seat
    first = claim(state).events[0]
    assert isinstance(first, (InitialClaimMade, ClaimMade))
    assert (type(first) is InitialClaimMade) == (position == "initial")
    assert first.seat == seat and first.valid is False


def test_claim_positions_cover_the_three_claim_kinds():
    config = make_config(5, rounds=10)
    kinds = {p: false_claim_ready(config, p).decision_kind.value for p in CLAIM_POSITIONS}
    assert kinds == {
        "initial": "initial_claim",
        "receive": "non_initiator_receive",
        "return": "initiator_return",
    }


def test_each_claim_position_uses_the_documented_hand_shape():
    config = make_config(4, rounds=8)
    assert [len(h) for h in false_claim_ready(config, "initial").hands] == [4, 4, 4, 4]
    receive = false_claim_ready(config, "receive")
    assert len(receive.hands[receive.decision_seat]) == 5
    assert len(receive.hands[receive.initiator]) == 3
    returned = false_claim_ready(config, "return")
    assert [len(h) for h in returned.hands] == [4, 4, 4, 4]


# --- completed rounds ----------------------------------------------------------------------

@pytest.mark.parametrize("position", CLAIM_POSITIONS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_false_claim_increments_completed_rounds_exactly_once(n, position):
    config = make_config(n, rounds=2 * n)
    state = false_claim_ready(config, position, completed_round=1)
    assert state.completed_rounds == 1
    result = claim(state)
    assert result.state.completed_rounds == 2
    rounds = [e for e in result.events if isinstance(e, RoundCompleted)]
    assert len(rounds) == 1
    assert (rounds[0].completed_round, rounds[0].rounds_completed) == (1, 2)
    assert rounds[0].outcome == "false_claim" and rounds[0].claimant == state.decision_seat


def test_the_next_round_is_ready_after_a_false_claim():
    config = make_config(4, rounds=8)
    state = false_claim_ready(config, "receive")
    new = claim(state).state
    assert new.phase is Phase.INITIAL_CLAIMS
    assert new.decision_seat == new.initiator == 1
    assert new.initial_claims_resolved == 0
    assert new.winner is None and new.false_claimant is None and new.claim_decision_kind is None
    assert [len(h) for h in new.hands] == [4, 4, 4, 4]
    check_invariants(new)
    assert len(legal_actions(new)) == 2  # claim or decline for the new initiator


def test_a_false_claim_never_leaves_the_transient_phase_visible():
    for position in CLAIM_POSITIONS:
        new = claim(false_claim_ready(make_config(4, rounds=8), position)).state
        assert new.phase is not Phase.FALSE_CLAIM


def test_the_previous_state_is_not_mutated():
    state = false_claim_ready(make_config(4, rounds=8), "initial")
    snapshot = replace(state)
    claim(state)
    assert state == snapshot


# --- ineligible claims ---------------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_out_of_turn_initial_claim_has_no_penalty_and_no_round_completion(n):
    config = make_config(n, rounds=2 * n)
    state = start(config)
    before = replace(state)
    for seat in range(n):
        if seat == state.decision_seat:
            continue
        result = apply_action(state, ClaimAction(seat))
        assert isinstance(result, Rejected)
        assert result.reason is RejectionReason.NOT_DECISION_POINT
    assert state == before
    assert state.scores == (0,) * n and state.completed_rounds == 0 and state.next_seq == 1


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_claim_by_a_non_receiver_during_passing_is_rejected_without_penalty(n):
    config = make_config(n, rounds=2 * n)
    state = false_claim_ready(config, "receive")
    before = replace(state)
    for seat in range(n):
        if seat == state.decision_seat:
            continue
        result = apply_action(state, ClaimAction(seat))
        assert isinstance(result, Rejected)
        assert result.reason is RejectionReason.NOT_DECISION_POINT
    assert state == before and state.scores == (0,) * n and state.completed_rounds == 0


def test_initiator_claim_at_first_pass_and_while_holding_three_is_rejected_without_penalty():
    from .helpers import to_passing

    config = make_config(4, rounds=8)
    state = to_passing(config)
    for candidate in (state, do_pass(state)[0]):
        before = replace(candidate)
        result = apply_action(candidate, ClaimAction(candidate.initiator))
        assert isinstance(result, Rejected)
        assert candidate == before
        assert candidate.scores == (0,) * 4 and candidate.completed_rounds == 0


@pytest.mark.parametrize("seat", [-1, 4, 99, True, False, 1.0, "0", None])
def test_invalid_seat_claim_is_rejected_without_penalty(seat):
    state = false_claim_ready(make_config(4, rounds=8), "initial")
    before = replace(state)
    result = apply_action(state, ClaimAction(seat))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.INVALID_SEAT
    assert state == before


def test_declined_seat_cannot_claim_later_and_is_not_penalized():
    state = start(make_config(4, rounds=8))
    state = apply_action(state, DeclineAction(0)).state
    result = apply_action(state, ClaimAction(0))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.NOT_DECISION_POINT
    assert state.scores == (0,) * 4 and state.completed_rounds == 0


# --- determinism ---------------------------------------------------------------------------

@pytest.fixture
def deal_rng_calls(monkeypatch):
    calls = []
    real = deal_module.make_rng

    def counting(master_seed, purpose, *indices):
        calls.append((master_seed, purpose, indices))
        return real(master_seed, purpose, *indices)

    monkeypatch.setattr(deal_module, "make_rng", counting)
    return calls


def test_rejected_actions_consume_no_rng_and_no_sequence_numbers(deal_rng_calls):
    state = false_claim_ready(make_config(4, rounds=8), "initial")
    deal_rng_calls.clear()
    for action in (ClaimAction(3), DeclineAction(2), ClaimAction(99), PassAction(0, state.hands[0][0]), object()):
        assert isinstance(apply_action(state, action), Rejected)
    assert deal_rng_calls == []
    assert state.next_seq == 1


def test_false_claim_draws_exactly_one_deal_for_the_next_round(deal_rng_calls):
    config = make_config(4, rounds=8)
    state = false_claim_ready(config, "initial", completed_round=1)
    deal_rng_calls.clear()
    claim(state)
    # (master seed, "deal", (completed round, attempt)) and nothing else
    assert deal_rng_calls == [(config.seed, "deal", (2, 1))]


def test_final_false_claim_and_valid_claims_draw_no_deal(deal_rng_calls):
    config = make_config(4, rounds=4)
    final = false_claim_ready(config, "initial", completed_round=3)
    deal_rng_calls.clear()
    assert claim(final).state.phase is Phase.GAME_OVER
    won = start(config, matching={0, 1, 2, 3})
    deal_rng_calls.clear()
    assert apply_action(won, ClaimAction(won.decision_seat)).state.phase is Phase.WIN_DECLARED
    assert deal_rng_calls == []


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_next_round_deal_is_the_seeded_deal_for_that_round(n):
    config = GameConfig(num_players=n, num_rounds=2 * n, seed=77)
    state = false_claim_ready(config, "initial")
    new = claim(state).state
    expected = deal_round(config, 1, 1)
    assert new.hands == expected.hands and new.initiator == expected.initiator == 1


def test_next_deal_is_fresh_and_differs_from_the_previous_deal():
    config = GameConfig(num_players=4, num_rounds=8, seed=5)
    final, events, _ = _full_game(config)
    deals = [e for e in events if isinstance(e, DealEvent)]
    assert len(deals) == 8
    hands = [e.hands for e in deals]
    assert len(set(hands)) == 8  # no round reused a shuffle
    for round_index, event in enumerate(deals):
        assert event.hands == deal_round(config, round_index, 1).hands


def test_the_same_seed_reproduces_the_same_game_and_another_seed_does_not():
    config = GameConfig(num_players=5, num_rounds=10, seed=11)
    a_state, a_events, a_claimants = _full_game(config)
    b_state, b_events, b_claimants = _full_game(config)
    assert a_state == b_state and a_events == b_events and a_claimants == b_claimants
    dumped = lambda events: json.dumps([e.debug_view() for e in events], sort_keys=True)
    assert dumped(a_events) == dumped(b_events)
    _, other_events, _ = _full_game(GameConfig(num_players=5, num_rounds=10, seed=12))
    assert dumped(other_events) != dumped(a_events)


def _full_game(config):
    from .helpers import play_false_claim_rounds

    return play_false_claim_rounds(config)


# --- rotation ------------------------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_initiator_rotates_clockwise_by_completed_round_over_two_rotations(n):
    config = GameConfig(num_players=n, num_rounds=2 * n, seed=3)
    final, events, claimants = _full_game(config)
    deals = [e for e in events if isinstance(e, DealEvent)]
    assert [e.initiator for e in deals] == [r % n for r in range(2 * n)]
    assert [e.initiator for e in deals] == [initiator_for_round(config, r) for r in range(2 * n)]
    assert deals[0].initiator == 0  # the first initiator is seat 0
    assert final.initiator == 0  # the terminal state wraps back to seat 0


def test_a_false_claim_by_a_non_initiator_still_rotates_the_initiator_by_one():
    config = make_config(5, rounds=10)
    state = false_claim_ready(config, "receive")
    assert state.decision_seat != state.initiator
    assert claim(state).state.initiator == 1


# --- attempts ------------------------------------------------------------------------------

def test_attempt_numbering_restarts_at_one_for_each_newly_completed_round():
    config = make_config(4, rounds=8)
    state = false_claim_ready(config, "initial", completed_round=1, attempt=3)  # e.g. after draws
    assert state.attempt == 3
    result = claim(state)
    assert result.state.attempt == 1 and result.state.completed_rounds == 2
    penalty = next(e for e in result.events if isinstance(e, FalseClaimPenalized))
    deal = next(e for e in result.events if isinstance(e, DealEvent))
    assert (penalty.completed_round, penalty.attempt) == (1, 3)  # the round that ended
    assert (deal.completed_round, deal.attempt) == (2, 1)  # the round that begins


# --- accumulated scores --------------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_scores_accumulate_across_rounds(n):
    config = GameConfig(num_players=n, num_rounds=2 * n, seed=21)
    final, events, claimants = _full_game(config)
    expected = [0] * n
    for seat in claimants:
        expected[seat] -= n - 1
    assert len(claimants) == 2 * n
    assert final.scores == tuple(expected)
    assert sum(final.scores) == -(n - 1) * 2 * n
    # scores are carried unchanged into each new round and only change at a penalty
    running = (0,) * n
    for event in events:
        if isinstance(event, FalseClaimPenalized):
            running = tuple(a + b for a, b in zip(running, event.score_changes))
            assert event.scores == running


def test_scores_survive_into_the_next_round_unchanged_until_the_next_penalty():
    config = make_config(4, rounds=8)
    first = claim(false_claim_ready(config, "initial")).state
    assert first.scores == (-3, 0, 0, 0)
    declined = apply_action(first, DeclineAction(first.decision_seat)).state
    assert declined.scores == (-3, 0, 0, 0)
    second = claim(declined).state  # the next seat falsely claims in round 1
    assert second.completed_rounds == 2
    assert sum(second.scores) == -6 and second.scores[0] == -3


# --- terminal state ------------------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_final_round_ends_in_a_clear_terminal_state(n):
    config = GameConfig(num_players=n, num_rounds=n, seed=4)
    final, events, claimants = _full_game(config)
    assert final.phase is Phase.GAME_OVER
    assert final.completed_rounds == config.num_rounds
    assert final.decision_seat is None and final.decision_kind is None
    assert final.winner is None and final.false_claimant is None and final.claim_decision_kind is None
    assert final.attempt == 1
    assert legal_actions(final) == ()
    check_invariants(final)
    last = events[-1]
    assert isinstance(last, GameCompleted)
    assert last.final_scores == final.scores and last.rounds_completed == config.num_rounds
    assert (last.completed_round, last.attempt) == (config.num_rounds, 1)
    assert sum(1 for e in events if isinstance(e, GameCompleted)) == 1
    assert sum(1 for e in events if isinstance(e, RoundCompleted)) == config.num_rounds


@pytest.mark.parametrize("position", CLAIM_POSITIONS)
def test_no_action_is_accepted_after_the_game_is_over(position):
    n = 4
    config = make_config(n, rounds=n)
    state = false_claim_ready(config, position, completed_round=n - 1)
    over = claim(state).state
    assert over.phase is Phase.GAME_OVER
    before = replace(over)
    for seat in range(n):
        for action in (ClaimAction(seat), DeclineAction(seat), PassAction(seat, over.hands[seat][0])):
            result = apply_action(over, action)
            assert isinstance(result, Rejected)
            assert result.reason is RejectionReason.PHASE_NOT_ACCEPTING
            assert "game is over" in result.message
    for bad in (ClaimAction(-1), ClaimAction(None), object()):
        assert isinstance(apply_action(over, bad), Rejected)
    assert over == before and over.next_seq == before.next_seq


def test_the_game_does_not_end_one_round_early():
    config = make_config(4, rounds=8)
    for r in range(7):
        assert claim(false_claim_ready(config, "initial", completed_round=r)).state.phase is Phase.INITIAL_CLAIMS
    assert claim(false_claim_ready(config, "initial", completed_round=7)).state.phase is Phase.GAME_OVER


def test_terminal_state_keeps_hands_conserved_and_scores_final():
    config = make_config(4, rounds=4)
    state = false_claim_ready(config, "receive", completed_round=3)
    claimant = state.decision_seat
    over = claim(state).state
    chits = [c for h in over.hands for c in h]
    assert len(chits) == 16 and len(set(chits)) == 16
    # a receiver's claim leaves the claim-time shape: one seat holds five, one holds three
    assert sorted(len(h) for h in over.hands) == [3, 4, 4, 5]
    assert over.scores == tuple(-3 if seat == claimant else 0 for seat in range(4))


# --- events --------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "position,first_type",
    [("initial", InitialClaimMade), ("receive", ClaimMade), ("return", ClaimMade)],
)
def test_false_claim_event_order(position, first_type):
    config = make_config(4, rounds=8)
    events = claim(false_claim_ready(config, position)).events
    assert [type(e) for e in events] == [first_type, FalseClaimPenalized, RoundCompleted, DealEvent]
    assert [e.seq for e in events] == list(range(events[0].seq, events[0].seq + 4))


def test_the_final_false_claim_ends_with_game_completed_instead_of_a_deal():
    config = make_config(4, rounds=4)
    events = claim(false_claim_ready(config, "initial", completed_round=3)).events
    assert [type(e) for e in events] == [InitialClaimMade, FalseClaimPenalized, RoundCompleted, GameCompleted]


def test_event_sequence_numbers_are_contiguous_across_the_whole_game():
    config = GameConfig(num_players=4, num_rounds=8, seed=9)
    final, events, _ = _full_game(config)
    assert [e.seq for e in events] == list(range(len(events)))
    assert final.next_seq == len(events)


def test_event_sequence_is_contiguous_across_round_boundaries_with_passing():
    # Round 0 passes and ends in a false receiver claim; round 1 continues the sequence.
    from chitai.engine import start_from_deal

    from .helpers import crafted_deal

    config = make_config(4, rounds=8)
    first = start_from_deal(config, crafted_deal(config, matching=set()))
    state, seen = first.state, list(first.events)
    for _ in range(4):
        step = apply_action(state, DeclineAction(state.decision_seat))
        state = step.state
        seen.extend(step.events)
    step = apply_action(state, PassAction(state.decision_seat, state.hands[state.decision_seat][0]))
    state = step.state
    seen.extend(step.events)
    step = apply_action(state, ClaimAction(state.decision_seat))
    seen.extend(step.events)
    assert [type(e) for e in seen[-4:]] == [ClaimMade, FalseClaimPenalized, RoundCompleted, DealEvent]
    assert any(isinstance(e, ChitPassed) for e in seen)
    assert [e.seq for e in seen] == list(range(len(seen)))
    assert step.state.next_seq == len(seen)
    # and the next round keeps counting
    nxt = apply_action(step.state, DeclineAction(step.state.decision_seat))
    assert nxt.events[0].seq == len(seen)


def test_public_views_of_the_new_events_expose_no_chit_identity():
    config = GameConfig(num_players=5, num_rounds=10, seed=2)
    _, events, _ = _full_game(config)
    for event in events:
        view = event.public_view()
        json.dumps(view)
        assert all_names_json_free(view), view
        json.dumps(event.debug_view())
    assert "hands" not in next(e for e in events if isinstance(e, DealEvent)).public_view()


def test_new_event_payloads_are_plain_deterministic_json():
    config = make_config(4, rounds=8)
    events = claim(false_claim_ready(config, "initial")).events
    penalty, completed, deal = events[1], events[2], events[3]
    assert penalty.public_view() == {
        "type": "false_claim_penalized",
        "seq": penalty.seq,
        "completed_round": 0,
        "attempt": 1,
        "seat": 0,
        "penalty": 3,
        "score_changes": [-3, 0, 0, 0],
        "scores": [-3, 0, 0, 0],
    }
    assert completed.public_view() == {
        "type": "round_completed",
        "seq": completed.seq,
        "completed_round": 0,
        "attempt": 1,
        "outcome": "false_claim",
        "claimant": 0,
        "rounds_completed": 1,
    }
    assert (deal.public_view()["completed_round"], deal.public_view()["initiator"]) == (1, 1)


def test_game_completed_public_view():
    config = make_config(4, rounds=4)
    event = claim(false_claim_ready(config, "initial", completed_round=3)).events[-1]
    assert event.public_view() == {
        "type": "game_completed",
        "seq": event.seq,
        "completed_round": 4,
        "attempt": 1,
        "rounds_completed": 4,
        "final_scores": [0, 0, 0, -3],  # the round-3 initiator is seat 3
    }


# --- valid claims are unchanged in M4 ------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_valid_claims_are_unchanged_in_m4(n):
    config = make_config(n, rounds=2 * n)
    state = start(config, matching=set(range(n)))
    result = apply_action(state, ClaimAction(state.decision_seat))
    won = result.state
    assert won.phase is Phase.WIN_DECLARED and won.winner == state.decision_seat
    assert won.scores == (0,) * n  # win scoring is M5
    assert won.completed_rounds == state.completed_rounds  # round completion on a win is M5
    assert [type(e) for e in result.events] == [InitialClaimMade]
    assert legal_actions(won) == ()
    for seat in range(n):
        reject = apply_action(won, ClaimAction(seat))
        assert isinstance(reject, Rejected) and reject.reason is RejectionReason.PHASE_NOT_ACCEPTING
