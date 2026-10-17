"""Milestone 5: valid-win resolution, player reactions and scoring (§3A.5, §3A.6)."""

from __future__ import annotations

import itertools
import json
import random
from dataclasses import replace
from functools import lru_cache

import pytest

import chitai.engine.engine as engine_module
from chitai.engine import (
    Accepted,
    ClaimAction,
    DeclineAction,
    DealEvent,
    DecisionKind,
    GameCompleted,
    GameConfig,
    InitialClaimMade,
    InvariantViolation,
    ClaimMade,
    PassAction,
    Phase,
    PlayerReacted,
    ReactAction,
    Rejected,
    RejectionReason,
    RoundCompleted,
    ValidWinScored,
    apply_action,
    check_invariants,
    deal_round,
    is_valid_claim,
    legal_actions,
    new_game,
    pending_reactors,
    reaction_score,
    start_from_deal,
    valid_win_round_total,
    valid_win_score_changes,
    winner_score,
    ROUND_OUTCOME_VALID_WIN,
)

from .helpers import (
    all_names_json_free,
    crafted_deal,
    decline_all_but,
    decline_to_passing,
    do_pass,
    hand_matches,
    make_config,
    start_deal,
)

PLAYER_COUNTS = [4, 5, 6, 7, 8]
POSITIONS = ["initial", "receive", "return"]


# --- helpers -----------------------------------------------------------------------------------

def claim_ready(config, position, completed_round=0, attempt=1):
    """A state in which `state.decision_seat` is about to make an eligible, VALID claim at
    `position`: the initial phase (initiator), a receiving non-initiator holding five, or the
    initiator when its own name's chit returns."""
    n = config.num_players
    probe = crafted_deal(config, set(), completed_round, attempt)
    initiator = probe.initiator
    if position == "initial":
        return start_deal(config, crafted_deal(config, set(range(n)), completed_round, attempt))
    if position == "receive":
        matching = {(initiator + 1) % n}
        state = decline_to_passing(start_deal(config, crafted_deal(config, matching, completed_round, attempt)))
        state, _ = do_pass(state)  # the initiator sends any chit; the next seat already holds four of a name
        assert state.decision_seat == (initiator + 1) % n and len(state.hands[state.decision_seat]) == 5
        return state
    assert position == "return"
    state = decline_to_passing(start_deal(config, crafted_deal(config, {initiator}, completed_round, attempt)))
    state, _ = do_pass(state)  # the initiator sends one of its matching chits ...
    for _ in range(n - 1):
        state, _ = do_pass(state, state.hands[state.decision_seat][-1])  # ... everyone forwards it back
    assert state.decision_seat == initiator and len(state.hands[initiator]) == 4
    return state


def win(config, position, completed_round=0, attempt=1):
    """(claim-ready state, Accepted result of the valid claim)."""
    ready = claim_ready(config, position, completed_round, attempt)
    result = apply_action(ready, ClaimAction(ready.decision_seat))
    assert isinstance(result, Accepted)
    assert result.state.phase is Phase.WIN_DECLARED, result.state.phase
    return ready, result


def react(state, seat):
    result = apply_action(state, ReactAction(seat))
    assert isinstance(result, Accepted), result
    return result


def react_in_order(state, order):
    """Apply the reactions in `order`; returns (final state, all events)."""
    events = []
    for seat in order:
        result = react(state, seat)
        state = result.state
        events.extend(result.events)
    return state, events


def non_winners(state):
    return [s for s in range(state.config.num_players) if s != state.winner]


def assert_rejected(state, action, reason):
    result = apply_action(state, action)
    assert isinstance(result, Rejected), result
    assert result.reason is reason, (result.reason, result.message)
    return result


@lru_cache(maxsize=None)
def seed_winning_in_round(n, round_index, rounds, require_mixed_before):
    """First seed whose deal for `round_index` gives its initiator four of a kind and (if asked)
    whose earlier rounds all give their initiators mixed hands. Searches the real seeded deals."""
    for seed in itertools.count():
        config = GameConfig(num_players=n, num_rounds=rounds, seed=seed)
        deal = deal_round(config, round_index, 1)
        if not hand_matches(deal.hands[deal.initiator]):
            continue
        if require_mixed_before and any(
            hand_matches(d.hands[d.initiator])
            for d in (deal_round(config, r, 1) for r in range(round_index))
        ):
            continue
        return seed


# --- A. valid-win lifecycle -------------------------------------------------------------------

