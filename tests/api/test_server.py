"""WebSocket protocol tests with several concurrent clients (Starlette TestClient)."""

from __future__ import annotations

import json
import time
from contextlib import ExitStack

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chitai.api.server import create_app, origin_allowed

from .support import SEED, policy


@pytest.fixture
def client():
    app = create_app(seed_factory=lambda: SEED)
    with TestClient(app) as c:
        c.app_manager = app.state.manager
        yield c


def open_ws(client, **kwargs):
    return client.websocket_connect("/ws", **kwargs)


def create(ws, name="Host", n=4, rounds=None, timeout=15):
    ws.send_json({"type": "create_room", "name": name, "num_players": n,
                  "num_rounds": n if rounds is None else rounds, "timeout_seconds": timeout})
    msg = ws.receive_json()
    assert msg["type"] == "state", msg
    return msg


def join(ws, code, name):
    ws.send_json({"type": "join_room", "code": code, "name": name})
    return ws.receive_json()


def table(client, stack, n=4, rounds=None, timeout=15):
    """Open n connections, create a room and fill it. Returns (sockets, latest messages)."""
    sockets = [stack.enter_context(open_ws(client)) for _ in range(n)]
    first = create(sockets[0], "P0", n, rounds, timeout)
    code = first["room"]["code"]
    latest = [first]
    for i in range(1, n):
        latest.append(join(sockets[i], code, f"P{i}"))
        for j in range(i):  # everyone already seated hears about the newcomer
            latest[j] = sockets[j].receive_json()
    return sockets, latest, code


def test_index_and_static_files_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "ChitAI" in page.text
    script = client.get("/static/app.js")
    assert script.status_code == 200 and "authoritative" in script.text
    assert client.get("/docs").status_code == 404


def test_create_room_returns_a_code_and_the_lobby(client):
    with open_ws(client) as ws:
        msg = create(ws, "Ann", 5, 10, 8)
    assert len(msg["room"]["code"]) == 4 and msg["room"]["status"] == "lobby"
    assert msg["me"] == {"seat": 0, "name": "Ann", "is_host": True}
    assert msg["observation"] is None and msg["room"]["num_rounds"] == 10
    assert "token" not in json.dumps(msg) and str(SEED) not in json.dumps(msg)


def test_join_start_and_per_seat_first_state(client):
    with ExitStack() as stack:
        sockets, latest, code = table(client, stack)
        sockets[0].send_json({"type": "start_game"})
        states = [ws.receive_json() for ws in sockets]
    assert [s["me"]["seat"] for s in states] == [0, 1, 2, 3]
    assert [s["room"]["status"] for s in states] == ["playing"] * 4
    assert [bool(s["legal_actions"]) for s in states] == [True, False, False, False]
    hands = [s["observation"]["my_hand"] for s in states]
    assert all(len(h) == 4 for h in hands)
    for seat, state in enumerate(states):  # the deal event carries only the recipient's own hand
        (deal,) = [e for e in state["events"] if e["type"] == "deal"]
        assert deal["my_hand"] == hands[seat]
        assert str(SEED) not in json.dumps(state)


def test_join_errors(client):
    with open_ws(client) as host, open_ws(client) as guest:
        code = create(host, "Host", 4)["room"]["code"]
        assert join(guest, "ZZZZ", "G")["message"] == "No room with that code."
        assert join(guest, 123, "G")["type"] == "error"
        assert join(guest, code.lower(), "")["type"] == "error"
        assert join(guest, code.lower(), "host")["message"].startswith("That name")
        ok = join(guest, code.lower(), "Guest")  # codes are case-insensitive
        assert ok["type"] == "state" and ok["me"]["seat"] == 1
        guest.send_json({"type": "join_room", "code": code, "name": "Again"})
        assert guest.receive_json()["message"] == "You are already in a room."


