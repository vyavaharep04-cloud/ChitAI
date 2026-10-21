"""Human vs AI rooms: configuration, orchestration, privacy and failure handling."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from chitai.api.rooms import (
    AI_AGENTS, STATUS_FINISHED, STATUS_PLAYING, Room, RoomError, parse_seats,
)
from chitai.api.server import create_app
from chitai.engine import Phase
from chitai.observations import Observation, legal_actions_for
from chitai.simulation.runner import _decide, build_agent

from .support import SEED, policy

LINEUP = ["human", "rulebot", "mindbot", "rulebot"]  # the example from the brief
DRAW_SEED = 17  # with the shared human policy this seed produces a draw and a redeal


class Client:
    """Stand-in for a connection (identity only)."""


# ------------------------------------------------------------------ helpers
def make_room(seats, rounds=4, seed=SEED):
    return Room("ABCD", len(seats), rounds, 15, seed=seed, seats=seats)


def seat_humans(room):
    clients = [Client() for _ in range(room.seat_kinds.count("human"))]
    for i, client in enumerate(clients):
        room.add_player(client, f"H{i}")
    return clients


def play_room_with_ais(room, clients, limit=20000, agents=None):
    """Drive a started room: AI seats through the same calls the server uses, humans
    through the shared policy. Returns every event in order."""
    agents = agents or {seat: build_agent(spec) for seat, spec in room.ai_seats().items()}
    events = []
    for _ in range(limit):
        if room.status == STATUS_FINISHED:
            return events
        actor = room.pending_ai_actor(set())
        if actor is not None:
            decision = _decide(room.state, actor, agents[actor])
            assert not isinstance(decision, str), "a real agent must not fault"
            events += room.apply_ai_action(actor, decision)
            continue
        for client in clients:
            msg = room.state_message(client)
            if msg["legal_actions"]:
                request = policy(msg)
                events += room.act(client, {k: v for k, v in request.items() if k != "type"})
                break
        else:
            raise AssertionError("nobody can act")
    raise AssertionError("game did not finish")


def open_ws(client):
    return client.websocket_connect("/ws")


class Recorder:
    """Wraps a real agent and records exactly what the server hands it."""

    def __init__(self, inner, seat_log):
        self.inner, self.log = inner, seat_log
        self.agent_type, self.agent_version, self.agent_config = inner.agent_type, inner.agent_version, inner.agent_config

    def choose_action(self, observation, legal_actions):
        choice = self.inner.choose_action(observation, legal_actions)
        self.log.append((observation, legal_actions, choice))
        return choice


class Boom:
    agent_type, agent_version, agent_config = "rulebot", "x", {}

    def choose_action(self, observation, legal_actions):
        raise RuntimeError("secret internal detail")


class Illegal:
    agent_type, agent_version, agent_config = "rulebot", "x", {}

    def choose_action(self, observation, legal_actions):
        return object()  # not one of the legal actions


def play(seed=SEED, seats=LINEUP, rounds=4, factory=None, always_claim=False, ai_delay=0.0,
         reaction_delay=0.0, instant_human=True):
    """One human against the AI seats over a real WebSocket. Returns (messages, errors,
    human actions sent, manager)."""
    kwargs = {"agent_factory": factory} if factory else {}
    app = create_app(seed_factory=lambda: seed, ai_delay=ai_delay, ai_reaction_delay=reaction_delay, **kwargs)
    msgs, errors, sent, reacted = [], [], [], set()
    with TestClient(app) as client, open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "Human", "mode": "ai", "seats": seats,
                      "num_rounds": rounds, "timeout_seconds": 15})
        first = ws.receive_json()
        assert first["type"] == "state", first
        ws.send_json({"type": "start_game"})
        for _ in range(6000):
            m = ws.receive_json()
            if m["type"] == "error":
                errors.append(m["message"])
                if "closed" in m["message"]:
                    break
                continue
            msgs.append(m)
            if m["room"]["status"] == "finished":
                break
            if m["legal_actions"]:
                request = policy(m, always_claim)
                key = (m["observation"]["completed_rounds"], m["observation"]["attempt"])
                if request["action"] == "react":
                    if key in reacted:  # a stale copy of a state already answered
                        continue
                    reacted.add(key)
                sent.append(request)
                ws.send_json(request)
        else:
            raise AssertionError("game did not finish")
        manager = app.state.manager
    return msgs, errors, sent, manager


def event_types(msgs):
    return [e["type"] for m in msgs for e in m["events"]]


# ============================================================ A. configuration
@pytest.mark.parametrize(
    "seats",
    [None, "human", [], ["human"] * 3, ["human"] * 5, ["human", "rulebot", "mindbot", "bogus"],
     ["rulebot"] * 4, ["mindbot", "mindbot", "mindbot", "mindbot"], [1, 2, 3, 4],
     ["human", "RuleBot", "rulebot", "rulebot"], ["human", None, "rulebot", "rulebot"],
     ["human", "rulebot", "rulebot", {"agent": "mindbot"}], ["human", "", "rulebot", "rulebot"]],
)
def test_invalid_seat_lineups_are_rejected(seats):
    with pytest.raises(RoomError):
        parse_seats(seats, 4)


def test_valid_lineups_are_accepted_for_every_player_count():
    for n in range(4, 9):
        seats = ["human"] + ["rulebot"] * (n - 1)
        assert parse_seats(seats, n) == tuple(seats)


def test_human_and_ai_seat_counts_sum_to_the_total():
    room = make_room(["human", "human", "mindbot", "rulebot", "rulebot"], rounds=5)
    assert room.num_players == 5 and room.seat_kinds.count("human") + len(room.ai_seats()) == 5
    with pytest.raises(RoomError):
        Room("ABCD", 4, 4, 15, seats=["human", "rulebot", "rulebot", "rulebot", "rulebot"])


def test_ai_seats_are_named_flagged_and_use_server_owned_specs():
    room = make_room(LINEUP)
    info = room.room_info()
    assert info["mode"] == "ai" and info["seat_kinds"] == LINEUP
    assert [(p["name"], p["ai"], p["agent"]) for p in info["players"]] == [
        ("RuleBot 1", True, "RuleBot"), ("MindBot", True, "MindBot"), ("RuleBot 2", True, "RuleBot")]
    specs = room.ai_seats()
    assert specs[2].agent_type == "mindbot" and specs[2].agent_config["use_inference"] is True
    assert specs[1].agent_type == "rulebot" and specs[1].agent_config == {"non_target_order": "fewest_copies"}
    assert set(AI_AGENTS) == {"rulebot", "mindbot"}


def test_humans_take_the_human_seats_in_join_order_and_the_first_is_host():
    room = make_room(["rulebot", "human", "human", "mindbot"])
    a, b = Client(), Client()
    assert room.add_player(a, "Ann") == 1 and room.add_player(b, "Bob") == 2
    assert [p.is_host for p in room.players] == [False, True, False, False]
    with pytest.raises(RoomError, match="full"):
        room.add_player(Client(), "Cy")
    room.disconnect(a)  # leaving the lobby frees the seat and promotes the next human
    assert room.seat_of(b) == 1 and room.players[1].is_host


def test_a_human_cannot_take_an_ai_name():
    room = make_room(LINEUP)
    with pytest.raises(RoomError, match="taken"):
        room.add_player(Client(), "  mindbot ")
    with pytest.raises(RoomError, match="taken"):
        room.add_player(Client(), "RULEBOT 1")


def test_only_humans_have_to_join_before_the_host_can_start():
    room = make_room(["human", "human", "rulebot", "mindbot"])
    host, guest = Client(), Client()
    room.add_player(host, "A")
    with pytest.raises(RoomError, match="Waiting for players: 1 of 2"):
        room.start(host)
    room.add_player(guest, "B")
    with pytest.raises(RoomError, match="host"):
        room.start(guest)
    room.start(host)
    assert room.status == STATUS_PLAYING


def test_ai_room_creation_over_websocket_and_human_only_unchanged():
    app = create_app(seed_factory=lambda: SEED)
    with TestClient(app) as client, open_ws(client) as ws, open_ws(client) as ws2:
        ws.send_json({"type": "create_room", "name": "Host", "mode": "ai", "seats": LINEUP, "num_rounds": 8})
        msg = ws.receive_json()
        assert msg["room"]["mode"] == "ai" and msg["me"]["seat"] == 0 and msg["room"]["num_players"] == 4
        assert [p["ai"] for p in msg["room"]["players"]] == [False, True, True, True]
        ws2.send_json({"type": "create_room", "name": "Plain", "num_players": 5, "num_rounds": 5})
        plain = ws2.receive_json()
        assert plain["room"]["mode"] == "human" and plain["room"]["seat_kinds"] == ["human"] * 5
        assert not any(p["ai"] for p in plain["room"]["players"])
        ws2.close()


@pytest.mark.parametrize(
    "extra",
    [{"mode": "ai"}, {"mode": "ai", "seats": "rulebot"}, {"mode": "ai", "seats": ["human"] * 4},
     {"mode": "ai", "seats": ["rulebot"] * 4}, {"mode": "ai", "seats": ["human", "rulebot", "x", "rulebot"]},
     {"mode": "ai", "seats": ["human", "rulebot", "rulebot"], "num_players": 4},
     {"mode": "ai", "seats": ["human"] + ["rulebot"] * 2},
     {"mode": "ai", "seats": LINEUP, "num_rounds": 6}, {"mode": "bogus", "seats": LINEUP},
     {"mode": "ai", "seats": LINEUP, "timeout_seconds": 99}],
)
def test_invalid_ai_room_requests_are_refused_and_create_nothing(extra):
    app = create_app()
    with TestClient(app) as client, open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "Host", **extra})
        assert ws.receive_json()["type"] == "error"
    assert not app.state.manager.rooms


def test_human_mode_ignores_a_seats_field():
    app = create_app()
    with TestClient(app) as client, open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "H", "num_players": 4, "num_rounds": 4, "seats": LINEUP})
        msg = ws.receive_json()
        assert msg["room"]["mode"] == "human" and not any(p["ai"] for p in msg["room"]["players"])


def test_clients_cannot_change_ai_assignments():
    app = create_app(seed_factory=lambda: SEED, ai_delay=0, ai_reaction_delay=0)
    with TestClient(app) as client, open_ws(client) as host, open_ws(client) as guest:
        host.send_json({"type": "create_room", "name": "Host", "mode": "ai", "num_rounds": 4,
                        "seats": ["human", "human", "rulebot", "mindbot"]})
        code = host.receive_json()["room"]["code"]
        room = app.state.manager.rooms[code].room
        before = (room.seat_kinds, dict(room.ai_seats()))
        for payload in ({"type": "configure_ai", "seat": 2, "agent": "mindbot"},
                        {"type": "set_agent", "seats": ["human"] * 4},
                        {"type": "action", "action": "claim", "seat": 2, "agent": "mindbot"}):
            guest.send_json(payload)
            assert guest.receive_json()["type"] == "error"
        guest.send_json({"type": "join_room", "name": "Guest", "code": code, "agent": "mindbot",
                         "seats": ["human"] * 4, "mode": "human"})
        assert guest.receive_json()["type"] == "state"
        host.receive_json()
        guest.send_json({"type": "start_game", "seats": ["human"] * 4})  # not the host
        assert "host" in guest.receive_json()["message"]
        assert (room.seat_kinds, dict(room.ai_seats())) == before


def test_an_ai_that_cannot_be_built_is_reported_not_replaced():
    def factory(spec):
        if spec.agent_type == "mindbot":
            raise RuntimeError("no inference module")
        return build_agent(spec)

    app = create_app(agent_factory=factory)
    with TestClient(app) as client, open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "H", "mode": "ai", "seats": LINEUP, "num_rounds": 4})
        err = ws.receive_json()
        assert err["type"] == "error" and "MindBot" in err["message"] and "unavailable" in err["message"]
        assert "no inference module" not in err["message"]
        ws.send_json({"type": "create_room", "name": "H", "mode": "ai",
                      "seats": ["human", "rulebot", "rulebot", "rulebot"], "num_rounds": 4})
        assert ws.receive_json()["type"] == "state"  # RuleBot-only still works


# ====================================================== B. AI orchestration
@pytest.mark.parametrize("seats", [
    ["human", "rulebot", "rulebot", "rulebot"],
    ["human", "mindbot", "mindbot", "mindbot"],
    LINEUP,
    ["rulebot", "human", "mindbot", "human", "rulebot"],
])
def test_a_complete_room_game_against_each_agent_type(seats):
    n = len(seats)
    room = make_room(seats, rounds=n)
    clients = seat_humans(room)
    room.start(clients[0])
    events = play_room_with_ais(room, clients)
    assert room.status == STATUS_FINISHED and room.state.phase is Phase.GAME_OVER
    kinds = [e.type for e in events]
    assert kinds.count("round_completed") == n and "game_completed" in kinds


@pytest.mark.parametrize("seats", [LINEUP, ["human", "mindbot", "mindbot", "mindbot"]])
def test_full_websocket_games_finish_and_standings_flag_the_ai(seats):
    msgs, errors, sent, _ = play(seats=seats)
    assert not errors
    final = msgs[-1]
    assert final["room"]["status"] == "finished"
    flags = {r["name"]: r["ai"] for r in final["standings"]}
    assert flags["Human"] is False and sum(flags.values()) == 3
    kinds = event_types(msgs)
    assert kinds.count("round_completed") == 4 and kinds.count("deal") >= 4
    assert "valid_win_scored" in kinds and "player_reacted" in kinds


def test_games_are_reproducible_for_a_fixed_seed():
    a = play(seed=SEED)[0]
    b = play(seed=SEED)[0]
    assert [e for m in a for e in m["events"]] == [e for m in b for e in m["events"]]
    assert a[-1]["standings"] == b[-1]["standings"]


def test_ai_decisions_use_only_the_seats_own_observation_and_legal_actions():
    log, instances = [], []

    def factory(spec):
        agent = Recorder(build_agent(spec), log)
        instances.append(agent)
        return agent

    msgs, errors, _, manager = play(factory=factory)
    assert not errors and log
    for observation, legal, choice in log:
        assert isinstance(observation, Observation)
        assert observation.my_seat in (1, 2, 3)  # never the human's seat
        assert choice in legal and legal
        assert "seed" not in json.dumps(observation.to_dict())
        assert not any(hasattr(observation, name) for name in ("hands", "state", "config", "seed"))
    # one fresh instance per AI seat per game (3 to validate at creation, 3 for the game)
    assert len(instances) == 6 and len({id(a) for a in instances[3:]}) == 3


def test_every_ai_action_is_accepted_by_the_engine_and_is_legal_for_its_seat():
    room = make_room(LINEUP)
    clients = seat_humans(room)
    room.start(clients[0])
    agents = {seat: build_agent(spec) for seat, spec in room.ai_seats().items()}
    checked = 0
    while room.status != STATUS_FINISHED:
        actor = room.pending_ai_actor(set())
        if actor is None:
            msg = room.state_message(clients[0])
            request = policy(msg)
            room.act(clients[0], {k: v for k, v in request.items() if k != "type"})
            continue
        legal = legal_actions_for(room.state, actor)
        decision = _decide(room.state, actor, agents[actor])
        assert not isinstance(decision, str) and decision.seat == actor
        room.apply_ai_action(actor, decision)
        checked += 1
    assert checked > 10


def test_the_ai_never_acts_for_a_human_seat_and_humans_never_for_an_ai():
    room = make_room(LINEUP)
    (human,) = seat_humans(room)
    room.start(human)
    with pytest.raises(RoomError):
        room.apply_ai_action(0, room.state and _decide(room.state, 0, build_agent(AI_AGENTS["rulebot"][1])))
    msgs, errors, sent, _ = play()
    # every event by seat 0 corresponds to something the human sent (no timeouts at 15s)
    own = [e for m in msgs for e in m["events"]
           if e.get("seat") == 0 and e["type"] in ("initial_claim_declined", "initial_claim_made", "claim_made", "player_reacted")
           or e.get("from_seat") == 0]
    assert len(own) == len(sent) and not errors
    assert "decision_timed_out" not in event_types(msgs)


def test_ai_actions_chain_automatically_and_stop_at_the_humans_turn():
    msgs, errors, sent, _ = play()
    assert not errors
    # a chit travelling 1 -> 2 -> 3 without any human action in between
    passes = [(e["from_seat"], e["to_seat"]) for m in msgs for e in m["events"] if e["type"] == "chit_passed"]
    assert any(a == (1, 2) and b == (2, 3) for a, b in zip(passes, passes[1:]))
    # whenever the human is asked, control really is the human's: no AI acts underneath it
    for m in msgs:
        if m["legal_actions"]:
            o = m["observation"]
            assert o["my_turn"] is True and m["room"]["status"] == "playing"
            assert o["phase"] == "win_declared" or o["decision_seat"] == 0


def test_the_ai_aware_room_state_stops_at_a_human_decision():
    room = make_room(["human", "rulebot", "mindbot", "rulebot"])
    (human,) = seat_humans(room)
    room.start(human)
    assert room.pending_ai_actor(set()) is None  # seat 0, the human, opens
    room2 = make_room(["rulebot", "human", "mindbot", "rulebot"])
    (human2,) = seat_humans(room2)
    room2.start(human2)
    assert room2.pending_ai_actor(set()) == 0  # the AI at seat 0 opens
    human_only, clients = Room("ABCD", 4, 4, 15, seed=SEED), []
    clients = [Client() for _ in range(4)]
    for i, c in enumerate(clients):
        human_only.add_player(c, f"P{i}")
    human_only.start(clients[0])
    assert human_only.pending_ai_actor(set()) is None


def test_draw_attempts_and_redeals_continue_through_ai_seats():
    msgs, errors, _, _ = play(seed=DRAW_SEED)
    kinds = event_types(msgs)
    assert not errors and "attempt_drawn" in kinds
    after = kinds[kinds.index("attempt_drawn"):]
    assert "deal" in after and "game_completed" in after
    assert msgs[-1]["room"]["status"] == "finished"


def test_false_claims_through_the_ai_pipeline():
    msgs, errors, _, _ = play(seats=["human", "rulebot", "mindbot", "rulebot"], rounds=8, always_claim=True)
    assert not errors and event_types(msgs).count("round_completed") == 8


def test_the_ai_does_not_get_a_host_timer_and_a_human_does():
    app = create_app(seed_factory=lambda: SEED, ai_delay=0.05, ai_reaction_delay=0.05)
    with TestClient(app) as client, open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "H", "mode": "ai", "num_rounds": 4,
                      "seats": ["rulebot", "human", "rulebot", "rulebot"]})
        ws.receive_json()
        ws.send_json({"type": "start_game"})
        first = ws.receive_json()
        assert first["observation"]["decision_seat"] == 0 and first["timer"] is None  # AI to move
        for _ in range(40):
            m = ws.receive_json()
            if m["legal_actions"]:
                assert m["timer"]["seat"] == 1  # the human's own decision has the host timer
                return
        raise AssertionError("the human was never asked")


def test_a_human_gets_a_fair_window_to_react_before_the_ai_seats():
    app = create_app(seed_factory=lambda: SEED, ai_delay=0.0, ai_reaction_delay=0.4)
    msgs, reacted = [], set()
    with TestClient(app) as client, open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "H", "mode": "ai", "num_rounds": 4, "seats": LINEUP})
        ws.receive_json()
        ws.send_json({"type": "start_game"})
        while True:
            m = ws.receive_json()
            if m["type"] != "state":
                continue
            msgs.append(m)
            if m["room"]["status"] == "finished":
                break
            if m["legal_actions"]:
                request = policy(m)
                key = (m["observation"]["completed_rounds"], m["observation"]["attempt"])
                if request["action"] == "react":
                    if key in reacted:
                        continue
                    reacted.add(key)
                ws.send_json(request)
    wins = [e for mm in msgs for e in mm["events"] if e["type"] == "valid_win_scored"]
    assert wins and any(w["winner"] != 0 for w in wins)
    for w in wins:
        if w["winner"] != 0:
            assert w["reaction_order"][0] == 0  # the human reacted at once and placed first


def test_closing_the_last_human_tab_removes_an_ai_room():
    app = create_app(seed_factory=lambda: SEED, ai_delay=0.05, ai_reaction_delay=0.05)
    with TestClient(app) as client:
        with open_ws(client) as ws:
            ws.send_json({"type": "create_room", "name": "H", "mode": "ai", "num_rounds": 4, "seats": LINEUP})
            ws.receive_json()
            ws.send_json({"type": "start_game"})
            ws.receive_json()
        deadline = time.time() + 2
        while app.state.manager.rooms and time.time() < deadline:
            time.sleep(0.02)
        assert not app.state.manager.rooms


# ====================================================== failure handling
def test_a_failing_ai_is_timed_out_like_the_runner_does_and_the_room_survives():
    def factory(spec):
        return Boom() if spec.agent_type == "mindbot" else build_agent(spec)

    msgs, errors, _, _ = play(factory=factory)
    assert not errors and msgs[-1]["room"]["status"] == "finished"
    timed_out = [e["seat"] for m in msgs for e in m["events"] if e["type"] == "decision_timed_out"]
    assert timed_out and set(timed_out) == {2}  # only the failing seat, never a claim for it
    claims_by_failing_seat = [e for m in msgs for e in m["events"]
                              if e["type"] in ("claim_made", "initial_claim_made") and e["seat"] == 2]
    assert not claims_by_failing_seat
    assert "secret internal detail" not in json.dumps(msgs)


def test_an_ai_returning_an_illegal_action_is_treated_as_a_failure():
    def factory(spec):
        return Illegal() if spec.agent_type == "mindbot" else build_agent(spec)

    msgs, errors, _, _ = play(factory=factory)
    assert not errors and msgs[-1]["room"]["status"] == "finished"
    assert 2 in {e["seat"] for m in msgs for e in m["events"] if e["type"] == "decision_timed_out"}


def test_when_every_pending_reactor_fails_the_room_is_closed_with_a_clear_message():
    app = create_app(seed_factory=lambda: 1, ai_delay=0, ai_reaction_delay=0, agent_factory=lambda spec: Boom())
    with TestClient(app) as client, open_ws(client) as ws:
        ws.send_json({"type": "create_room", "name": "H", "mode": "ai", "seats": LINEUP, "num_rounds": 4})
        ws.receive_json()
        ws.send_json({"type": "start_game"})
        message = None
        for _ in range(3000):
            m = ws.receive_json()
            if m["type"] == "error":
                message = m["message"]
                break
            if m["legal_actions"]:
                ws.send_json(policy(m))
        assert message and "AI player failed" in message
        assert not app.state.manager.rooms


def test_unresolvable_means_only_failed_ai_reactors_remain():
    room = make_room(["human", "rulebot", "rulebot", "rulebot"])
    (human,) = seat_humans(room)
    room.start(human)
    agents = {seat: build_agent(spec) for seat, spec in room.ai_seats().items()}
    for _ in range(20000):
        if room.state.phase is Phase.WIN_DECLARED:
            break
        actor = room.pending_ai_actor(set())
        if actor is not None:
            room.apply_ai_action(actor, _decide(room.state, actor, agents[actor]))
        else:
            req = policy(room.state_message(human))
            room.act(human, {k: v for k, v in req.items() if k != "type"})
    else:
        pytest.fail("no valid win")
    assert room.unresolvable({1, 2, 3}) is (room.state.winner == 0)
    assert room.unresolvable(set()) is False


# ============================================================ C. privacy
def test_no_ai_hand_or_diagnostic_reaches_the_human():
    msgs, errors, _, _ = play(seed=SEED)
    assert not errors
    forbidden = ("belief", "estimator", "inference", "counters", "agent_config", "non_target_order",
                 "use_inference", "fewest_copies", '"hands"', '"copy"', "debug", "token", "seed")
    for m in msgs:
        text = json.dumps(m)
        assert str(SEED) not in text
        for word in forbidden:
            assert word not in text, word
        assert m["me"]["seat"] == 0 and m["observation"]["my_seat"] == 0
        for e in m["events"]:
            if e["type"] == "deal":
                assert len(e["my_hand"]) == 4
            else:
                assert "my_hand" not in e
            if e["type"] == "chit_passed":  # only passes the human sent or received show the chit
                assert ("chit_name" in e) == (0 in (e["from_seat"], e["to_seat"]))
    seen_private = [e for m in msgs for e in m["events"] if e["type"] == "chit_passed" and "chit_name" in e]
    seen_public = [e for m in msgs for e in m["events"] if e["type"] == "chit_passed" and "chit_name" not in e]
    assert seen_private and seen_public  # AI-to-AI passes were visible only as public facts


def test_the_deal_event_carries_only_the_humans_own_hand():
    msgs, _, _, _ = play()
    for m in msgs:
        for e in m["events"]:
            if e["type"] == "deal":
                assert set(e) >= {"my_hand"} and len(e["my_hand"]) == 4
        assert len(m["observation"]["my_hand"]) in (3, 4, 5)  # 3 after passing, 5 on receiving
        assert all(isinstance(x, str) for x in m["observation"]["my_hand"])


def test_hidden_twin_the_human_view_is_identical_whichever_chit_the_ai_passed():
    """Two games that differ only in which chit an AI seat passes to another AI seat
    look the same to the human on the wire."""
    views = []
    for chosen in (0, 1):
        room = make_room(["human", "rulebot", "rulebot", "rulebot"])
        (human,) = seat_humans(room)
        room.start(human)
        room.act(human, {"action": "decline"})
        for seat in (1, 2, 3):
            room.apply_ai_action(seat, _decide(room.state, seat, build_agent(AI_AGENTS["rulebot"][1])))
        state = room.state
        assert state.phase is Phase.PASSING and state.decision_seat == 0
        hand = sorted({c.name for c in state.hands[0]})
        events = room.act(human, {"action": "pass", "chit_name": hand[min(chosen, len(hand) - 1)]})
        # now seat 1 (AI) passes to seat 2 (AI): the human is a bystander of that pass
        agent = build_agent(AI_AGENTS["rulebot"][1])
        ai_events = room.apply_ai_action(1, _decide(room.state, 1, agent))
        views.append(json.dumps(room.state_message(human, ai_events)["events"], sort_keys=True))
    assert views[0] == views[1]  # the bystander view does not depend on the hidden chit
    assert all('"chit_name"' not in v for v in views)


# ============================================================ D. regression
def test_lower_layers_never_import_the_web_package():
    root = Path(__file__).parents[2] / "src" / "chitai"
    for package in ("engine", "observations", "agents", "simulation", "eventlog", "batch"):
        for path in (root / package).rglob("*.py"):
            assert not re.search(r"chitai\.api|from \.\.api|from \.\.\.api", path.read_text(encoding="utf-8")), path


def test_the_runner_helpers_the_server_relies_on_exist():
    assert callable(_decide) and callable(build_agent)


def test_a_stale_ai_step_changes_nothing():
    """An AI step remembers the engine step it was scheduled for. If the game has
    moved on by the time it runs (a human or a timer acted first), it does nothing."""
    import asyncio

    from chitai.api.server import ManagedRoom, RoomManager

    async def scenario():
        manager = RoomManager(seed_factory=lambda: SEED, ai_delay=0, ai_reaction_delay=0)
        room = make_room(["rulebot", "rulebot", "human", "rulebot"])
        human = Client()
        room.add_player(human, "H")
        managed = ManagedRoom(room)
        managed.agents = manager._build_agents(room)
        room.start(human)
        old_seq = room.state.next_seq
        assert room.pending_ai_actor(set()) == 0
        room.apply_timeout(old_seq)  # the game moves on first
        state = room.state
        await manager._ai_step(managed, old_seq, 0, 0.0, False)
        assert room.state is state
        # the same step with the current sequence number does act
        current = room.state.next_seq
        actor = room.pending_ai_actor(set())
        assert actor == 1
        await manager._ai_step(managed, current, actor, 0.0, False)
        assert room.state is not state

    asyncio.run(scenario())