@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_valid_claim_enters_the_reaction_phase_and_records_the_winner(n, position):
    config = make_config(n, rounds=2 * n)
    ready, result = win(config, position)
    won = result.state
    claimant = ready.decision_seat
    assert won.phase is Phase.WIN_DECLARED
    assert won.winner == claimant and won.false_claimant is None
    assert won.reaction_order == ()
    assert won.decision_seat is None and won.decision_kind is None
    assert won.scores == (0,) * n  # nothing is scored until the last reaction
    assert won.completed_rounds == ready.completed_rounds and won.attempt == ready.attempt
    assert [type(e) for e in result.events] == [InitialClaimMade if position == "initial" else ClaimMade]
    assert result.events[0].valid is True
    check_invariants(won)


@pytest.mark.parametrize("position", POSITIONS)
def test_the_claim_position_is_recorded_for_each_winning_path(position):
    from chitai.engine import DecisionKind

    expected = {
        "initial": DecisionKind.INITIAL_CLAIM,
        "receive": DecisionKind.NON_INITIATOR_RECEIVE,
        "return": DecisionKind.INITIATOR_RETURN,
    }[position]
    _, result = win(make_config(5, rounds=10), position)
    assert result.state.claim_decision_kind is expected


def test_a_winner_from_a_later_seat_in_the_initial_order_is_recorded():
    config = make_config(5, rounds=10)
    state = start_deal(config, crafted_deal(config, {0, 1, 2, 3, 4}, completed_round=1))
    state, _ = decline_all_but(state, apply_action, 3)  # round 1: order is 1, 2, 3, 4, 0
    seat = state.decision_seat
    assert seat == 4
    won = apply_action(state, ClaimAction(seat)).state
    assert won.winner == 4 and won.phase is Phase.WIN_DECLARED


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_every_non_winner_is_legal_to_react_and_the_winner_is_not(n):
    config = make_config(n, rounds=n)
    _, result = win(config, "initial")
    won = result.state
    assert legal_actions(won) == tuple(ReactAction(s) for s in range(n) if s != won.winner)
    assert pending_reactors(won) == tuple(non_winners(won))
    assert ReactAction(won.winner) not in legal_actions(won)


def test_legal_actions_shrink_as_players_react_and_end_with_the_round():
    config = make_config(4)
    _, result = win(config, "initial")
    state = result.state  # winner is seat 0
    state = react(state, 2).state
    assert legal_actions(state) == (ReactAction(1), ReactAction(3))
    assert pending_reactors(state) == (1, 3)
    state = react(state, 1).state
    assert legal_actions(state) == (ReactAction(3),)
    state = react(state, 3).state  # the round completes: this is the next round's initial phase
    assert state.phase is Phase.INITIAL_CLAIMS
    assert pending_reactors(state) == ()
    assert all(not isinstance(a, ReactAction) for a in legal_actions(state))


# --- B. reaction validation --------------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_the_winner_cannot_react(n):
    _, result = win(make_config(n, rounds=n), "initial")
    won = result.state
    rejection = assert_rejected(won, ReactAction(won.winner), RejectionReason.WINNER_CANNOT_REACT)
    assert "won" in rejection.message
    # a mid-sequence winner attempt is rejected too, and nothing changes
    mid = react(won, non_winners(won)[0]).state
    assert_rejected(mid, ReactAction(mid.winner), RejectionReason.WINNER_CANNOT_REACT)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_player_cannot_react_twice(n):
    _, result = win(make_config(n, rounds=n), "initial")
    state = result.state
    first = non_winners(state)[0]
    state = react(state, first).state
    before = state
    assert_rejected(state, ReactAction(first), RejectionReason.ALREADY_REACTED)
    assert state == before and state.reaction_order == (first,)


@pytest.mark.parametrize("bad", [-1, 4, 99, True, False, 1.0, "1", None, (1,)])
def test_invalid_player_identifiers_are_rejected(bad):
    _, result = win(make_config(4), "initial")
    won = result.state
    before = won
    assert_rejected(won, ReactAction(bad), RejectionReason.INVALID_SEAT)
    assert won == before


def test_other_actions_after_a_win_are_rejected_without_penalty():
    config = make_config(4)
    ready, result = win(config, "initial")
    won = result.state
    for seat in range(4):
        for action in (ClaimAction(seat), DeclineAction(seat), PassAction(seat, won.hands[seat][0])):
            assert_rejected(won, action, RejectionReason.PHASE_NOT_ACCEPTING)
    assert won.scores == (0,) * 4 and won.winner == ready.decision_seat and won.reaction_order == ()


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_reacting_at_the_wrong_phase_is_rejected_and_changes_nothing(n):
    config = make_config(n, rounds=n)
    initial = start_deal(config, crafted_deal(config, set()))
    passing = decline_to_passing(initial)
    receiving, _ = do_pass(passing)
    for state in (initial, passing, receiving):
        for seat in range(n):
            before = state
            assert_rejected(state, ReactAction(seat), RejectionReason.ACTION_NOT_AVAILABLE)
            assert state == before


