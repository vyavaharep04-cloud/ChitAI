"""M3: claims during ordinary passing (four-of-five for receivers, four-of-four on return)."""

import json

import pytest

from chitai.engine import (
    ClaimAction,
    ClaimMade,
    DecisionKind,
    PassAction,
    Phase,
    Rejected,
    RejectionReason,
    apply_action,
    check_invariants,
    is_valid_claim,
    is_valid_receiver_claim,
    legal_actions,
)

from .helpers import (
    all_names_json_free,
    deal_from_names,
    do_pass,
    make_config,
    start_deal,
    decline_to_passing,
)

S, M, T, C = "Sun", "Moon", "Star", "Cloud"  # the four names used by a 4-player deal


def four_player_state(*hands):
    config = make_config(4)
    return decline_to_passing(start_deal(config, deal_from_names(config, hands)))


def claim(state, seat=None):
    result = apply_action(state, ClaimAction(state.decision_seat if seat is None else seat))
    assert not isinstance(result, Rejected), result
    return result


# --- pure rule: four of five ---------------------------------------------------------

def chits(*names):
    from chitai.engine import Chit

    seen: dict[str, int] = {}
    out = []
    for name in names:
        out.append(Chit(name, seen.get(name, 0)))
        seen[name] = seen.get(name, 0) + 1
    return tuple(out)


@pytest.mark.parametrize(
    "names,expected",
    [
        ((S, S, S, S, M), True),  # four plus an odd one
        ((M, S, S, S, S), True),  # the four need not be adjacent
        ((S, M, S, S, S), True),
        ((S, S, S, M, M), False),  # three plus a pair
        ((S, S, M, M, T), False),  # two pairs
        ((S, S, S, M, T), False),  # three of a kind
        ((S, M, T, C, S), False),
    ],
)
def test_receiver_claim_requires_four_of_five_same_name(names, expected):
    assert is_valid_receiver_claim(chits(*names)) is expected
    assert is_valid_claim(DecisionKind.NON_INITIATOR_RECEIVE, chits(*names)) is expected


def test_receiver_rule_needs_five_chits_and_initial_rule_needs_four():
    with pytest.raises(ValueError):
        is_valid_receiver_claim(chits(S, S, S, S))
    with pytest.raises(ValueError):
        is_valid_claim(DecisionKind.INITIATOR_RETURN, chits(S, S, S, S, M))
    with pytest.raises(ValueError):
        is_valid_claim(DecisionKind.INITIATOR_FIRST_PASS, chits(S, S, S, S))


def test_matching_uses_names_not_copy_indexes():
    from chitai.engine import Chit

    assert is_valid_receiver_claim((Chit(S, 3), Chit(S, 0), Chit(S, 2), Chit(S, 1), Chit(M, 0)))


# --- receiver claims -------------------------------------------------------------------

def test_receiver_wins_when_the_received_chit_completes_four():
    # Seat 1 holds Moon x3 + Sun; seat 0 passes it its fourth Moon.
    state = four_player_state([S, S, S, M], [M, M, M, S], [T] * 4, [C] * 4)
    moon = next(c for c in state.hands[0] if c.name == M)
    state, _ = do_pass(state, moon)
    assert len(state.hands[1]) == 5
    result = claim(state)
    won = result.state
    assert won.phase is Phase.WIN_DECLARED and won.winner == 1 and won.false_claimant is None
    assert won.claim_decision_kind is DecisionKind.NON_INITIATOR_RECEIVE
    assert [(type(e), e.valid) for e in result.events] == [(ClaimMade, True)]
    assert won.decision_seat is None and won.decision_kind is None
    check_invariants(won)


def test_receiver_wins_when_the_four_matching_were_already_held():
    # Seat 1 already holds four Moon; seat 0 sends an unrelated Sun.
    state = four_player_state([S, S, S, S], [M] * 4, [T] * 4, [C] * 4)
    state, _ = do_pass(state)
    assert sorted(c.name for c in state.hands[1]) == [M, M, M, M, S]
    assert claim(state).state.phase is Phase.WIN_DECLARED


def test_receiver_false_claim_with_three_of_a_kind():
    # Seat 1 holds M,M,T,T and receives a third Moon: three of a kind plus a pair.
    state = four_player_state([S, S, S, M], [M, M, T, T], [S, C, C, C], [M, T, T, C])
    state, _ = do_pass(state, next(c for c in state.hands[0] if c.name == M))
    assert sorted(c.name for c in state.hands[1]) == [M, M, M, T, T]
    result = claim(state)
    lost = result.state
    # M4: the false claim is penalized and the round completes (details in test_false_claims.py).
    assert result.events[0].seat == 1
    assert [(type(e), e.valid) for e in result.events[:1]] == [(ClaimMade, False)]
    assert lost.phase is Phase.INITIAL_CLAIMS and lost.scores == (0, -3, 0, 0)
    assert lost.completed_rounds == 1 and lost.false_claimant is None and lost.winner is None
    check_invariants(lost)


def test_false_claim_applies_the_penalty_and_completes_the_round():
    # M3 held this state back; M4 applies the -(N-1) penalty and completes the round.
    state = four_player_state([S, S, M, M], [T, T, C, C], [S, S, M, M], [T, T, C, C])
    state, _ = do_pass(state)
    lost = claim(state).state
    assert lost.scores == (0, -3, 0, 0)
    assert lost.completed_rounds == 1 and lost.attempt == 1


