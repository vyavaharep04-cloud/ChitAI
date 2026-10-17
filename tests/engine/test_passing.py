"""M3: sequential clockwise passing, atomic delivery, and the §3A.4 hand-size table."""

import json

import pytest

from chitai.engine import (
    ChitPassed,
    ClaimAction,
    DeclineAction,
    DecisionKind,
    GameConfig,
    PassAction,
    Phase,
    Rejected,
    RejectionReason,
    apply_action,
    build_deck,
    check_invariants,
    legal_actions,
    new_game,
)

from .helpers import all_names_json_free, do_pass, make_config, start, to_passing

PLAYER_COUNTS = [4, 5, 6, 7, 8]


def sizes(state):
    return [len(h) for h in state.hands]


# --- first pass ---------------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_first_pass_state_has_all_hands_of_four_and_no_claim_opportunity(n):
    state = to_passing(make_config(n))
    assert state.phase is Phase.PASSING
    assert state.decision_kind is DecisionKind.INITIATOR_FIRST_PASS
    assert state.decision_seat == state.initiator
    assert sizes(state) == [4] * n
    actions = legal_actions(state)
    assert not any(isinstance(a, ClaimAction) for a in actions)
    assert actions == tuple(PassAction(state.initiator, c) for c in state.hands[state.initiator])
    assert len(actions) == 4


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_initiator_pass_leaves_three_and_gives_next_seat_five(n):
    for round_index in range(n):  # every initiator, including wraparound
        state = to_passing(make_config(n), completed_round=round_index)
        initiator = state.initiator
        chit = state.hands[initiator][2]
        after, events = do_pass(state, chit)
        receiver = (initiator + 1) % n
        assert chit not in after.hands[initiator] and chit in after.hands[receiver]
        assert after.hands[receiver][-1] == chit
        assert len(after.hands[initiator]) == 3
        assert len(after.hands[receiver]) == 5
        assert all(len(after.hands[s]) == 4 for s in range(n) if s not in (initiator, receiver))
        assert after.decision_seat == receiver
        assert after.decision_kind is DecisionKind.NON_INITIATOR_RECEIVE
        assert sum(sizes(after)) == 4 * n
        assert [type(e) for e in events] == [ChitPassed]
        assert (events[0].from_seat, events[0].to_seat, events[0].chit) == (initiator, receiver, chit)


# --- the full cycle -----------------------------------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_pass_cycle_walks_clockwise_and_returns_to_initiator_after_n_passes(n):
    for round_index in range(n):
        state = to_passing(make_config(n), completed_round=round_index)
        initiator = state.initiator
        for step in range(n):
            expected_passer = (initiator + step) % n
            assert state.decision_seat == expected_passer
            state, _ = do_pass(state)
            check_invariants(state)
            if step < n - 1:
                assert state.decision_kind is DecisionKind.NON_INITIATOR_RECEIVE
                assert state.decision_seat == (initiator + step + 1) % n
                expected = [4] * n
                expected[initiator] = 3
                expected[state.decision_seat] = 5
                assert sizes(state) == expected
        assert state.decision_seat == initiator
        assert state.decision_kind is DecisionKind.INITIATOR_RETURN
        assert sizes(state) == [4] * n


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_initiator_passes_again_after_return_and_cycle_repeats(n):
    state = to_passing(make_config(n))
    for _ in range(n):
        state, _ = do_pass(state)
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    again, _ = do_pass(state)  # the initiator passes rather than claiming
    assert again.phase is Phase.PASSING
    assert again.decision_seat == (state.initiator + 1) % n
    assert again.decision_kind is DecisionKind.NON_INITIATOR_RECEIVE
    assert len(again.hands[state.initiator]) == 3
    assert len(again.hands[again.decision_seat]) == 5


def test_returning_chit_need_not_be_the_one_the_initiator_sent():
    state = to_passing(make_config(4))
    sent = state.hands[0][0]
    state, _ = do_pass(state, sent)
    # seat 1 passes a chit of its own instead of forwarding `sent`
    own = state.hands[1][0]
    assert own != sent
    state, _ = do_pass(state, own)
    state, _ = do_pass(state)
    state, _ = do_pass(state)
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    assert sent not in state.hands[0]