def test_reacting_after_the_round_has_completed_is_rejected():
    config = make_config(4, rounds=8)
    _, result = win(config, "initial")
    done, _ = react_in_order(result.state, [1, 2, 3])
    assert done.phase is Phase.INITIAL_CLAIMS and done.completed_rounds == 1
    for seat in range(4):  # late reactions to the finished round, including a retry of the last one
        assert_rejected(done, ReactAction(seat), RejectionReason.ACTION_NOT_AVAILABLE)
    assert done.scores == (4, 3, 2, 1)  # scored once, untouched by the retries


def test_no_reaction_or_other_action_is_accepted_after_the_game_is_over():
    config = make_config(4, rounds=4)
    _, result = win(config, "initial", completed_round=3)
    assert result.state.winner == 3  # the round-3 initiator wins, so seats 0, 1, 2 react
    over, _ = react_in_order(result.state, [0, 1, 2])
    assert over.phase is Phase.GAME_OVER
    for seat in range(4):
        for action in (ReactAction(seat), ClaimAction(seat), DeclineAction(seat)):
            assert_rejected(over, action, RejectionReason.PHASE_NOT_ACCEPTING)
    assert legal_actions(over) == () and pending_reactors(over) == ()


@pytest.mark.parametrize("n", [4, 8])
def test_rejected_reactions_change_no_state_event_sequence_or_randomness(n, monkeypatch):
    calls = []
    real = engine_module.deal_round
    monkeypatch.setattr(engine_module, "deal_round", lambda *a, **k: calls.append(a) or real(*a, **k))
    config = make_config(n, rounds=2 * n)
    _, result = win(config, "initial")
    state = react(result.state, non_winners(result.state)[0]).state
    snapshot = state
    for action in (
        ReactAction(state.winner),
        ReactAction(state.reaction_order[0]),
        ReactAction(-1),
        ReactAction(n),
        ClaimAction(state.winner),
        "react",
        None,
    ):
        assert isinstance(apply_action(state, action), Rejected)
    assert state == snapshot and state.next_seq == snapshot.next_seq
    assert calls == []  # rejections never touch the deal RNG


# --- C. scoring --------------------------------------------------------------------------------

def test_four_player_scores_follow_reaction_order():
    _, result = win(make_config(4), "initial")
    won = result.state  # seat 0 won
    final, events = react_in_order(won, [3, 1, 2])
    scored = next(e for e in events if isinstance(e, ValidWinScored))
    assert scored.winner == 0 and scored.reaction_order == (3, 1, 2)
    assert scored.score_changes == (4, 2, 1, 3)  # winner 4; first 3; second 2; last 1
    assert scored.scores == (4, 2, 1, 3) and final.scores == (4, 2, 1, 3)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_scores_for_every_supported_player_count(n):
    _, result = win(make_config(n, rounds=2 * n), "initial")
    won = result.state
    order = list(reversed(non_winners(won)))
    final, events = react_in_order(won, order)
    scored = next(e for e in events if isinstance(e, ValidWinScored))
    assert scored.score_changes[won.winner] == n
    for position, seat in enumerate(order, start=1):
        assert scored.score_changes[seat] == n - position
    assert sorted(scored.score_changes, reverse=True) == list(range(n, 0, -1))  # N, N-1, ..., 1
    assert sum(scored.score_changes) == valid_win_round_total(n) == n * (n + 1) // 2
    assert final.scores == scored.score_changes


def test_reaction_order_alone_determines_the_non_winner_scores_for_all_orders():
    config = make_config(4)
    _, result = win(config, "initial")
    won = result.state
    outcomes = set()
    for order in itertools.permutations(non_winners(won)):
        final, events = react_in_order(won, order)
        scored = next(e for e in events if isinstance(e, ValidWinScored))
        assert scored.score_changes[won.winner] == 4  # the winner's score never depends on the order
        for position, seat in enumerate(order, start=1):
            assert scored.score_changes[seat] == 4 - position
        outcomes.add(scored.score_changes)
    assert len(outcomes) == 6  # six orders, six different score vectors


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_scores_are_the_same_for_every_winning_path(n, position):
    config = make_config(n, rounds=2 * n)
    _, result = win(config, position)
    won = result.state
    order = non_winners(won)
    final, events = react_in_order(won, order)
    scored = next(e for e in events if isinstance(e, ValidWinScored))
    assert scored.score_changes[won.winner] == n
    assert [scored.score_changes[s] for s in order] == list(range(n - 1, 0, -1))


