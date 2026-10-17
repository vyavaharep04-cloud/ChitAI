"""Engine invariants (§5A, constraint 8). Milestone 2 scope.

`check_invariants` is called by the engine on every state it produces. A
violation means an engine bug (or a malformed deal handed to the engine) and
raises `InvariantViolation`; it is never a normal rejection of a player action.

Only M2 states exist, and every M2 state is a resting state in which all hands
hold four chits. Milestone 3 extends the hand-size rule for the three-chit
initiator and five-chit receiver states.
"""

from __future__ import annotations

from collections import Counter

from .chits import CHITS_PER_HAND, COPIES_PER_NAME, Chit, build_deck, chit_names_for
from .deal import FIRST_ATTEMPT, initiator_for_round
from .rules import initial_claim_order, is_valid_initial_claim
from .state import DecisionKind, GameState, Phase


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
        # Every M2 state is a resting state: all hands hold four chits.
        _require(len(hand) == CHITS_PER_HAND, f"seat {seat} holds {len(hand)} chits, expected 4")

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

    if state.phase is Phase.INITIAL_CLAIMS:
        _require(resolved < n, "initial claims all resolved but phase is still INITIAL_CLAIMS")
        _require(state.decision_kind is DecisionKind.INITIAL_CLAIM, "wrong decision kind")
        _require(
            state.decision_seat == order[resolved],
            f"decision seat {state.decision_seat!r} != expected {order[resolved]}",
        )
        _require(state.winner is None and state.false_claimant is None, "outcome set too early")
    elif state.phase is Phase.PASSING:
        _require(resolved == n, "PASSING requires every initial opportunity resolved")
        _require(state.decision_kind is DecisionKind.INITIATOR_FIRST_PASS, "wrong decision kind")
        _require(state.decision_seat == state.initiator, "initiator must make the first pass")
        _require(state.winner is None and state.false_claimant is None, "outcome set in PASSING")
    else:  # WIN_DECLARED or FALSE_CLAIM
        _require(1 <= resolved <= n, f"bad initial_claims_resolved {resolved} for {state.phase}")
        _require(state.decision_seat is None and state.decision_kind is None, "no decision point expected")
        claimant = order[resolved - 1]
        if state.phase is Phase.WIN_DECLARED:
            _require(state.winner == claimant and state.false_claimant is None, "inconsistent winner")
            _require(is_valid_initial_claim(state.hands[claimant]), "winner's hand does not match")
        else:
            _require(state.false_claimant == claimant and state.winner is None, "inconsistent claimant")
            _require(
                not is_valid_initial_claim(state.hands[claimant]),
                "false claimant's hand actually matches",
            )