def test_room_full_and_late_join(client):
    with ExitStack() as stack:
        sockets, _, code = table(client, stack)
        extra = stack.enter_context(open_ws(client))
        assert join(extra, code, "Extra")["message"] == "This room is full."
        sockets[0].send_json({"type": "start_game"})
        for ws in sockets:
            ws.receive_json()
        assert join(extra, code, "Extra")["message"] in ("This game has already started.", "This room is full.")


def test_only_the_host_starts_and_only_when_full(client):
    with open_ws(client) as host, open_ws(client) as guest:
        code = create(host, "Host", 4)["room"]["code"]
        join(guest, code, "Guest")
        host.receive_json()
        guest.send_json({"type": "start_game"})
        assert "host" in guest.receive_json()["message"]
        host.send_json({"type": "start_game"})
        assert "Waiting for players" in host.receive_json()["message"]


@pytest.mark.parametrize(
    "raw",
    ["not json", "[]", "5", '{"no_type": 1}', '{"type": 5}', '{"type": "nope"}',
     '{"type": "timeout"}', '{"type": "action", "action": "decline"}', '{"type": "start_game"}',
     "x" * 5000],
)
def test_malformed_or_unauthorised_messages_get_an_error_and_do_not_crash(client, raw):
    with open_ws(client) as ws:
        ws.send_text(raw)
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "create_room", "name": "Still works", "num_players": 4, "num_rounds": 4})
        assert ws.receive_json()["type"] == "state"


@pytest.mark.parametrize(
    "settings",
    [{"num_players": 3}, {"num_players": 9}, {"num_players": "4"}, {"num_players": 4, "num_rounds": 6},
     {"num_players": 4, "num_rounds": 0}, {"num_players": 4, "timeout_seconds": 99},
     {"num_players": 4, "timeout_seconds": "x"}, {"num_players": 4, "timeout_seconds": 0}],
)
def test_invalid_room_settings_are_refused(client, settings):
    with open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "A", **settings})
        assert ws.receive_json()["type"] == "error"
    assert not client.app_manager.rooms


def test_clients_cannot_submit_timeouts_or_choose_a_seat(client):
    with ExitStack() as stack:
        sockets, _, _ = table(client, stack)
        sockets[0].send_json({"type": "start_game"})
        for ws in sockets:
            ws.receive_json()
        for payload in ({"type": "action", "action": "timeout"},
                        {"type": "action", "action": "TimeoutAction", "seat": 0},
                        {"type": "timeout", "seat": 0},
                        {"type": "action", "action": "decline", "seat": 0}):
            sockets[1].send_json(payload)
            assert sockets[1].receive_json()["type"] == "error"
        # nothing changed for anyone: seat 0 can still act
        sockets[0].send_json({"type": "action", "action": "decline"})
        assert [ws.receive_json()["observation"]["decision_seat"] for ws in sockets] == [1, 1, 1, 1]


def play_full_game(client, n=4, rounds=None, always_claim=False, limit=20000):
    with ExitStack() as stack:
        sockets, latest, _ = table(client, stack, n, rounds)
        sockets[0].send_json({"type": "start_game"})
        latest = [ws.receive_json() for ws in sockets]
        history = [latest]
        for _ in range(limit):
            if latest[0]["room"]["status"] == "finished":
                return history
            actor = next(i for i, m in enumerate(latest) if m["legal_actions"])
            sockets[actor].send_json(policy(latest[actor], always_claim))
            latest = [ws.receive_json() for ws in sockets]
            assert all(m["type"] == "state" for m in latest), latest
            history.append(latest)
        raise AssertionError("game did not finish")


def test_four_browsers_play_a_complete_game_over_websockets(client):
    history = play_full_game(client, 4, 4)
    final = history[-1]
    assert [m["room"]["status"] for m in final] == ["finished"] * 4
    assert all(m["standings"] == final[0]["standings"] for m in final)  # standings are public
    kinds = {e["type"] for step in history for e in step[0]["events"]}
    assert {"valid_win_scored", "round_completed", "game_completed"} <= kinds
    for step in history:  # privacy over the whole game, on the wire
        for seat, msg in enumerate(step):
            text = json.dumps(msg)
            assert str(SEED) not in text and '"copy"' not in text and '"hands"' not in text
            for ev in msg["events"]:
                if ev["type"] == "chit_passed":
                    assert ("chit_name" in ev) == (seat in (ev["from_seat"], ev["to_seat"]))