def test_valid_win_scoring_is_a_pure_function():
    assert winner_score(4) == 4 and winner_score(8) == 8
    assert [reaction_score(4, p) for p in (1, 2, 3)] == [3, 2, 1]
    assert [reaction_score(8, p) for p in range(1, 8)] == [7, 6, 5, 4, 3, 2, 1]
    assert valid_win_score_changes(4, 2, (0, 3, 1)) == (3, 1, 4, 2)
    assert valid_win_round_total(4) == 10 and valid_win_round_total(8) == 36


@pytest.mark.parametrize("n", [3, 9, True, 4.0, "4", None])
def test_scoring_rejects_unsupported_player_counts(n):
    with pytest.raises(ValueError):
        winner_score(n)
    with pytest.raises(ValueError):
        valid_win_round_total(n)


@pytest.mark.parametrize("position", [0, 4, -1, True, 1.5, None])
def test_reaction_score_rejects_invalid_positions(position):
    with pytest.raises(ValueError):
        reaction_score(4, position)


@pytest.mark.parametrize(
    "winner, order",
    [
        (0, (1, 2)),  # missing a non-winner
        (0, (1, 2, 3, 3)),  # repeated seat
        (0, (0, 1, 2)),  # contains the winner
        (0, (1, 2, 9)),  # invalid seat
        (0, [1, 2, 3]),  # not a tuple
        (4, (1, 2, 3)),  # winner out of range
        (True, (1, 2, 3)),
    ],
)
def test_valid_win_score_changes_rejects_inconsistent_input(winner, order):
    with pytest.raises(ValueError):
        valid_win_score_changes(4, winner, order)


def test_scoring_is_applied_exactly_once_and_cannot_be_replayed():
    config = make_config(4, rounds=8)
    _, result = win(config, "initial")
    won = result.state
    state, events = react_in_order(won, [1, 2, 3])
    assert [type(e) for e in events] == [PlayerReacted] * 3 + [ValidWinScored, RoundCompleted, DealEvent]
    assert sum(isinstance(e, ValidWinScored) for e in events) == 1
    assert state.scores == (4, 3, 2, 1)
    # retrying the completing action (or any reaction) is rejected and scores stay put
    for seat in range(4):
        assert isinstance(apply_action(state, ReactAction(seat)), Rejected)
    assert state.scores == (4, 3, 2, 1)
    # the pre-completion state is immutable, so replaying from it yields the identical outcome
    again, again_events = react_in_order(won, [1, 2, 3])
    assert again == state and again_events == events


def test_scores_accumulate_across_rounds_and_false_claim_scoring_is_unchanged():
    n = 4
    seed = seed_winning_in_round(n, 1, 2 * n, False)
    config = GameConfig(num_players=n, num_rounds=2 * n, seed=seed)
    # Round 0: crafted all-mixed deal, false claim by seat 0 (-(N-1)); everyone else 0.
    state = start_from_deal(config, crafted_deal(config, set())).state
    state = apply_action(state, ClaimAction(0)).state
    assert state.scores == (-3, 0, 0, 0) and state.completed_rounds == 1
    # Round 1 (real seeded deal): seat 1 holds four of a kind and wins; reactions 2, 3, 0.
    assert state.decision_seat == 1 and hand_matches(state.hands[1])
    won = apply_action(state, ClaimAction(1)).state
    assert won.scores == (-3, 0, 0, 0)  # unchanged while reactions are pending
    state, events = react_in_order(won, [2, 3, 0])
    scored = next(e for e in events if isinstance(e, ValidWinScored))
    # seat 1 wins (4); seat 2 reacted first (3), seat 3 second (2), seat 0 last (1)
    assert scored.score_changes == (1, 4, 3, 2)
    assert state.scores == (-3 + 1, 4, 3, 2) and state.completed_rounds == 2
    # Round 2: the cumulative scores survive into the next round's state.
    assert state.phase is Phase.INITIAL_CLAIMS and state.decision_seat == 2
    assert scored.scores == state.scores


