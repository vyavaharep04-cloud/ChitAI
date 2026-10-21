"""FastAPI/WebSocket layer (Milestone 10).

One WebSocket per player at `/ws`; the browser UI is served from the repository's
`web/` directory. The connection itself is the identity: a seat is assigned by
`rooms.Room` and looked up from the connection, never from the message.

Concurrency: each room has an `asyncio.Lock`; every state change (client action,
host timeout, join, leave) happens under it, including the broadcast that follows,
so messages reach clients in the order the engine accepted the actions. Reaction
order is therefore the order in which the server processed the actions.

AI seats (Human vs AI rooms): the server, never a client, decides when an AI acts.
After every state change `_plan` looks at the engine state and either schedules the
AI seat that must act next or starts the host timer for a human. An AI step builds
the seat's `Observation`, asks the existing agent for a choice, validates it against
that seat's legal actions with the simulation runner's own `_decide`, and applies it
through the engine. Agent failures are handled exactly as the runner handles them:
a single decision becomes a host timeout; a failed reactor is skipped.

Timeouts are issued here, by a server-side timer, through the engine's own
`timeout_action`. There is no client message that means "timeout". A timer
remembers the engine sequence number it was started for and does nothing if the
game has moved on (stale timer).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..engine import Phase
from ..simulation.runner import _decide, build_agent
from .rooms import AI_AGENTS, HUMAN, STATUS_PLAYING, Room, RoomError

log = logging.getLogger("chitai.api")

MAX_MESSAGE_CHARS = 2048
MAX_ROOMS = 50
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I or O
CODE_LENGTH = 4
DEFAULT_TIMEOUT_SECONDS = 15.0
# Pacing for AI seats so people can follow the game. The reaction delay also gives a
# human a fair window to react before the AI seats do (reaction order scores points).
DEFAULT_AI_DELAY_SECONDS = 0.9
DEFAULT_AI_REACTION_DELAY_SECONDS = 2.0


def default_web_dir() -> Path:
    override = os.environ.get("CHITAI_WEB_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "web"


class Connection:
    """One browser tab. Identity is object identity; `room` is set once joined."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.room: ManagedRoom | None = None


class ManagedRoom:
    def __init__(self, room: Room) -> None:
        self.room = room
        self.lock = asyncio.Lock()
        self.connections: list[Connection] = []
        self.timer_task: asyncio.Task | None = None
        self.ai_task: asyncio.Task | None = None
        self.timer_deadline = 0.0
        self.timer_seat: int | None = None
        self.agents: dict[int, Any] = {}       # seat -> agent instance, one per AI seat per game
        self.faulted: set[int] = set()         # AI reactors that failed during the current reaction phase
        self.ai_fault_count = 0
        self.closed = False


def origin_allowed(origin: str | None, host: str | None, extra: frozenset[str]) -> bool:
    """Same-origin check for the WebSocket handshake. Browsers always send Origin,
    so a page from another site cannot drive this server; clients that send no
    Origin (scripts, tests) are allowed."""
    if origin is None:
        return True
    if origin in extra:
        return True
    netloc = urlsplit(origin).netloc
    return bool(host) and netloc.casefold() == host.casefold()


