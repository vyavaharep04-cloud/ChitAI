"""The initial claim phase through the authoritative engine (§3A.3, §3A.5)."""

import random

import pytest

from chitai.engine import (
    Accepted,
    ClaimAction,
    DeclineAction,
    DecisionKind,
    GameConfig,
    Phase,
    Rejected,
    RejectionReason,
    apply_action,
    check_invariants,
    initial_claim_order,
    legal_actions,
    new_game,
    start_from_deal,
)

from .helpers import crafted_deal, decline_all_but, make_config, start

PLAYER_COUNTS = range(4, 9)


# --- starting a game -------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_new_game_starts_initial_phase_at_seat_zero(n):
    result = new_game(GameConfig(num_players=n, num_rounds=n, seed=5))
    state = result.state
    assert state.phase is Phase.INITIAL_CLAIMS
    assert state.decision_kind is DecisionKind.INITIAL_CLAIM
    assert state.decision_seat == 0 and state.initiator == 0
    assert (state.completed_rounds, state.attempt) == (0, 1)
    assert state.scores == (0,) * n
    assert state.initial_claims_resolved == 0
    assert all(len(h) == 4 for h in state.hands)
    assert [e.seq for e in result.events] == [0]
    assert state.next_seq == 1


def test_new_game_is_deterministic_per_seed():
    a = new_game(GameConfig(5, 5, seed=11)).state
    b = new_game(GameConfig(5, 5, seed=11)).state
    c = new_game(GameConfig(5, 5, seed=12)).state
    assert a == b
    assert a.hands != c.hands


def test_start_from_deal_rejects_non_deal():
    with pytest.raises(TypeError):
        start_from_deal(make_config(4), "not a deal")


def test_start_from_deal_rejects_inconsistent_initiator():
    from dataclasses import replace

    from chitai.engine import InvariantViolation

    config = make_config(4)
    bad = replace(crafted_deal(config), initiator=2)
    with pytest.raises(InvariantViolation):
        start_from_deal(config, bad)


# --- deterministic order, all decline --------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
@pytest.mark.parametrize("completed_round", [0, 1, "last"])
def test_opportunities_follow_initiator_clockwise(n, completed_round):
    config = make_config(n, rounds=2 * n)
    rnd = 2 * n - 1 if completed_round == "last" else completed_round
    state = start(config, completed_round=rnd)
    expected = initial_claim_order(n, state.initiator)
    assert expected[0] == rnd % n

    seen = []
    while state.phase is Phase.INITIAL_CLAIMS:
        seen.append(state.decision_seat)
        result = apply_action(state, DeclineAction(state.decision_seat))
        assert isinstance(result, Accepted)
        state = result.state
    assert tuple(seen) == expected


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_all_decline_moves_to_passing_with_initiator_first_pass(n):
    state = start(make_config(n))
    state, events = decline_all_but(state, apply_action, n)
    assert state.phase is Phase.PASSING
    assert state.decision_seat == state.initiator
    assert state.decision_kind is DecisionKind.INITIATOR_FIRST_PASS
    assert state.initial_claims_resolved == n
    assert state.winner is None and state.false_claimant is None
    assert state.scores == (0,) * n
    assert all(len(h) == 4 for h in state.hands)  # no chit has moved
    assert [e.type for e in events] == ["initial_claim_declined"] * n + ["initial_claims_resolved"]


def test_initiator_has_no_further_initial_opportunity_after_resolution():
    state = start(make_config(4))
    state, _ = decline_all_but(state, apply_action, 4)
    # M3: passing now exists, so the phase accepts actions, but the initiator
    # still has no claim opportunity at the first pass (§3A.3) and no decline exists.
    expected = {
        ClaimAction: RejectionReason.NO_CLAIM_OPPORTUNITY,
        DeclineAction: RejectionReason.ACTION_NOT_AVAILABLE,
    }
    for action in (ClaimAction(state.initiator), DeclineAction(state.initiator)):
        before = state
        result = apply_action(state, action)
        assert isinstance(result, Rejected)
        assert result.reason is expected[type(action)]
        assert state == before
    assert not any(isinstance(a, (ClaimAction, DeclineAction)) for a in legal_actions(state))