def test_a_false_claim_after_a_valid_win_still_costs_n_minus_one_and_only_the_claimant():
    n = 4
    seed = seed_winning_in_round(n, 1, 2 * n, False)
    config = GameConfig(num_players=n, num_rounds=2 * n, seed=seed)
    state = apply_action(start_from_deal(config, crafted_deal(config, set())).state, ClaimAction(0)).state
    won = apply_action(state, ClaimAction(1)).state
    after_win, _ = react_in_order(won, [2, 3, 0])
    seat = after_win.decision_seat
    assert not hand_matches(after_win.hands[seat])  # round 2's real deal: a claim here is false
    result = apply_action(after_win, ClaimAction(seat))
    deltas = [a - b for a, b in zip(result.state.scores, after_win.scores)]
    assert sorted(deltas) == [-3, 0, 0, 0] and deltas[seat] == -3
    assert result.state.completed_rounds == after_win.completed_rounds + 1


# --- D. round progression ----------------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_round_completion_happens_exactly_once_on_the_last_reaction(n):
    config = make_config(n, rounds=2 * n)
    _, result = win(config, "initial")
    state = result.state
    order = non_winners(state)
    for seat in order[:-1]:
        step = react(state, seat)
        state = step.state
        assert state.phase is Phase.WIN_DECLARED and state.completed_rounds == 0
        assert [type(e) for e in step.events] == [PlayerReacted]
        assert state.scores == (0,) * n  # nothing is scored before the last reaction
    last = react(state, order[-1])
    assert last.state.completed_rounds == 1
    completed = [e for e in last.events if isinstance(e, RoundCompleted)]
    assert len(completed) == 1
    assert completed[0].outcome == ROUND_OUTCOME_VALID_WIN and completed[0].claimant == state.winner
    assert completed[0].rounds_completed == 1 and completed[0].completed_round == 0


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_the_next_round_uses_a_fresh_seeded_deal_and_a_rotated_initiator(n, position):
    config = make_config(n, rounds=2 * n, seed=7)
    _, result = win(config, position)
    final, events = react_in_order(result.state, non_winners(result.state))
    expected = deal_round(config, 1, 1)
    assert final.phase is Phase.INITIAL_CLAIMS and final.completed_rounds == 1
    assert final.hands == expected.hands  # the seeded deal for (round 1, attempt 1)
    assert final.initiator == expected.initiator == 1  # seat 0 -> seat 1
    assert final.decision_seat == 1 and final.initial_claims_resolved == 0
    assert final.winner is None and final.false_claimant is None and final.reaction_order == ()
    assert final.claim_decision_kind is None
    deal_event = events[-1]
    assert isinstance(deal_event, DealEvent) and deal_event.hands == expected.hands
    assert deal_event.completed_round == 1 and deal_event.attempt == 1


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_initiator_rotates_one_seat_per_completed_round_after_a_win(n):
    config = make_config(n, rounds=2 * n)
    for round_index in range(n):  # every possible initiator, including the wraparound
        _, result = win(config, "initial", completed_round=round_index)
        final, _ = react_in_order(result.state, non_winners(result.state))
        assert final.initiator == (round_index + 1) % n
        assert final.completed_rounds == round_index + 1


def test_the_attempt_counter_resets_to_one_after_a_won_round():
    config = make_config(4, rounds=8)
    _, result = win(config, "initial", completed_round=1, attempt=3)
    assert result.state.attempt == 3
    final, events = react_in_order(result.state, non_winners(result.state))
    assert final.attempt == 1 and final.completed_rounds == 2
    assert all(e.attempt == 3 for e in events if not isinstance(e, DealEvent))
    assert events[-1].attempt == 1


def test_a_win_in_the_final_configured_round_ends_the_game():
    n = 4
    config = make_config(n, rounds=n)
    _, result = win(config, "initial", completed_round=n - 1)
    final, events = react_in_order(result.state, [0, 1, 2])  # seat 3 wins the last round
    assert result.state.winner == 3
    assert final.phase is Phase.GAME_OVER
    assert final.completed_rounds == n and final.attempt == 1 and final.initiator == 0
    assert final.decision_seat is None and final.decision_kind is None
    assert final.winner is None and final.reaction_order == () and final.claim_decision_kind is None
    assert final.scores == (3, 2, 1, 4)
    assert [type(e) for e in events] == [PlayerReacted] * 3 + [ValidWinScored, RoundCompleted, GameCompleted]
    assert events[-1].final_scores == final.scores and events[-1].completed_round == n
    assert events[-2].rounds_completed == n
    check_invariants(final)


