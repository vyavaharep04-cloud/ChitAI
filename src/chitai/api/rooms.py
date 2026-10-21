"""One game room: lobby, seats and the action pipeline (Milestone 10).

No sockets and no asyncio here, so everything is unit-testable. The server layer
identifies each participant by an opaque `client` object (its connection). The
seat of a client is assigned by this module and looked up from that object; a
seat number sent by a client is never read.

Privacy: the only game information that leaves this module is `observe(state,
seat)`, `legal_actions_for(state, seat)` and `observe_event(event, seat)` for the
recipient's own seat. The seed, the `GameConfig`, `GameState`, other hands and
engine `Rejected` messages are never put in a message.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Hashable

from ..engine import (
    Accepted,
    ClaimAction,
    ConfigError,
    DeclineAction,
    GameConfig,
    GameState,
    MAX_PASS_TIMEOUT_SECONDS,
    MAX_PLAYERS,
    MIN_PLAYERS,
    Phase,
    ReactAction,
    TimeoutAction,
    apply_action,
    new_game,
    pending_reactors,
    timeout_action,
)
from ..observations import (
    NamePassAction,
    action_to_dict,
    legal_actions_for,
    observe,
    observe_event,
    to_engine_action,
)
from ..simulation import AgentSpec, competition_ranks
from ..simulation.seeds import reaction_order_for_state

MAX_NAME_LENGTH = 20
MAX_ROUNDS = 64
STATUS_LOBBY = "lobby"
STATUS_PLAYING = "playing"
STATUS_FINISHED = "finished"

# Human vs AI: the only seat types a client may ask for. The server owns the mapping
# from a seat type to a concrete agent configuration; clients never send agent
# settings. Both use the configuration the M9 experiments use (fewest_copies);
# MindBot adds its behavioural inference.
HUMAN = "human"
AI_AGENTS: dict[str, tuple[str, AgentSpec]] = {
    "rulebot": ("RuleBot", AgentSpec("rulebot", {"non_target_order": "fewest_copies"})),
    "mindbot": ("MindBot", AgentSpec("mindbot", {"non_target_order": "fewest_copies", "use_inference": True})),
}


class RoomError(Exception):
    """A request was refused. `message` is safe to show to the client: it never
    contains game data."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Player:
    name: str
    client: Hashable | None  # the connection, or None once disconnected (always None for an AI)
    is_host: bool = False
    agent: str | None = None  # None for a human; "rulebot" or "mindbot" for an AI seat
    seat: int = -1

    @property
    def is_ai(self) -> bool:
        return self.agent is not None

    @property
    def connected(self) -> bool:
        return self.is_ai or self.client is not None


def clean_name(value: object) -> str:
    if not isinstance(value, str):
        raise RoomError("Please enter a display name.")
    name = " ".join(value.split())  # collapses whitespace and control spacing
    if not name or not name.isprintable():
        raise RoomError("Please enter a display name.")
    if len(name) > MAX_NAME_LENGTH:
        raise RoomError(f"Display names can have at most {MAX_NAME_LENGTH} characters.")
    return name


def _int_setting(value: object, label: str) -> int:
    if type(value) is not int:
        raise RoomError(f"{label} must be a whole number.")
    return value


def parse_seats(seats: object, n: int) -> tuple[str, ...]:
    """Validate a seat lineup such as ["human", "rulebot", "mindbot", "rulebot"]."""
    if not isinstance(seats, (list, tuple)):
        raise RoomError("The seat setup must be a list of seat types.")
    if len(seats) != n:
        raise RoomError(f"The seat setup must list exactly {n} seats.")
    for kind in seats:
        if not isinstance(kind, str) or (kind != HUMAN and kind not in AI_AGENTS):
            raise RoomError("Unknown seat type. Use human, rulebot or mindbot.")
    if HUMAN not in seats:
        raise RoomError("At least one seat must be human.")
    return tuple(seats)


