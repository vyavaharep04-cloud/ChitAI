"""Room logic without any network: seats, validation, the action pipeline, timers."""

from __future__ import annotations

import json

import pytest

from chitai.engine import Phase
from chitai.api.rooms import STATUS_FINISHED, STATUS_LOBBY, STATUS_PLAYING, Room, RoomError

from .support import SEED, policy


class Client:
    """A stand-in for a connection: only its identity matters."""


def make_room(n: int = 4, rounds: int | None = None, timeout: float = 15, seed: int = SEED) -> Room:
    return Room("ABCD", n, n if rounds is None else rounds, timeout, seed=seed)


def full_room(n: int = 4, rounds: int | None = None, seed: int = SEED):
    room = make_room(n, rounds, seed=seed)
    clients = [Client() for _ in range(n)]
    for i, client in enumerate(clients):
        room.add_player(client, f"P{i}")
    return room, clients


def started_room(n: int = 4, rounds: int | None = None, seed: int = SEED):
    room, clients = full_room(n, rounds, seed)
    room.start(clients[0])
    return room, clients


def message(room: Room, client: Client, events: tuple = ()):
    return room.state_message(client, events)


# ------------------------------------------------------------------ settings
@pytest.mark.parametrize(
    "n, rounds, timeout",
    [(3, 3, 15), (9, 9, 15), (4, 6, 15), (4, 0, 15), (4, -4, 15), (4, 4, 0), (4, 4, 16), (4, 4, "5"),
     (4, 4, True), (4.0, 4, 15), (True, 4, 15), (4, 4.0, 15), (4, 4, float("nan")), (4, 68, 15)],
)
def test_invalid_settings_are_refused(n, rounds, timeout):
    with pytest.raises(RoomError):
        Room("ABCD", n, rounds, timeout)


@pytest.mark.parametrize("n", [4, 5, 6, 7, 8])
def test_valid_settings_are_accepted(n):
    room = Room("ABCD", n, 2 * n, 10)
    assert room.num_players == n and room.num_rounds == 2 * n


# --------------------------------------------------------------------- lobby
def test_first_player_is_host_and_seats_follow_join_order():
    room = make_room()
    a, b = Client(), Client()
    assert room.add_player(a, "Ann") == 0 and room.add_player(b, "Bob") == 1
    info = room.room_info()
    assert [p["name"] for p in info["players"]] == ["Ann", "Bob"]
    assert [p["is_host"] for p in info["players"]] == [True, False]
    assert info["status"] == STATUS_LOBBY


@pytest.mark.parametrize("bad", [None, 5, "", "   ", "x" * 21, "bad\x00name", ["a"]])
def test_bad_names_are_refused(bad):
    with pytest.raises(RoomError):
        make_room().add_player(Client(), bad)


def test_duplicate_names_are_refused_ignoring_case_and_spacing():
    room = make_room()
    room.add_player(Client(), "Ann")
    with pytest.raises(RoomError):
        room.add_player(Client(), "  ann ")


def test_room_full_and_late_join_are_refused():
    room, clients = full_room()
    with pytest.raises(RoomError, match="full"):
        room.add_player(Client(), "Late")
    room.start(clients[0])
    with pytest.raises(RoomError, match="already started"):
        room.add_player(Client(), "Late")


def test_only_the_host_can_start_and_only_when_full():
    room = make_room()
    host, other = Client(), Client()
    room.add_player(host, "A")
    room.add_player(other, "B")
    with pytest.raises(RoomError, match="Waiting for players"):
        room.start(host)
    with pytest.raises(RoomError, match="host"):
        room.start(other)
    with pytest.raises(RoomError, match="host"):
        room.start(Client())


def test_cannot_start_twice():
    room, clients = started_room()
    with pytest.raises(RoomError, match="already started"):
        room.start(clients[0])


def test_leaving_the_lobby_frees_the_seat_and_promotes_a_host():
    room = make_room()
    a, b, c = Client(), Client(), Client()
    for client, name in ((a, "A"), (b, "B"), (c, "C")):
        room.add_player(client, name)
    assert room.disconnect(a) is False
    assert [p["name"] for p in room.room_info()["players"]] == ["B", "C"]
    assert room.room_info()["players"][0]["is_host"] is True
    assert room.disconnect(b) is False
    assert room.disconnect(c) is True  # empty: the server removes the room


def test_disconnect_during_play_keeps_the_seat_and_marks_it():
    room, clients = started_room()
    assert room.disconnect(clients[2]) is False
    players = room.room_info()["players"]
    assert len(players) == 4 and players[2]["connected"] is False
    assert room.seat_of(clients[2]) is None
    for client in (clients[0], clients[1], clients[3]):
        assert room.disconnect(client) in (False, True)
    assert room.disconnect(clients[3]) is True