def test_a_win_at_a_later_attempt_in_the_final_round_ends_the_game_at_attempt_one():
    config = make_config(4, rounds=4)
    _, result = win(config, "initial", completed_round=3, attempt=3)
    assert result.state.attempt == 3
    final, events = react_in_order(result.state, non_winners(result.state))
    assert final.phase is Phase.GAME_OVER and final.attempt == 1 and final.completed_rounds == 4
    assert events[-1].attempt == 1 and events[-2].attempt == 3  # RoundCompleted keeps the ended attempt


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_one_round_early_a_win_does_not_end_the_game(n):
    config = make_config(n, rounds=2 * n)
    _, result = win(config, "initial", completed_round=n - 1)
    final, _ = react_in_order(result.state, non_winners(result.state))
    assert final.phase is Phase.INITIAL_CLAIMS and final.completed_rounds == n


@pytest.mark.parametrize("n", [4, 8])
def test_a_win_in_the_final_round_after_earlier_false_claim_penalties(n):
    seed = seed_winning_in_round(n, n - 1, n, True)
    config = GameConfig(num_players=n, num_rounds=n, seed=seed)
    state = new_game(config).state
    for r in range(n - 1):  # every earlier round: its initiator claims a mixed hand
        assert state.completed_rounds == r and state.decision_seat == r
        state = apply_action(state, ClaimAction(r)).state
    assert state.completed_rounds == n - 1 and state.decision_seat == n - 1
    assert state.scores == tuple([-(n - 1)] * (n - 1) + [0])
    won = apply_action(state, ClaimAction(n - 1)).state
    assert won.phase is Phase.WIN_DECLARED and won.winner == n - 1
    order = list(range(n - 1))  # seats 0 .. n-2 react in seat order
    final, events = react_in_order(won, order)
    expected = [-(n - 1) + (n - 1 - i) for i in range(n - 1)] + [n]
    assert final.phase is Phase.GAME_OVER and final.scores == tuple(expected)
    assert events[-1].final_scores == final.scores
    for seat in range(n):
        for action in (ReactAction(seat), ClaimAction(seat), DeclineAction(seat)):
            assert isinstance(apply_action(final, action), Rejected)


@pytest.mark.parametrize("n", [4, 8])
def test_event_sequence_numbers_are_contiguous_through_the_whole_win_lifecycle(n):
    config = make_config(n, rounds=2 * n)
    ready = claim_ready(config, "receive")
    claim = apply_action(ready, ClaimAction(ready.decision_seat))
    final, events = react_in_order(claim.state, non_winners(claim.state))
    seqs = [e.seq for e in claim.events + tuple(events)]
    assert seqs == list(range(ready.next_seq, ready.next_seq + len(seqs)))
    assert final.next_seq == ready.next_seq + len(seqs)


# --- E. determinism and invariants -------------------------------------------------------------

def play_scripted(config, reaction_seed):
    """Initial claims all decline until the first matching hand claims (real seeded deals); wins
    are followed by random-order reactions drawn from `reaction_seed`. Returns every event."""
    rng = random.Random(reaction_seed)
    result = new_game(config)
    state, events = result.state, list(result.events)
    for _ in range(4000):
        if state.phase is Phase.GAME_OVER:
            break
        if state.phase is Phase.WIN_DECLARED:
            action = ReactAction(rng.choice(pending_reactors(state)))
        elif state.phase is Phase.INITIAL_CLAIMS:
            seat = state.decision_seat
            action = DeclineAction(seat) if rng.random() < 0.5 else ClaimAction(seat)
        else:
            seat = state.decision_seat
            hand = state.hands[seat]
            can_claim = state.decision_kind is not DecisionKind.INITIATOR_FIRST_PASS
            action = (
                ClaimAction(seat)
                if can_claim and rng.random() < 0.3
                else PassAction(seat, hand[rng.randrange(len(hand))])
            )
        step = apply_action(state, action)
        assert isinstance(step, Accepted), step
        state = step.state
        events.extend(step.events)
    return state, events


@pytest.mark.parametrize("n", [4, 6, 8])
def test_equal_config_seed_and_actions_give_identical_outcomes(n):
    config = GameConfig(num_players=n, num_rounds=n, seed=42)
    a_state, a_events = play_scripted(config, reaction_seed=5)
    b_state, b_events = play_scripted(GameConfig(num_players=n, num_rounds=n, seed=42), reaction_seed=5)
    assert a_state == b_state and a_events == b_events
    assert [e.debug_view() for e in a_events] == [e.debug_view() for e in b_events]