def test_receiver_may_pass_the_chit_it_just_received():
    state = to_passing(make_config(4))
    sent = state.hands[0][1]
    state, _ = do_pass(state, sent)
    assert sent in legal_pass_chits(state)
    state, _ = do_pass(state, sent)
    assert sent in state.hands[2] and sent not in state.hands[1]
    assert len(state.hands[1]) == 4


def legal_pass_chits(state):
    return [a.chit for a in legal_actions(state) if isinstance(a, PassAction)]


# --- legal actions per decision point (§3A.4 table) -----------------------------

def test_legal_actions_for_receive_and_return_include_claim_and_every_held_chit():
    state = to_passing(make_config(4))
    state, _ = do_pass(state)
    actions = legal_actions(state)
    assert actions[0] == ClaimAction(1)
    assert [a.chit for a in actions[1:]] == list(state.hands[1]) and len(actions) == 6  # claim + 5
    for _ in range(3):
        state, _ = do_pass(state)
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    actions = legal_actions(state)
    assert actions[0] == ClaimAction(0)
    assert [a.chit for a in actions[1:]] == list(state.hands[0]) and len(actions) == 5  # claim + 4


def test_claim_opportunity_does_not_depend_on_the_hand_matching():
    # Seat 1 starts with four of a kind; seat 2 does not. Both get a claim
    # opportunity when they receive a chit, and neither is claimed for them.
    state = to_passing(make_config(4), matching={1})
    state, _ = do_pass(state)
    assert state.decision_seat == 1 and ClaimAction(1) in legal_actions(state)
    state, _ = do_pass(state, name=state.hands[1][-1].name)  # seat 1 passes instead of claiming
    assert state.phase is Phase.PASSING and state.decision_seat == 2
    assert ClaimAction(2) in legal_actions(state)


# --- hand-size table across every n and initiator --------------------------------

@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_total_chits_and_copies_preserved_through_many_passes(n):
    state = to_passing(make_config(n))
    deck = set(build_deck(n))
    for step in range(3 * n):
        state, _ = do_pass(state, state.hands[state.decision_seat][step % 4])
        held = [c for h in state.hands for c in h]
        assert len(held) == 4 * n and set(held) == deck
    assert state.scores == (0,) * n
    assert state.completed_rounds == 0 and state.attempt == 1


# --- rejections ---------------------------------------------------------------------

def test_pass_by_a_seat_that_is_not_the_decision_point_is_rejected():
    state = to_passing(make_config(4))
    for seat in (1, 2, 3):
        chit = state.hands[seat][0]
        before = state
        result = apply_action(state, PassAction(seat, chit))
        assert isinstance(result, Rejected)
        assert result.reason is RejectionReason.NOT_DECISION_POINT
        assert state == before


def test_pass_of_a_chit_the_seat_does_not_hold_is_rejected():
    state = to_passing(make_config(4))
    foreign = state.hands[1][0]
    for bad in (foreign, "Sun", None, 3, ("Sun", 0)):
        before = state
        result = apply_action(state, PassAction(0, bad))
        assert isinstance(result, Rejected)
        assert result.reason is RejectionReason.CHIT_NOT_HELD
        assert state == before and state.next_seq == before.next_seq


def test_initiator_cannot_pass_a_chit_it_no_longer_holds_after_the_return():
    state = to_passing(make_config(4))
    for _ in range(4):
        state, _ = do_pass(state)  # chit travels all the way back to the initiator
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN
    not_held = next(c for c in build_deck(4) if c not in state.hands[0])
    before = state
    result = apply_action(state, PassAction(0, not_held))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.CHIT_NOT_HELD
    assert state == before


@pytest.mark.parametrize("seat", [-1, 4, 99, True, 1.0, "0", None])
def test_pass_with_invalid_seat_is_rejected(seat):
    state = to_passing(make_config(4))
    result = apply_action(state, PassAction(seat, state.hands[0][0]))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.INVALID_SEAT