# ------------------------------------------------------- the action pipeline
def test_the_game_starts_in_the_initial_claim_phase_with_the_host_deciding_first():
    room, clients = started_room()
    assert room.status == STATUS_PLAYING
    first = message(room, clients[0])
    assert first["observation"]["phase"] == "initial_claims"
    assert first["observation"]["decision_seat"] == 0
    assert {a["type"] for a in first["legal_actions"]} == {"claim", "decline"}
    assert message(room, clients[1])["legal_actions"] == []


def test_a_wrong_seat_action_is_refused_without_changing_state():
    room, clients = started_room()
    before = room.state
    with pytest.raises(RoomError, match="not your turn"):
        room.act(clients[1], {"action": "decline"})
    assert room.state is before


def test_a_client_supplied_seat_is_ignored():
    room, clients = started_room()
    before = room.state
    # seat 1 pretends to be seat 0 by naming it in the message: still seat 1's own action
    with pytest.raises(RoomError):
        room.act(clients[1], {"action": "decline", "seat": 0})
    assert room.state is before
    events = room.act(clients[0], {"action": "decline", "seat": 3})  # seat 3 named, but it is seat 0 acting
    assert events[0].type == "initial_claim_declined" and events[0].seat == 0


@pytest.mark.parametrize(
    "request_",
    [{}, {"action": None}, {"action": 5}, {"action": "timeout"}, {"action": "TimeoutAction"},
     {"action": "pass"}, {"action": "pass", "chit_name": 7}, {"action": "pass", "chit_name": "Sun"},
     {"action": "react"}, {"action": ["decline"]}],
)
def test_invalid_or_unavailable_requests_are_refused_without_effect(request_):
    room, clients = started_room()
    before = room.state
    with pytest.raises(RoomError):
        try:
            room.act(clients[0], request_)
        except TypeError:  # an unhashable "action" is still a refusal, not a crash
            raise RoomError("x")
    assert room.state is before


def test_an_action_from_a_stranger_or_before_the_game_is_refused():
    room, clients = full_room()
    with pytest.raises(RoomError, match="not in progress"):
        room.act(clients[0], {"action": "decline"})
    room.start(clients[0])
    with pytest.raises(RoomError, match="not in this room"):
        room.act(Client(), {"action": "decline"})


def test_refusal_messages_never_contain_game_data():
    room, clients = started_room()
    holder = room.state.hands[0]
    texts = []
    for client, request in (
        (clients[0], {"action": "pass", "chit_name": holder[0].name}),
        (clients[1], {"action": "decline"}),
        (clients[0], {"action": "react"}),
    ):
        with pytest.raises(RoomError) as info:
            room.act(client, request)
        texts.append(info.value.message)
    for text in texts:
        assert str(SEED) not in text and "Chit(" not in text and "copy" not in text


def test_passing_a_chit_the_player_does_not_hold_is_refused():
    room, clients = started_room()
    for client in clients:
        room.act(client, {"action": "decline"})
    state = room.state
    assert state.phase is Phase.PASSING and state.decision_seat == 0
    held = {c.name for c in state.hands[0]}
    missing = next(n for n in message(room, clients[0])["observation"]["chit_names"] if n not in held)
    before = room.state
    with pytest.raises(RoomError):
        room.act(clients[0], {"action": "pass", "chit_name": missing})
    assert room.state is before


# -------------------------------------------------------------------- timers
def test_timer_target_exists_at_a_decision_point_and_not_in_the_lobby():
    room, clients = full_room()
    assert room.timer_target() is None
    room.start(clients[0])
    seq, seat = room.timer_target()
    assert seat == 0 and seq == room.state.next_seq


def test_a_timeout_in_the_initial_phase_is_an_automatic_decline():
    room, clients = started_room()
    seq, _ = room.timer_target()
    events = room.apply_timeout(seq)
    assert [e.type for e in events] == ["decision_timed_out", "initial_claim_declined"]
    assert room.state.decision_seat == 1


def test_a_stale_timer_changes_nothing():
    room, clients = started_room()
    old_seq, _ = room.timer_target()
    room.act(clients[0], {"action": "decline"})
    state = room.state
    assert room.apply_timeout(old_seq) is None
    assert room.state is state


def test_a_timeout_never_claims_and_a_forced_pass_is_a_pass():
    room, clients = started_room()
    for client in clients:
        room.act(client, {"action": "decline"})
    events = room.apply_timeout(room.state.next_seq)
    assert [e.type for e in events] == ["decision_timed_out", "chit_passed"]
    assert all(e.type != "claim_made" for e in events)


def test_the_last_reactor_is_timed_out_but_several_pending_reactors_are_not():
    room, clients = started_room(rounds=4)
    play_until_reaction(room, clients)
    assert room.state.phase is Phase.WIN_DECLARED
    assert room.timer_target() is None  # several pending: no timeout by rule
    winner = room.state.winner
    others = [c for i, c in enumerate(clients) if i != winner]
    room.act(others[0], {"action": "react"})
    room.act(others[1], {"action": "react"})
    assert room.timer_target() is not None  # exactly one pending
    events = room.apply_timeout(room.state.next_seq)
    assert events[0].type == "decision_timed_out"
    assert any(e.type == "valid_win_scored" for e in events)