def test_a_different_reaction_order_changes_scores_but_not_the_next_deal():
    config = make_config(4, rounds=8, seed=11)
    _, result = win(config, "initial")
    a, _ = react_in_order(result.state, [1, 2, 3])
    b, _ = react_in_order(result.state, [3, 2, 1])
    assert a.scores != b.scores
    assert a.hands == b.hands == deal_round(config, 1, 1).hands  # reactions never consume randomness
    assert a.initiator == b.initiator


def test_deals_are_requested_only_for_the_next_round_and_not_at_all_when_the_game_ends(monkeypatch):
    calls = []
    real = engine_module.deal_round
    monkeypatch.setattr(engine_module, "deal_round", lambda *a, **k: calls.append(a[1:]) or real(*a, **k))
    config = make_config(4, rounds=8)
    _, result = win(config, "initial")
    after_first = react(result.state, 1).state
    react(after_first, 2)
    assert calls == []  # non-completing reactions use no randomness
    react_in_order(result.state, [1, 2, 3])
    assert calls == [(1, 1)]  # exactly one deal: (completed round 1, attempt 1)
    calls.clear()
    last = make_config(4, rounds=4)
    _, final_win = win(last, "initial", completed_round=3)
    react_in_order(final_win.state, [0, 1, 2])
    assert calls == []  # the final round of the game deals nothing


def steered_action(state, actions, rng):
    """A random-but-steered legal action so that generated games reach both valid wins and false
    claims: players usually claim a genuinely valid hand, rarely claim a false one, and otherwise
    keep their most-held name (passing the least-held chit) or pass at random."""
    if state.phase is Phase.WIN_DECLARED:
        return rng.choice(actions)
    seat = state.decision_seat
    claim = ClaimAction(seat)
    if claim in actions:
        valid = is_valid_claim(state.decision_kind, state.hands[seat])
        if rng.random() < (0.8 if valid else 0.05):
            return claim
    if state.phase is Phase.INITIAL_CLAIMS:
        return DeclineAction(seat)
    passes = [a for a in actions if isinstance(a, PassAction)]
    if rng.random() < 0.15:
        return rng.choice(passes)
    counts = {}
    for chit in state.hands[seat]:
        counts[chit.name] = counts.get(chit.name, 0) + 1
    fewest = min(counts.values())
    return rng.choice([a for a in passes if counts[a.chit.name] == fewest])


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_invariants_and_an_independent_score_oracle_hold_across_generated_games(n):
    wins_seen = false_seen = finished = 0
    for seed in range(25):
        config = GameConfig(num_players=n, num_rounds=n, seed=seed)
        rng = random.Random(9000 + 31 * n + seed)
        result = new_game(config)
        state, events = result.state, list(result.events)
        oracle, pending, reacted, claimant = [0] * n, [0] * n, [], None
        for _ in range(1500):  # nothing stops an endless pass cycle before M6, so bound the walk
            if state.phase is Phase.GAME_OVER:
                finished += 1
                break
            step = apply_action(state, steered_action(state, legal_actions(state), rng))
            assert isinstance(step, Accepted), step
            check_invariants(step.state)
            for event in step.events:
                assert event.seq == len(events)
                events.append(event)
                # an oracle built only from claim and reaction events, never from engine scores
                if isinstance(event, (InitialClaimMade, ClaimMade)):
                    claimant, reacted, pending = event.seat, [], [0] * n
                    if not event.valid:
                        oracle[event.seat] -= n - 1
                        false_seen += 1
                elif isinstance(event, PlayerReacted):
                    reacted.append(event.seat)
                    assert event.position == len(reacted) and event.winner == claimant
                    pending[event.seat] += n - event.position  # banked, not yet scored
                    if len(reacted) == n - 1:  # the last reaction completes the round: score once
                        pending[claimant] += n
                        oracle = [a + b for a, b in zip(oracle, pending)]
                        wins_seen += 1
            state = step.state
            assert list(state.scores) == oracle
            assert state.next_seq == len(events)
    assert wins_seen > 0 and false_seen > 0 and finished > 0


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_invariants_hold_at_every_state_of_the_win_lifecycle(n):
    config = make_config(n, rounds=2 * n)
    for position in POSITIONS:
        ready, result = win(config, position)
        state = result.state
        check_invariants(state)
        for seat in non_winners(state):
            state = react(state, seat).state
            check_invariants(state)
            held = [c for h in state.hands for c in h]
            assert len(held) == 4 * n and len(set(held)) == 4 * n


def _won_state(n=4):
    return win(make_config(n, rounds=2 * n), "initial")[1].state