# --- claims ----------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_valid_claim_by_each_seat_position_fixes_winner(n):
    config = make_config(n, rounds=2 * n)
    for k in range(n):  # k-th seat in the order claims
        state = start(config, matching={0, 1} if n > 4 else {0, 1, 2, 3}, completed_round=1)
        order = initial_claim_order(n, state.initiator)
        state, _ = decline_all_but(state, apply_action, k)
        seat = order[k]
        has_match = seat in {0, 1} if n > 4 else True
        result = apply_action(state, ClaimAction(seat))
        assert isinstance(result, Accepted)
        new = result.state
        if has_match:
            assert new.phase is Phase.WIN_DECLARED and new.winner == seat
            assert new.false_claimant is None
        else:
            assert new.phase is Phase.FALSE_CLAIM and new.false_claimant == seat
        assert new.decision_seat is None and new.decision_kind is None
        assert new.scores == (0,) * n  # M2 applies no scores
        assert new.completed_rounds == state.completed_rounds  # M2 completes no round
        assert new.attempt == state.attempt
        (event,) = result.events
        assert event.type == "initial_claim_made" and event.seat == seat


def test_matching_player_may_decline_engine_never_claims_for_them():
    # Seat 0 holds four matching chits but declines; the engine must not claim for it.
    state = start(make_config(4), matching={0, 1, 2, 3})
    result = apply_action(state, DeclineAction(0))
    assert isinstance(result, Accepted)
    assert result.state.phase is Phase.INITIAL_CLAIMS
    assert result.state.decision_seat == 1
    assert result.state.winner is None


def test_engine_waits_at_matching_hand_until_explicit_action():
    state = start(make_config(4), matching={0, 1, 2, 3})
    check_invariants(state)
    assert state.phase is Phase.INITIAL_CLAIMS and state.winner is None
    assert legal_actions(state) == (ClaimAction(0), DeclineAction(0))


def test_non_matching_player_may_claim_and_it_is_a_false_claim():
    # Eligibility does not depend on matching (§3A.4); only validity does.
    state = start(make_config(4), matching=set())
    result = apply_action(state, ClaimAction(0))
    assert isinstance(result, Accepted)
    assert result.state.phase is Phase.FALSE_CLAIM
    assert result.state.false_claimant == 0 and result.state.winner is None
    assert result.state.scores == (0, 0, 0, 0)  # penalty belongs to M4
    assert result.events[0].valid is False


def test_three_of_a_kind_claim_is_false_in_initial_phase():
    # Four-of-five is a five-chit rule; the initial phase needs all four.
    from dataclasses import replace

    config = make_config(4)
    deal = crafted_deal(config, matching={2, 3})  # seats 0 and 1 share all Sun/Moon chits
    pool = [c for h in deal.hands[:2] for c in h]
    sun = [c for c in pool if c.name == "Sun"]
    moon = [c for c in pool if c.name == "Moon"]
    hands = (tuple(sun[:3] + moon[:1]), tuple(moon[1:] + sun[3:]), *deal.hands[2:])
    state = start_from_deal(config, replace(deal, hands=hands)).state
    result = apply_action(state, ClaimAction(0))  # seat 0: three Suns + one Moon
    assert result.state.phase is Phase.FALSE_CLAIM
    assert result.state.false_claimant == 0


def test_claim_by_later_seat_in_order_is_rejected_without_penalty():
    state = start(make_config(4), matching={0, 1, 2, 3})
    for seat in (1, 2, 3):
        before = state
        result = apply_action(state, ClaimAction(seat))
        assert isinstance(result, Rejected)
        assert result.reason is RejectionReason.NOT_DECISION_POINT
        assert state == before
        assert state.scores == (0, 0, 0, 0) and state.phase is Phase.INITIAL_CLAIMS


def test_claim_by_seat_that_already_declined_is_rejected():
    state = start(make_config(4), matching={0, 1, 2, 3})
    state, _ = decline_all_but(state, apply_action, 2)  # seats 0 and 1 declined
    before = state
    for seat in (0, 1):
        result = apply_action(state, ClaimAction(seat))
        assert isinstance(result, Rejected) and result.reason is RejectionReason.NOT_DECISION_POINT
    assert state == before


def test_decline_out_of_turn_is_rejected_and_changes_nothing():
    state = start(make_config(4))
    result = apply_action(state, DeclineAction(2))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.NOT_DECISION_POINT
    assert state.decision_seat == 0 and state.initial_claims_resolved == 0 and state.next_seq == 1