class RoomManager:
    def __init__(
        self,
        seed_factory: Callable[[], int | None] = lambda: None,
        agent_factory: Callable[[Any], Any] = build_agent,
        ai_delay: float = DEFAULT_AI_DELAY_SECONDS,
        ai_reaction_delay: float = DEFAULT_AI_REACTION_DELAY_SECONDS,
    ) -> None:
        self.rooms: dict[str, ManagedRoom] = {}
        self._seed_factory = seed_factory
        self._agent_factory = agent_factory
        self._ai_delay = ai_delay
        self._ai_reaction_delay = ai_reaction_delay

    # ------------------------------------------------------------- plumbing
    async def _send(self, connection: Connection, payload: dict[str, Any]) -> None:
        try:
            await connection.websocket.send_json(payload)
        except Exception:  # closed or broken socket: its disconnect handler cleans up
            pass

    async def _error(self, connection: Connection, message: str) -> None:
        await self._send(connection, {"type": "error", "message": message})

    def _timer_info(self, managed: ManagedRoom) -> dict[str, Any] | None:
        if managed.timer_task is None or managed.timer_seat is None:
            return None
        loop = asyncio.get_running_loop()
        return {"seat": managed.timer_seat, "seconds_left": max(0.0, managed.timer_deadline - loop.time())}

    async def _broadcast(self, managed: ManagedRoom, events: tuple = ()) -> None:
        timer = self._timer_info(managed)
        for connection in list(managed.connections):
            message = managed.room.state_message(connection, events, timer)
            if message is not None:
                await self._send(connection, message)

    def _plan(self, managed: ManagedRoom) -> None:
        """After any state change: cancel pending timers and schedule what is next."""
        current = asyncio.current_task()
        for attr in ("timer_task", "ai_task"):
            task = getattr(managed, attr)
            if task is not None and task is not current:
                task.cancel()
            setattr(managed, attr, None)
        managed.timer_seat = None
        room = managed.room
        if managed.closed or room.status != STATUS_PLAYING or room.state is None:
            return
        if room.state.phase is not Phase.WIN_DECLARED:
            managed.faulted.clear()
        if room.unresolvable(managed.faulted):
            self._abort(managed, "An AI player failed and the game cannot continue. The room was closed.")
            return
        loop = asyncio.get_running_loop()
        actor = room.pending_ai_actor(managed.faulted)
        if actor is not None:
            delay = self._ai_reaction_delay if room.state.phase is Phase.WIN_DECLARED else self._ai_delay
            managed.ai_task = asyncio.create_task(
                self._ai_step(managed, room.state.next_seq, actor, delay, False)
            )
            return
        target = room.timer_target()
        if target is None:
            return
        expected_seq, seat = target
        if room.is_ai(seat):  # the last pending reactor is an AI that failed: host times it out now
            managed.ai_task = asyncio.create_task(self._ai_step(managed, expected_seq, seat, 0.0, True))
            return
        delay = room.timeout_seconds
        managed.timer_deadline = loop.time() + delay
        managed.timer_seat = seat
        managed.timer_task = asyncio.create_task(self._timer(managed, expected_seq, delay))

    async def _ai_step(
        self, managed: ManagedRoom, expected_seq: int, seat: int, delay: float, force_timeout: bool
    ) -> None:
        if delay:
            await asyncio.sleep(delay)
        async with managed.lock:
            if managed.ai_task is asyncio.current_task():
                managed.ai_task = None
            room = managed.room
            if managed.closed or room.status != STATUS_PLAYING or room.state is None:
                return
            if room.state.next_seq != expected_seq:  # a human acted first: stale step
                return
            events: tuple | None = None
            try:
                if force_timeout:
                    events = room.apply_timeout(expected_seq)
                else:
                    decision = _decide(room.state, seat, managed.agents[seat])
                    if isinstance(decision, str):  # fault text may be agent-internal: log only
                        managed.ai_fault_count += 1
                        log.warning("AI seat %d failed in room %s", seat, room.code)
                        if room.state.phase is Phase.WIN_DECLARED:
                            managed.faulted.add(seat)
                        else:
                            events = room.apply_timeout(expected_seq)
                    else:
                        events = room.apply_ai_action(seat, decision)
            except Exception:
                log.exception("AI step failed in room %s", room.code)
                self._abort(managed, "The server hit an error with an AI player. The room was closed.")
                return
            self._plan(managed)
            if events:
                await self._broadcast(managed, events)

    def _abort(self, managed: ManagedRoom, message: str) -> None:
        if managed.closed:
            return
        self._close(managed)
        asyncio.create_task(self._notify_all(managed, message))

    async def _notify_all(self, managed: ManagedRoom, message: str) -> None:
        for connection in list(managed.connections):
            await self._error(connection, message)

    async def _timer(self, managed: ManagedRoom, expected_seq: int, delay: float) -> None:
        await asyncio.sleep(delay)
        async with managed.lock:
            if managed.timer_task is asyncio.current_task():
                managed.timer_task = None  # this task is finishing; never cancel ourselves
            if managed.closed:
                return
            try:
                events = managed.room.apply_timeout(expected_seq)
            except Exception:
                log.exception("timeout failed in room %s", managed.room.code)
                events = None
            if events is None:  # stale timer (the game moved on) or refused: change nothing
                if managed.timer_task is None and managed.room.status == STATUS_PLAYING:
                    self._plan(managed)
                return
            self._plan(managed)
            await self._broadcast(managed, events)

    def _close(self, managed: ManagedRoom) -> None:
        managed.closed = True
        current = asyncio.current_task()
        for attr in ("timer_task", "ai_task"):
            task = getattr(managed, attr)
            if task is not None and task is not current:
                task.cancel()
            setattr(managed, attr, None)
        self.rooms.pop(managed.room.code, None)

    # ------------------------------------------------------------- messages
    async def handle(self, connection: Connection, text: str) -> None:
        if len(text) > MAX_MESSAGE_CHARS:
            await self._error(connection, "That message is too large.")
            return
        try:
            message = json.loads(text)
        except ValueError:
            await self._error(connection, "Messages must be valid JSON.")
            return
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            await self._error(connection, "Malformed message.")
            return
        kind = message["type"]
        try:
            if kind == "create_room":
                await self._create_room(connection, message)
            elif kind == "join_room":
                await self._join_room(connection, message)
            elif kind == "start_game":
                await self._start_game(connection)
            elif kind == "action":
                await self._action(connection, message)
            else:
                await self._error(connection, "Unknown message type.")
        except RoomError as error:
            await self._error(connection, error.message)
        except Exception:
            log.exception("unexpected error handling %r", kind)
            await self._error(connection, "Something went wrong on the server.")

    def _new_code(self) -> str:
        for _ in range(100):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                return code
        raise RoomError("The server is busy. Please try again.")

    async def _create_room(self, connection: Connection, message: dict[str, Any]) -> None:
        if connection.room is not None:
            raise RoomError("You are already in a room.")
        if len(self.rooms) >= MAX_ROOMS:
            raise RoomError("The server has too many rooms open right now.")
        mode = message.get("mode", "human")
        seats = None
        num_players = message.get("num_players", 4)
        if mode == "ai":
            seats = message.get("seats")
            if not isinstance(seats, list):
                raise RoomError("Choose the seat setup for a Human vs AI game.")
            if not any(kind != HUMAN for kind in seats):
                raise RoomError("A Human vs AI game needs at least one AI seat.")
            if "num_players" in message and message["num_players"] != len(seats):
                raise RoomError("The player count must equal the number of human and AI seats.")
            num_players = len(seats)
        elif mode != "human":
            raise RoomError("Unknown game mode.")
        room = Room(
            self._new_code(),
            num_players,
            message.get("num_rounds", num_players),
            message.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            seed=self._seed_factory(),
            seats=seats,
        )
        self._build_agents(room)  # fail now, with a clear message, if an AI cannot be built
        managed = ManagedRoom(room)
        room.add_player(connection, message.get("name"))
        managed.connections.append(connection)
        connection.room = managed
        self.rooms[room.code] = managed
        async with managed.lock:
            await self._broadcast(managed)

    def _build_agents(self, room: Room) -> dict[int, Any]:
        """One fresh agent instance per AI seat (MindBot keeps memory between its
        decisions). No silent substitution: a failure is reported to the host."""
        agents: dict[int, Any] = {}
        for seat, spec in room.ai_seats().items():
            try:
                agents[seat] = self._agent_factory(spec)
            except Exception:
                log.exception("could not build the %s agent", spec.agent_type)
                label = AI_AGENTS[room.player_at(seat).agent][0]
                raise RoomError(f"The {label} AI is unavailable, so this game cannot be created.") from None
        return agents

    async def _join_room(self, connection: Connection, message: dict[str, Any]) -> None:
        if connection.room is not None:
            raise RoomError("You are already in a room.")
        code = message.get("code")
        managed = self.rooms.get(code.strip().upper()) if isinstance(code, str) else None
        if managed is None:
            raise RoomError("No room with that code.")
        async with managed.lock:
            if managed.closed:
                raise RoomError("No room with that code.")
            managed.room.add_player(connection, message.get("name"))
            managed.connections.append(connection)
            connection.room = managed
            await self._broadcast(managed)

    async def _start_game(self, connection: Connection) -> None:
        managed = connection.room
        if managed is None:
            raise RoomError("Join or create a room first.")
        async with managed.lock:
            managed.room.check_start(connection)
            managed.agents = self._build_agents(managed.room)  # fresh agents for this game
            managed.faulted.clear()
            events = managed.room.start(connection)
            self._plan(managed)
            await self._broadcast(managed, events)

    async def _action(self, connection: Connection, message: dict[str, Any]) -> None:
        managed = connection.room
        if managed is None:
            raise RoomError("Join or create a room first.")
        async with managed.lock:
            if managed.closed:
                raise RoomError("This room has closed.")
            events = managed.room.act(connection, message)
            self._plan(managed)
            await self._broadcast(managed, events)

    async def disconnect(self, connection: Connection) -> None:
        managed = connection.room
        if managed is None:
            return
        async with managed.lock:
            if connection in managed.connections:
                managed.connections.remove(connection)
            connection.room = None
            if managed.room.disconnect(connection):
                self._close(managed)
                return
            await self._broadcast(managed)


def create_app(
    web_dir: Path | None = None,
    seed_factory: Callable[[], int | None] = lambda: None,
    allowed_origins: frozenset[str] = frozenset(),
    agent_factory: Callable[[Any], Any] = build_agent,
    ai_delay: float = DEFAULT_AI_DELAY_SECONDS,
    ai_reaction_delay: float = DEFAULT_AI_REACTION_DELAY_SECONDS,
) -> FastAPI:
    """Build the application. `seed_factory`, `agent_factory` and the AI delays are
    for tests; by default every game gets a fresh random seed that never leaves the
    server, and AI seats use the existing `build_agent`."""
    app = FastAPI(title="ChitAI", docs_url=None, redoc_url=None, openapi_url=None)
    manager = RoomManager(seed_factory, agent_factory, ai_delay, ai_reaction_delay)
    app.state.manager = manager
    static_dir = web_dir if web_dir is not None else default_web_dir()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        if not origin_allowed(
            websocket.headers.get("origin"), websocket.headers.get("host"), allowed_origins
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        connection = Connection(websocket)
        try:
            while True:
                text = await websocket.receive_text()
                await manager.handle(connection, text)
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(connection)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app