def test_the_full_length_reaction_state_is_valid_but_one_more_is_not():
    won = _won_state()  # winner 0
    check_invariants(replace(won, reaction_order=(1, 2, 3)))  # transient state, never returned
    with pytest.raises(InvariantViolation):
        check_invariants(replace(won, reaction_order=(1, 2, 3, 1)))


@pytest.mark.parametrize("order", [(0,), (1, 1), (1, 2, 1), (4,), (-1,), (True,), [1], (1.0,)])
def test_bad_reaction_orders_are_detected(order):
    with pytest.raises(InvariantViolation):
        check_invariants(replace(_won_state(), reaction_order=order))


def test_reactions_outside_the_reaction_phase_are_detected():
    config = make_config(4)
    initial = start_deal(config, crafted_deal(config, set()))
    passing = decline_to_passing(initial)
    over = replace(
        _won_state(), phase=Phase.GAME_OVER, completed_rounds=8, attempt=1, initiator=0,
        initial_claims_resolved=0, winner=None, claim_decision_kind=None,
    )
    for state in (initial, passing):
        with pytest.raises(InvariantViolation):
            check_invariants(replace(state, reaction_order=(1,)))
    with pytest.raises(InvariantViolation):
        check_invariants(replace(over, reaction_order=(1,)))


def _at_round(k, scores, n=4):
    """A consistent start-of-round state at completed-round index k with the given scores."""
    config = make_config(n, rounds=2 * n)
    state = start_deal(config, crafted_deal(config, set(), completed_round=k))
    return replace(state, scores=scores)


def test_positive_scores_are_valid_but_unreachable_ones_are_not():
    # n = 4: one valid-win round adds 10 in total (4, 3, 2, 1 in some order); one false claim subtracts 3.
    check_invariants(_at_round(1, (4, 3, 2, 1)))  # reachable after one win
    check_invariants(_at_round(1, (-3, 0, 0, 0)))  # the M4 penalty is still valid
    check_invariants(_at_round(2, (-2, 4, 3, 2)))  # a penalty and then a win
    check_invariants(_at_round(2, (8, 7, 5, 0)))  # two wins can stack on one seat's side
    for k, bad in [
        (1, (1, 0, 0, 0)),  # total 1 is not reachable with one round
        (1, (5, 5, 0, 0)),  # a seat above N points per completed round
        (1, (-4, 0, 0, 0)),  # a seat below -(N-1) per completed round
        (0, (4, 3, 2, 1)),  # win scores with no completed round
        (2, (9, 0, 0, 0)),  # a seat above 2 * N
    ]:
        with pytest.raises(InvariantViolation):
            check_invariants(_at_round(k, bad))


# --- F. edge cases and views -------------------------------------------------------------------

def test_public_views_of_the_new_events_are_json_safe_and_leak_no_chit_names():
    config = make_config(4, rounds=8)
    ready = claim_ready(config, "receive")
    claim = apply_action(ready, ClaimAction(ready.decision_seat))
    final, events = react_in_order(claim.state, [2, 3, 0])
    new_events = [e for e in events if isinstance(e, (PlayerReacted, ValidWinScored, RoundCompleted))]
    assert len(new_events) == 5
    for event in new_events:
        view = event.public_view()
        json.dumps(view)
        assert all_names_json_free(view)
        assert event.debug_view() == view  # nothing private in these events
    reacted = events[0].public_view()
    assert reacted["type"] == "player_reacted" and reacted["seat"] == 2 and reacted["position"] == 1
    scored = next(e for e in events if isinstance(e, ValidWinScored)).public_view()
    assert scored["type"] == "valid_win_scored"
    assert scored["winner"] == claim.state.winner and scored["reaction_order"] == [2, 3, 0]
    assert sum(scored["score_changes"]) == 10 and scored["scores"] == list(final.scores)


def test_wrong_phase_actions_around_a_win_are_rejected():
    config = make_config(4, rounds=8)
    initial = start_deal(config, crafted_deal(config, {0, 1, 2, 3}))
    # Reacting is wrong in the initial phase, but claiming there still starts the lifecycle.
    assert_rejected(initial, ReactAction(initial.decision_seat), RejectionReason.ACTION_NOT_AVAILABLE)
    won = apply_action(initial, ClaimAction(initial.decision_seat)).state
    # ... and passing, claiming and declining are wrong once reactions have begun.
    assert_rejected(won, PassAction(1, won.hands[1][0]), RejectionReason.PHASE_NOT_ACCEPTING)
    assert_rejected(won, DeclineAction(1), RejectionReason.PHASE_NOT_ACCEPTING)
    assert_rejected(won, ClaimAction(1), RejectionReason.PHASE_NOT_ACCEPTING)