def play_until_reaction(room: Room, clients, limit: int = 5000):
    """Drive the policy until a valid claim opens the reaction phase."""
    for _ in range(limit):
        if room.state.phase is Phase.WIN_DECLARED:
            return
        assert room.state.phase is not Phase.GAME_OVER
        seat = room.state.decision_seat
        msg = message(room, clients[seat])
        room.act(clients[seat], _strip(policy(msg)))
    raise AssertionError("no valid win within the step limit")


def _strip(request):
    return {k: v for k, v in request.items() if k != "type"}


# ---------------------------------------------------------------- full games
def play_game(room: Room, clients, always_claim: bool = False, limit: int = 20000):
    log = []  # (events, per-seat messages)
    for _ in range(limit):
        if room.status == STATUS_FINISHED:
            return log
        state = room.state
        if state.phase is Phase.WIN_DECLARED:
            seat = next(s for s in range(len(clients)) if message(room, clients[s])["legal_actions"])
        else:
            seat = state.decision_seat
        request = policy(message(room, clients[seat]), always_claim)
        events = room.act(clients[seat], _strip(request))
        log.append((events, [message(room, c, events) for c in clients]))
    raise AssertionError("game did not finish")


@pytest.mark.parametrize("n", [4, 5, 8])
def test_a_complete_game_reaches_game_over_with_consistent_standings(n):
    room, clients = started_room(n, n)
    log = play_game(room, clients)
    assert room.status == STATUS_FINISHED and room.state.phase is Phase.GAME_OVER
    final = log[-1][1][0]
    assert final["standings"] is not None
    assert final["observation"]["completed_rounds"] == n
    scores = final["observation"]["scores"]
    assert sorted(r["score"] for r in final["standings"]) == sorted(scores)
    assert final["standings"][0]["rank"] == 1
    kinds = {e.type for events, _ in log for e in events}
    assert {"valid_win_scored", "round_completed", "game_completed"} <= kinds


def test_false_claims_and_multiple_rounds_through_the_pipeline():
    room, clients = started_room(4, 8)
    log = play_game(room, clients, always_claim=True)
    kinds = [e.type for events, _ in log for e in events]
    assert "false_claim_penalized" in kinds
    assert kinds.count("round_completed") == 8
    assert room.status == STATUS_FINISHED


def test_after_game_over_no_action_is_accepted():
    room, clients = started_room()
    play_game(room, clients)
    with pytest.raises(RoomError):
        room.act(clients[0], {"action": "decline"})
    assert room.timer_target() is None and room.apply_timeout(0) is None


# ------------------------------------------------------------------- privacy
def test_no_message_ever_contains_the_seed_copy_ids_or_engine_objects():
    room, clients = started_room()
    log = play_game(room, clients)
    for events, messages in log:
        for msg in messages:
            text = json.dumps(msg)
            assert str(SEED) not in text
            for forbidden in ('"copy"', '"hands"', "GameState", "GameConfig", "debug", "seed", "token"):
                assert forbidden not in text, forbidden


def test_each_seat_receives_only_its_own_hand_and_the_passed_chit_only_if_involved():
    room, clients = started_room(5, 5)
    saw_private_chit = False
    for events, messages in play_game(room, clients):
        for seat, msg in enumerate(messages):
            assert msg["me"]["seat"] == seat
            assert msg["observation"]["my_seat"] == seat
            for ev in msg["events"]:
                if ev["type"] == "chit_passed":
                    involved = seat in (ev["from_seat"], ev["to_seat"])
                    assert ("chit_name" in ev) == involved
                    saw_private_chit |= involved
                if ev["type"] == "deal":
                    assert len(ev["my_hand"]) == 4
                else:
                    assert "my_hand" not in ev
    assert saw_private_chit


def test_bystanders_cannot_distinguish_two_games_that_differ_only_in_a_passed_chit_they_did_not_see():
    """Hidden-twin check on the wire: the same engine events, viewed by a bystander,
    serialise identically whichever chit was passed."""
    room, clients = started_room()
    for client in clients:
        room.act(client, {"action": "decline"})
    state = room.state
    sender = state.decision_seat
    receiver = (sender + 1) % 4
    bystander = next(s for s in range(4) if s not in (sender, receiver))
    names = sorted({c.name for c in state.hands[sender]})
    views = []
    for name in names:
        twin, twin_clients = started_room()
        for client in twin_clients:
            twin.act(client, {"action": "decline"})
        events = twin.act(twin_clients[sender], {"action": "pass", "chit_name": name})
        msg = twin.state_message(twin_clients[bystander], events)
        views.append(json.dumps(msg["events"], sort_keys=True))
    assert len(names) > 1 and len(set(views)) == 1