class Room:
    def __init__(
        self,
        code: str,
        num_players: object,
        num_rounds: object,
        timeout_seconds: object,
        seed: int | None = None,
        seats: object = None,
    ) -> None:
        n = _int_setting(num_players, "The number of players")
        rounds = _int_setting(num_rounds, "The number of rounds")
        if not MIN_PLAYERS <= n <= MAX_PLAYERS:
            raise RoomError(f"The number of players must be between {MIN_PLAYERS} and {MAX_PLAYERS}.")
        if rounds <= 0 or rounds % n != 0:
            raise RoomError(f"The number of rounds must be a positive multiple of {n}.")
        if rounds > MAX_ROUNDS:
            raise RoomError(f"At most {MAX_ROUNDS} rounds are allowed.")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise RoomError("The timeout must be a number of seconds.")
        if not 0 < timeout_seconds <= MAX_PASS_TIMEOUT_SECONDS:
            raise RoomError(f"The timeout must be above 0 and at most {MAX_PASS_TIMEOUT_SECONDS:g} seconds.")
        self.code = code
        self.num_players = n
        self.num_rounds = rounds
        self.timeout_seconds = float(timeout_seconds)
        # The seed fixes every deal, so it stays inside the room: never in a message.
        self._seed = secrets.randbits(62) if seed is None else seed
        self.seat_kinds: tuple[str, ...] = (
            (HUMAN,) * n if seats is None else parse_seats(seats, n)
        )
        self._human_seats = [i for i, kind in enumerate(self.seat_kinds) if kind == HUMAN]
        self._humans: list[Player] = []  # in join order; they take the human seats in order
        self._ai: dict[int, Player] = {}
        labels: dict[str, int] = {}
        for kind in self.seat_kinds:
            if kind != HUMAN:
                labels[kind] = labels.get(kind, 0) + 1
        counters: dict[str, int] = {}
        for seat, kind in enumerate(self.seat_kinds):
            if kind == HUMAN:
                continue
            counters[kind] = counters.get(kind, 0) + 1
            label = AI_AGENTS[kind][0]
            name = label if labels[kind] == 1 else f"{label} {counters[kind]}"
            self._ai[seat] = Player(name, None, agent=kind, seat=seat)
        self.status = STATUS_LOBBY
        self.state: GameState | None = None
        try:  # validates the combination with the engine's own rules
            self._config = GameConfig(n, rounds, self._seed, float(timeout_seconds))
        except ConfigError as error:  # pragma: no cover - the checks above cover it
            raise RoomError(str(error)) from None

    # ------------------------------------------------------------------ seats
    @property
    def players(self) -> list[Player]:
        """Everyone seated so far (humans and AI), in seat order."""
        return sorted([*self._humans, *self._ai.values()], key=lambda p: p.seat)

    def player_at(self, seat: int) -> Player:
        for player in self.players:
            if player.seat == seat:
                return player
        raise KeyError(seat)

    def is_ai(self, seat: int) -> bool:
        return seat in self._ai

    def ai_seats(self) -> dict[int, AgentSpec]:
        return {seat: AI_AGENTS[p.agent][1] for seat, p in self._ai.items() if p.agent}

    def _reseat(self) -> None:
        for player, seat in zip(self._humans, self._human_seats):
            player.seat = seat

    def seat_of(self, client: Hashable) -> int | None:
        for player in self._humans:
            if player.client is client:
                return player.seat
        return None

    def add_player(self, client: Hashable, name: object) -> int:
        """Seat a new human in the next free human seat; the first one is the host."""
        if self.status != STATUS_LOBBY:
            raise RoomError("This game has already started.")
        if len(self._humans) >= len(self._human_seats):
            raise RoomError("This room is full.")
        clean = clean_name(name)
        if any(p.name.casefold() == clean.casefold() for p in self.players):
            raise RoomError("That name is already taken in this room.")
        player = Player(clean, client, is_host=not self._humans)
        self._humans.append(player)
        self._reseat()
        return player.seat

    def disconnect(self, client: Hashable) -> bool:
        """Handle a closed connection. Returns True when no human is connected any
        more and the room should be removed."""
        for player in list(self._humans):
            if player.client is client:
                if self.status == STATUS_LOBBY:
                    self._humans.remove(player)
                    self._reseat()
                    if player.is_host and self._humans:
                        self._humans[0].is_host = True
                else:
                    player.client = None  # the seat stays; the game goes on
                break
        return not any(p.client is not None for p in self._humans)

    # ------------------------------------------------------------------ start
    def check_start(self, client: Hashable) -> None:
        seat = self.seat_of(client)
        if seat is None or not self.player_at(seat).is_host:
            raise RoomError("Only the host can start the game.")
        if self.status != STATUS_LOBBY:
            raise RoomError("This game has already started.")
        if len(self._humans) != len(self._human_seats):
            raise RoomError(
                f"Waiting for players: {len(self._humans)} of {len(self._human_seats)} have joined."
            )

    def start(self, client: Hashable) -> tuple:
        self.check_start(client)
        opening = new_game(self._config)
        self.state = opening.state
        self.status = STATUS_PLAYING
        return opening.events

    # ---------------------------------------------------------------- actions
    def act(self, client: Hashable, request: dict[str, Any]) -> tuple:
        """Apply the action a client asked for. The seat is the client's own."""
        seat = self.seat_of(client)
        if seat is None:
            raise RoomError("You are not in this room.")
        if self.status != STATUS_PLAYING or self.state is None:
            raise RoomError("The game is not in progress.")
        kind = request.get("action")
        if kind == "claim":
            wanted: Any = ClaimAction(seat)
        elif kind == "decline":
            wanted = DeclineAction(seat)
        elif kind == "react":
            wanted = ReactAction(seat)
        elif kind == "pass":
            chit_name = request.get("chit_name")
            if not isinstance(chit_name, str):
                raise RoomError("Choose a chit to pass.")
            wanted = NamePassAction(seat, chit_name)
        else:
            raise RoomError("Unknown action.")
        state = self.state
        engine_action = to_engine_action(state, wanted)
        if engine_action is None:
            if not legal_actions_for(state, seat):
                raise RoomError("It is not your turn.")
            raise RoomError("That action is not available right now.")
        outcome = apply_action(state, engine_action)
        if not isinstance(outcome, Accepted):
            # A legal, translated action cannot be rejected; never forward the engine's text.
            raise RoomError("The server could not apply that action.")
        return self._advance(outcome)

    def timer_target(self) -> tuple[int, int] | None:
        """(expected sequence number, seat) for the host timer that should be
        running now, or None. Exists at every single decision point and for the
        last pending reactor only (engine `timeout_action`)."""
        if self.status != STATUS_PLAYING or self.state is None:
            return None
        action = timeout_action(self.state)
        if action is None:
            return None
        return self.state.next_seq, action.seat

    def apply_timeout(self, expected_seq: int) -> tuple | None:
        """Issue the host timeout, but only if the game is still at the decision
        the timer was started for. Returns None for a stale timer."""
        if self.status != STATUS_PLAYING or self.state is None:
            return None
        if self.state.next_seq != expected_seq:
            return None
        action = timeout_action(self.state)
        if not isinstance(action, TimeoutAction):
            return None
        outcome = apply_action(self.state, action)
        if not isinstance(outcome, Accepted):
            return None
        return self._advance(outcome)

    # --------------------------------------------------------------- AI seats
    def pending_ai_actor(self, faulted: frozenset[int] | set[int] = frozenset()) -> int | None:
        """The AI seat that should act next, or None when a human (or nobody) is
        up. A single decision belongs to the engine's decision seat. In the
        reaction phase the seeded reaction queue (the same one the simulation
        runner uses) picks which pending AI goes first. `faulted` AIs are skipped."""
        if self.status != STATUS_PLAYING or self.state is None:
            return None
        state = self.state
        if state.phase in (Phase.INITIAL_CLAIMS, Phase.PASSING):
            return state.decision_seat if self.is_ai(state.decision_seat) else None
        if state.phase is Phase.WIN_DECLARED:
            pending = set(pending_reactors(state))
            for seat in reaction_order_for_state(state):
                if seat in pending and self.is_ai(seat) and seat not in faulted:
                    return seat
        return None

    def unresolvable(self, faulted: set[int]) -> bool:
        """Several reactors are pending and every one is an AI that failed: the
        rules give the host no way to move on (no timeout while 2+ are pending)."""
        if self.status != STATUS_PLAYING or self.state is None or self.state.phase is not Phase.WIN_DECLARED:
            return False
        pending = pending_reactors(self.state)
        return len(pending) >= 2 and all(self.is_ai(s) and s in faulted for s in pending)

    def apply_ai_action(self, seat: int, action: Any) -> tuple:
        """Apply an action an AI seat chose. The server already validated it
        against that seat's legal actions; this guards the seat and the engine."""
        if not self.is_ai(seat) or getattr(action, "seat", None) != seat:
            raise RoomError("That seat is not controlled by an AI.")
        if self.status != STATUS_PLAYING or self.state is None:
            raise RoomError("The game is not in progress.")
        outcome = apply_action(self.state, action)
        if not isinstance(outcome, Accepted):
            raise RoomError("The server could not apply that action.")
        return self._advance(outcome)

    def _advance(self, outcome: Accepted) -> tuple:
        self.state = outcome.state
        if outcome.state.phase is Phase.GAME_OVER:
            self.status = STATUS_FINISHED
        return outcome.events

    # --------------------------------------------------------------- messages
    def room_info(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "num_players": self.num_players,
            "num_rounds": self.num_rounds,
            "timeout_seconds": self.timeout_seconds,
            "mode": "ai" if self._ai else "human",
            "seat_kinds": list(self.seat_kinds),
            "players": [
                {"seat": p.seat, "name": p.name, "connected": p.connected, "is_host": p.is_host,
                 "ai": p.is_ai, "agent": AI_AGENTS[p.agent][0] if p.agent else None}
                for p in self.players
            ],
        }

    def state_message(
        self, client: Hashable, events: tuple = (), timer: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """The message for one participant, or None if they are not seated."""
        seat = self.seat_of(client)
        if seat is None:
            return None
        message: dict[str, Any] = {
            "type": "state",
            "room": self.room_info(),
            "me": {"seat": seat, "name": self.player_at(seat).name, "is_host": self.player_at(seat).is_host},
            "observation": None,
            "legal_actions": [],
            "events": [],
            "standings": None,
            "timer": timer,
        }
        if self.state is not None:
            state = self.state
            message["observation"] = observe(state, seat).to_dict()
            message["legal_actions"] = [action_to_dict(a) for a in legal_actions_for(state, seat)]
            message["events"] = [observe_event(event, seat) for event in events]
            if self.status == STATUS_FINISHED:
                message["standings"] = self.standings()
        return message

    def standings(self) -> list[dict[str, Any]]:
        assert self.state is not None
        scores = tuple(self.state.scores)
        ranks = competition_ranks(scores)
        rows = [
            {"seat": seat, "name": self.player_at(seat).name, "score": scores[seat], "rank": ranks[seat],
             "ai": self.is_ai(seat)}
            for seat in range(len(scores))
        ]
        return sorted(rows, key=lambda row: (row["rank"], row["seat"]))