def test_decline_does_not_exist_during_passing():
    state = to_passing(make_config(4))
    state, _ = do_pass(state)  # seat 1 now holds five
    for seat in range(4):
        result = apply_action(state, DeclineAction(seat))
        assert isinstance(result, Rejected)
        expected = (
            RejectionReason.ACTION_NOT_AVAILABLE
            if seat == state.decision_seat
            else RejectionReason.NOT_DECISION_POINT
        )
        assert result.reason is expected


def test_pass_is_rejected_during_the_initial_claim_phase():
    state = start(make_config(4))
    before = state
    result = apply_action(state, PassAction(0, state.hands[0][0]))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.ACTION_NOT_AVAILABLE
    assert state == before


def test_pass_is_rejected_after_a_claim_has_ended_the_attempt():
    state = start(make_config(4))
    over = apply_action(state, ClaimAction(0)).state  # false claim -> holding phase
    result = apply_action(over, PassAction(0, over.hands[0][0]))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.PHASE_NOT_ACCEPTING


def test_initiator_cannot_claim_at_first_pass_and_no_penalty_is_applied():
    state = to_passing(make_config(4))
    result = apply_action(state, ClaimAction(state.initiator))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.NO_CLAIM_OPPORTUNITY
    assert state.phase is Phase.PASSING and state.scores == (0,) * 4 and state.false_claimant is None


def test_initiator_cannot_claim_while_holding_three():
    state = to_passing(make_config(4))
    state, _ = do_pass(state)  # initiator now holds three; seat 1 decides
    assert len(state.hands[0]) == 3
    result = apply_action(state, ClaimAction(0))
    assert isinstance(result, Rejected) and result.reason is RejectionReason.NOT_DECISION_POINT


def test_non_initiator_cannot_claim_outside_its_receive_decision():
    state = to_passing(make_config(4))
    state, _ = do_pass(state)  # seat 1 decides; seats 2 and 3 hold four and may not claim
    for seat in (2, 3):
        result = apply_action(state, ClaimAction(seat))
        assert isinstance(result, Rejected) and result.reason is RejectionReason.NOT_DECISION_POINT
        assert state.phase is Phase.PASSING and state.scores == (0,) * 4


def test_rejections_consume_no_sequence_numbers():
    state = to_passing(make_config(4))
    seq = state.next_seq
    apply_action(state, ClaimAction(0))
    apply_action(state, DeclineAction(0))
    apply_action(state, PassAction(1, state.hands[1][0]))
    apply_action(state, PassAction(0, None))
    after, events = do_pass(state)
    assert events[0].seq == seq and after.next_seq == seq + 1


# --- events and privacy ----------------------------------------------------------------

def test_chit_passed_public_view_hides_the_chit_and_debug_view_shows_it():
    state = to_passing(make_config(4))
    chit = state.hands[0][3]
    _, events = do_pass(state, chit)
    event = events[0]
    pub, dbg = event.public_view(), event.debug_view()
    assert pub["type"] == "chit_passed" and (pub["from_seat"], pub["to_seat"]) == (0, 1)
    assert "chit" not in pub and all_names_json_free(pub)
    assert dbg["chit"] == {"name": chit.name, "copy": chit.copy}
    json.dumps(pub)
    json.dumps(dbg)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_event_sequence_is_contiguous_across_the_whole_pass_cycle(n):
    result = new_game(GameConfig(n, n, seed=3))
    state, seqs = result.state, [e.seq for e in result.events]
    for _ in range(n):
        step = apply_action(state, DeclineAction(state.decision_seat))
        state = step.state
        seqs += [e.seq for e in step.events]
    for _ in range(2 * n):
        state, events = do_pass(state)
        seqs += [e.seq for e in events]
    assert seqs == list(range(len(seqs))) and state.next_seq == len(seqs)


def test_accepted_pass_does_not_mutate_the_previous_state():
    state = to_passing(make_config(4))
    snapshot = (state.hands, state.decision_seat, state.decision_kind, state.next_seq)
    do_pass(state)
    assert (state.hands, state.decision_seat, state.decision_kind, state.next_seq) == snapshot
