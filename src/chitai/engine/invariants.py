"""Engine invariants (§5A, constraint 8). M2: initial phase. M3: passing.

`check_invariants` is called by the engine on every state it produces. A
violation means an engine bug (or a malformed deal handed to the engine) and
raises `InvariantViolation`; it is never a normal rejection of a player action.

Hand sizes follow the §3A.4 table. Delivery is atomic, so every state is a
resting state and the chits held always total exactly 4N:

* all hands hold four, except
* while a non-initiator is deciding after a receive: the initiator holds three
  and that receiver holds five (a claim made there keeps this shape).
"""

from __future__ import annotations

from collections import Counter

from .chits import CHITS_PER_HAND, COPIES_PER_NAME, Chit, build_deck, chit_names_for
from .deal import FIRST_ATTEMPT, initiator_for_round
from .rules import initial_claim_order, is_valid_claim
from .state import CLAIM_KINDS, DecisionKind, GameState, Phase


class InvariantViolation(RuntimeError):
    """An internal engine invariant failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvariantViolation(message)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_invariants(state: GameState) -> None:
    config = state.config
    n = config.num_players

    # --- counters and identity -------------------------------------------
    _require(isinstance(state.phase, Phase), f"phase must be a Phase, got {state.phase!r}")
    _require(
        _is_int(state.completed_rounds) and 0 <= state.completed_rounds < config.num_rounds,
        f"completed_rounds out of range: {state.completed_rounds!r}",
    )
    _require(
        _is_int(state.attempt) and state.attempt >= FIRST_ATTEMPT,
        f"attempt must be an integer >= {FIRST_ATTEMPT}: {state.attempt!r}",
    )
    _require(
        state.initiator == initiator_for_round(config, state.completed_rounds),
        f"initiator {state.initiator!r} does not match round {state.completed_rounds}",
    )
    _require(_is_int(state.next_seq) and state.next_seq >= 0, f"bad next_seq {state.next_seq!r}")
    _require(
        isinstance(state.scores, tuple) and len(state.scores) == n and all(map(_is_int, state.scores)),
        f"scores must be a tuple of {n} integers: {state.scores!r}",
    )

    # --- hands: sizes, 4N total, four copies per name, no duplicates -----
    _require(
        isinstance(state.hands, tuple) and len(state.hands) == n,
        f"expected {n} hands, got {len(state.hands) if isinstance(state.hands, tuple) else state.hands!r}",
    )
    for seat, hand in enumerate(state.hands):
        _require(
            isinstance(hand, tuple) and all(isinstance(c, Chit) for c in hand),
            f"seat {seat} hand must be a tuple of Chit",
        )

    all_chits = [chit for hand in state.hands for chit in hand]
    _require(len(all_chits) == CHITS_PER_HAND * n, f"total chits {len(all_chits)} != {4 * n}")
    instance_counts = Counter(all_chits)
    duplicated = [c for c, k in instance_counts.items() if k > 1]
    _require(not duplicated, f"physical chit instance appears more than once: {duplicated}")
    name_counts = Counter(chit.name for chit in all_chits)
    _require(
        set(name_counts) == set(chit_names_for(n)),
        f"chit names in play {sorted(name_counts)} != {list(chit_names_for(n))}",
    )
    _require(
        all(k == COPIES_PER_NAME for k in name_counts.values()),
        f"each name must appear exactly {COPIES_PER_NAME} times: {dict(name_counts)}",
    )
    _require(
        set(all_chits) == set(build_deck(n)),
        "chits in play are not exactly the fixed deck",
    )

    # --- phase / decision-point consistency ------------------------------
    resolved = state.initial_claims_resolved
    _require(_is_int(resolved) and 0 <= resolved <= n, f"bad initial_claims_resolved {resolved!r}")
    order = initial_claim_order(n, state.initiator)
    _require(
        state.claim_decision_kind is None or isinstance(state.claim_decision_kind, DecisionKind),
        f"bad claim_decision_kind {state.claim_decision_kind!r}",
    )

    if state.phase is Phase.INITIAL_CLAIMS:
        _require(resolved < n, "initial claims all resolved but phase is still INITIAL_CLAIMS")
        _require(state.decision_kind is DecisionKind.INITIAL_CLAIM, "wrong decision kind")
        _require(
            state.decision_seat == order[resolved],
            f"decision seat {state.decision_seat!r} != expected {order[resolved]}",
        )
        _require(_no_outcome(state), "outcome set too early")
        _check_hand_sizes(state, DecisionKind.INITIAL_CLAIM, state.decision_seat)
    elif state.phase is Phase.PASSING:
        _require(resolved == n, "PASSING requires every initial opportunity resolved")
        _require(_no_outcome(state), "outcome set in PASSING")
        kind, seat = state.decision_kind, state.decision_seat
        _require(
            kind
            in (
                DecisionKind.INITIATOR_FIRST_PASS,
                DecisionKind.NON_INITIATOR_RECEIVE,
                DecisionKind.INITIATOR_RETURN,
            ),
            f"decision kind {kind!r} is not a passing decision",
        )
        _require(_is_int(seat) and 0 <= seat < n, f"bad decision seat {seat!r}")
        if kind is DecisionKind.NON_INITIATOR_RECEIVE:
            _require(seat != state.initiator, "a non-initiator receive cannot be at the initiator")
        else:  # first pass or chit returned: the initiator is deciding
            _require(seat == state.initiator, f"{kind.value} must be the initiator's decision")
        _check_hand_sizes(state, kind, seat)
    else:  # WIN_DECLARED or FALSE_CLAIM
        _require(1 <= resolved <= n, f"bad initial_claims_resolved {resolved} for {state.phase}")
        _require(state.decision_seat is None and state.decision_kind is None, "no decision point expected")
        kind = state.claim_decision_kind
        _require(kind in CLAIM_KINDS, f"an outcome needs a claim decision kind, got {kind!r}")
        won = state.phase is Phase.WIN_DECLARED
        claimant = state.winner if won else state.false_claimant
        _require(
            claimant is not None and (state.false_claimant is None if won else state.winner is None),
            "inconsistent winner/false claimant",
        )
        _require(_is_int(claimant) and 0 <= claimant < n, f"bad claimant {claimant!r}")
        if kind is DecisionKind.INITIAL_CLAIM:
            _require(claimant == order[resolved - 1], "claimant is not the last initial opportunity")
        else:
            _require(resolved == n, "a passing-phase claim requires every initial opportunity resolved")
            if kind is DecisionKind.NON_INITIATOR_RECEIVE:
                _require(claimant != state.initiator, "a receiver claim cannot come from the initiator")
            else:
                _require(claimant == state.initiator, "an initiator-return claim must be the initiator's")
        _check_hand_sizes(state, kind, claimant)
        _require(
            is_valid_claim(kind, state.hands[claimant]) is won,
            "winner's hand does not match" if won else "false claimant's hand actually matches",
        )


def _no_outcome(state: GameState) -> bool:
    return state.winner is None and state.false_claimant is None and state.claim_decision_kind is None


def _check_hand_sizes(state: GameState, kind: DecisionKind, seat: int) -> None:
    """The §3A.4 hand-size table. Only the receive state is off-shape: the
    initiator holds three and the deciding receiver holds five."""
    n = state.config.num_players
    expected = [CHITS_PER_HAND] * n
    if kind is DecisionKind.NON_INITIATOR_RECEIVE:
        expected[state.initiator] = CHITS_PER_HAND - 1
        expected[seat] = CHITS_PER_HAND + 1
    actual = [len(hand) for hand in state.hands]
    _require(actual == expected, f"hand sizes {actual} != expected {expected} at {kind.value}")