def test_receiver_with_a_matching_hand_is_never_claimed_for():
    state = four_player_state([S, S, S, S], [M] * 4, [T] * 4, [C] * 4)
    state, _ = do_pass(state)
    # the engine waits for an explicit action even though seat 1 could win
    assert state.phase is Phase.PASSING and state.decision_seat == 1 and state.winner is None
    assert ClaimAction(1) in legal_actions(state)


# --- initiator-return claims --------------------------------------------------------------

def test_initiator_wins_on_return_with_four_of_a_kind():
    # Seat 0 sends its only Moon. Seat 1 now holds four Moon and one Sun and
    # forwards the Sun; it travels clockwise and completes seat 0's four Suns.
    state = four_player_state([S, S, S, M], [M, M, M, S], [T] * 4, [C] * 4)
    state, _ = do_pass(state, next(c for c in state.hands[0] if c.name == M))
    state, _ = do_pass(state, next(c for c in state.hands[1] if c.name == S))
    state, _ = do_pass(state, next(c for c in state.hands[2] if c.name == S))
    state, _ = do_pass(state, next(c for c in state.hands[3] if c.name == S))
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN and state.decision_seat == 0
    assert [c.name for c in state.hands[0]] == [S, S, S, S]
    result = claim(state)
    won = result.state
    assert won.phase is Phase.WIN_DECLARED and won.winner == 0
    assert won.claim_decision_kind is DecisionKind.INITIATOR_RETURN
    assert len(won.hands[0]) == 4
    check_invariants(won)


def test_initiator_false_claim_on_return_with_three_of_a_kind():
    state = four_player_state([S, S, S, M], [T, T, T, T], [M, M, M, S], [C] * 4)
    state, _ = do_pass(state, next(c for c in state.hands[0] if c.name == M))
    for _ in range(3):
        state, _ = do_pass(state)
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    assert len({c.name for c in state.hands[0]}) > 1
    result = claim(state)
    lost = result.state
    assert result.events[0].seat == 0 and result.events[0].valid is False
    assert lost.scores == (-3, 0, 0, 0) and lost.completed_rounds == 1
    assert lost.phase is Phase.INITIAL_CLAIMS and lost.initiator == 1
    check_invariants(lost)


# --- after a claim ------------------------------------------------------------------------

@pytest.mark.parametrize("valid", [True, False])
def test_no_actions_are_accepted_after_a_passing_phase_claim(valid):
    if valid:
        state = four_player_state([S, S, S, M], [M, M, M, S], [T] * 4, [C] * 4)
        state, _ = do_pass(state, next(c for c in state.hands[0] if c.name == M))
    else:
        state = four_player_state([S, S, M, M], [T, T, C, C], [S, S, M, M], [T, T, C, C])
        state, _ = do_pass(state)
    over = claim(state).state
    if valid:
        assert over.phase is Phase.WIN_DECLARED
        assert legal_actions(over) == ()
    else:
        # M4: a false claim completes the round, so play simply continues; the
        # end-of-game case is covered in test_false_claims.py.
        assert over.phase is Phase.INITIAL_CLAIMS
        return
    for seat in range(4):
        for action in (ClaimAction(seat), PassAction(seat, over.hands[seat][0])):
            result = apply_action(over, action)
            assert isinstance(result, Rejected)
            assert result.reason is RejectionReason.PHASE_NOT_ACCEPTING


def test_the_first_valid_claim_fixes_the_winner():
    state = four_player_state([S, S, S, M], [M, M, M, S], [T] * 4, [C] * 4)
    state, _ = do_pass(state, next(c for c in state.hands[0] if c.name == M))
    won = claim(state).state
    assert won.winner == 1
    for seat in (0, 2, 3):
        assert isinstance(apply_action(won, ClaimAction(seat)), Rejected)
    assert won.winner == 1 and won.scores == (0,) * 4


def test_passing_phase_claim_event_privacy():
    state = four_player_state([S, S, S, M], [M, M, M, S], [T] * 4, [C] * 4)
    state, _ = do_pass(state, next(c for c in state.hands[0] if c.name == M))
    hand = state.hands[1]
    event = claim(state).events[0]
    pub, dbg = event.public_view(), event.debug_view()
    assert pub["type"] == "claim_made" and pub["seat"] == 1 and pub["valid"] is True
    assert "hand" not in pub and all_names_json_free(pub)
    assert [(c["name"], c["copy"]) for c in dbg["hand"]] == [(c.name, c.copy) for c in hand]
    json.dumps(pub)
    json.dumps(dbg)


def test_claim_event_sequence_and_state_counters():
    state = four_player_state([S, S, M, M], [T, T, C, C], [S, S, M, M], [T, T, C, C])
    state, _ = do_pass(state)
    seq = state.next_seq
    result = claim(state)
    assert result.events[0].seq == seq
    assert result.state.next_seq == seq + len(result.events)  # contiguous (M4 adds events)
    assert result.events[0].completed_round == 0 and result.events[0].attempt == 1