def test_first_valid_claim_fixes_winner_and_later_claims_cannot_replace_it():
    state = start(make_config(4), matching={0, 1, 2, 3})
    state, _ = decline_all_but(state, apply_action, 1)
    won = apply_action(state, ClaimAction(1)).state
    assert won.phase is Phase.WIN_DECLARED and won.winner == 1
    for seat in range(4):
        for action in (ClaimAction(seat), DeclineAction(seat)):
            result = apply_action(won, action)
            assert isinstance(result, Rejected)
            assert result.reason is RejectionReason.PHASE_NOT_ACCEPTING
    assert won.winner == 1


def test_no_actions_after_false_claim():
    state = start(make_config(4))
    over = apply_action(state, ClaimAction(0)).state
    assert over.phase is Phase.FALSE_CLAIM
    result = apply_action(over, ClaimAction(1))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.PHASE_NOT_ACCEPTING
    assert over.false_claimant == 0


# --- invalid input ----------------------------------------------------------

@pytest.mark.parametrize("seat", [-1, 4, 99, True, False, 1.0, "0", None, (0,)])
@pytest.mark.parametrize("action_type", [ClaimAction, DeclineAction])
def test_invalid_seats_rejected_without_state_change(seat, action_type):
    state = start(make_config(4))
    result = apply_action(state, action_type(seat))
    assert isinstance(result, Rejected)
    assert result.reason is RejectionReason.INVALID_SEAT
    assert state.next_seq == 1 and state.initial_claims_resolved == 0


@pytest.mark.parametrize("action", [None, "claim", 0, {"seat": 0}, object(), ClaimAction, ("claim", 0)])
def test_unrecognized_actions_rejected(action):
    state = start(make_config(4))
    result = apply_action(state, action)
    assert isinstance(result, Rejected) and result.reason is RejectionReason.UNKNOWN_ACTION


def test_apply_action_requires_a_game_state():
    with pytest.raises(TypeError):
        apply_action("not a state", ClaimAction(0))


def test_states_are_immutable():
    from dataclasses import FrozenInstanceError

    state = start(make_config(4))
    with pytest.raises(FrozenInstanceError):
        state.phase = Phase.PASSING  # type: ignore[misc]


def test_accepted_action_does_not_mutate_previous_state():
    state = start(make_config(4))
    snapshot = (state.decision_seat, state.initial_claims_resolved, state.next_seq, state.phase)
    apply_action(state, DeclineAction(0))
    assert (state.decision_seat, state.initial_claims_resolved, state.next_seq, state.phase) == snapshot


# --- sequencing and randomized walk ----------------------------------------

def test_event_sequence_numbers_are_contiguous_across_a_game():
    result = new_game(make_config(4))
    state, seqs = result.state, [e.seq for e in result.events]
    while state.phase is Phase.INITIAL_CLAIMS:
        step = apply_action(state, DeclineAction(state.decision_seat))
        state = step.state
        seqs.extend(e.seq for e in step.events)
    assert seqs == list(range(len(seqs)))
    assert state.next_seq == len(seqs)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_random_walks_keep_invariants_and_terminate(n):
    rng = random.Random(1234 + n)
    for seed in range(40):
        state = new_game(GameConfig(n, n, seed=seed)).state
        steps = 0
        while state.phase is Phase.INITIAL_CLAIMS:
            action = (ClaimAction if rng.random() < 0.25 else DeclineAction)(state.decision_seat)
            state = apply_action(state, action).state
            check_invariants(state)
            steps += 1
            assert steps <= n
        assert state.phase in (Phase.PASSING, Phase.WIN_DECLARED, Phase.FALSE_CLAIM)
        assert state.scores == (0,) * n
        assert all(len(h) == 4 for h in state.hands)


def test_outcome_matches_actual_hand_over_many_real_deals():
    # Real seeded deals: a claim is a win exactly when the claimant's four chits share a name.
    for seed in range(300):
        state = new_game(GameConfig(4, 4, seed=seed)).state
        hand = state.hands[0]
        result = apply_action(state, ClaimAction(0)).state
        expected = Phase.WIN_DECLARED if len({c.name for c in hand}) == 1 else Phase.FALSE_CLAIM
        assert result.phase is expected