def test_false_claims_complete_rounds_over_websockets(client):
    history = play_full_game(client, 4, 8, always_claim=True)
    kinds = [e["type"] for step in history for e in step[0]["events"]]
    assert "false_claim_penalized" in kinds and kinds.count("round_completed") == 8


def test_a_server_timer_resolves_a_silent_player_and_never_claims(client):
    with ExitStack() as stack:
        sockets, _, _ = table(client, stack, 4, 4, timeout=0.05)
        sockets[0].send_json({"type": "start_game"})
        seen = []
        for _ in range(12):  # nobody acts: the server times every decision out
            seen += [e["type"] for e in sockets[0].receive_json()["events"]]
            if seen.count("decision_timed_out") >= 6 and "chit_passed" in seen:
                break
        assert seen.count("decision_timed_out") >= 6
        assert "chit_passed" in seen
        assert not {"claim_made", "initial_claim_made"} & set(seen)


def test_a_timer_message_carries_the_countdown_for_the_decision_seat(client):
    with ExitStack() as stack:
        sockets, _, _ = table(client, stack)
        sockets[0].send_json({"type": "start_game"})
        msg = sockets[2].receive_json()
        assert msg["timer"]["seat"] == 0 and 0 < msg["timer"]["seconds_left"] <= 15


def test_disconnect_is_reported_and_the_game_continues(client):
    with ExitStack() as stack:
        sockets, _, _ = table(client, stack)
        sockets[0].send_json({"type": "start_game"})
        for ws in sockets:
            ws.receive_json()
        sockets[3].close()
        for ws in sockets[:3]:
            msg = ws.receive_json()
            assert [p["connected"] for p in msg["room"]["players"]] == [True, True, True, False]
        sockets[0].send_json({"type": "action", "action": "decline"})
        assert sockets[1].receive_json()["type"] == "state"


def wait_for(predicate, seconds=2.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_empty_rooms_are_removed(client):
    with open_ws(client) as ws:
        create(ws, "Solo", 4)
        assert len(client.app_manager.rooms) == 1
    assert wait_for(lambda: not client.app_manager.rooms)


def test_leaving_the_lobby_promotes_the_next_player(client):
    with open_ws(client) as host, open_ws(client) as guest:
        code = create(host, "Host", 4)["room"]["code"]
        join(guest, code, "Guest")
        host.receive_json()
        host.close()
        msg = guest.receive_json()
        assert [(p["name"], p["is_host"]) for p in msg["room"]["players"]] == [("Guest", True)]
        assert msg["me"]["is_host"] is True


# ------------------------------------------------------------- origin checks
def test_a_foreign_origin_is_rejected_and_same_origin_accepted(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
            pass
    with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        ws.send_json({"type": "create_room", "name": "A", "num_players": 4, "num_rounds": 4})
        assert ws.receive_json()["type"] == "state"


@pytest.mark.parametrize(
    "origin, host, expected",
    [(None, "127.0.0.1:8000", True), ("http://127.0.0.1:8000", "127.0.0.1:8000", True),
     ("http://localhost:8000", "127.0.0.1:8000", False), ("http://evil.example", "127.0.0.1:8000", False),
     ("http://127.0.0.1:8000", None, False), ("null", "127.0.0.1:8000", False)],
)
def test_origin_allowed(origin, host, expected):
    assert origin_allowed(origin, host, frozenset()) is expected


def test_the_server_binds_to_loopback_by_default():
    from pathlib import Path
    source = (Path(__file__).parents[2] / "src" / "chitai" / "api" / "__main__.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in source and "0.0.0.0" not in source
