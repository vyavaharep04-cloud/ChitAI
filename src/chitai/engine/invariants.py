"""Engine invariants (§5A, constraint 8). M2: initial phase. M3: passing. M4: scores,
round completion and the terminal state. M5: reaction phase and win scores. M6: anti-stall streaks.

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
from .deal import FIRST_ATTEMPT, initiator_for_round, rotation_initiator
from .rules import CONSECUTIVE_PASS_LIMIT, initial_claim_order, is_valid_claim
from .scoring import false_claim_penalty, valid_win_round_total, winner_score
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
    over = state.phase is Phase.GAME_OVER
    # While a round is being played its index is below the configured total;
    # a finished game has completed exactly the configured total (M4).
    upper = config.num_rounds if over else config.num_rounds - 1
    _require(
        _is_int(state.completed_rounds) and 0 <= state.completed_rounds <= upper,
        f"completed_rounds out of range: {state.completed_rounds!r}",
    )
    _require(
        _is_int(state.attempt) and state.attempt >= FIRST_ATTEMPT,
        f"attempt must be an integer >= {FIRST_ATTEMPT}: {state.attempt!r}",
    )
    expected_initiator = (
        rotation_initiator(n, state.completed_rounds)
        if over
        else initiator_for_round(config, state.completed_rounds)
    )
    _require(
        state.initiator == expected_initiator,
        f"initiator {state.initiator!r} does not match round {state.completed_rounds}",
    )
    _require(_is_int(state.next_seq) and state.next_seq >= 0, f"bad next_seq {state.next_seq!r}")
    _require(
        isinstance(state.scores, tuple) and len(state.scores) == n and all(map(_is_int, state.scores)),
        f"scores must be a tuple of {n} integers: {state.scores!r}",
    )
    _check_scores(state)
    _check_pass_streaks(state)

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

    if over:
        _require(state.attempt == FIRST_ATTEMPT, f"a finished game has attempt 1, got {state.attempt}")
        _require(resolved == 0, f"a finished game has no initial claims resolved, got {resolved}")
        _require(state.decision_seat is None and state.decision_kind is None, "no decision point expected")
        _require(_no_outcome(state), "a finished game has no winner, false claimant or claim kind")
        _check_final_hand_shape(state)
    elif state.phase is Phase.INITIAL_CLAIMS:
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
        _check_reactions(state, won)


def _no_outcome(state: GameState) -> bool:
    return (
        state.winner is None
        and state.false_claimant is None
        and state.claim_decision_kind is None
        and state.reaction_order == ()
    )


def _check_reactions(state: GameState, won: bool) -> None:
    """M5: reactions exist only after a valid win. They are distinct non-winner
    seats; the round completes when all N-1 have reacted, so a returned state
    has fewer than N-1 (the full-length state is transient and only validated
    inside the engine)."""
    n = state.config.num_players
    order = state.reaction_order
    _require(isinstance(order, tuple) and all(map(_is_int, order)), f"bad reaction_order {order!r}")
    if not won:
        _require(order == (), "a false claim has no reactions")
        return
    _require(len(order) <= n - 1, f"{len(order)} reactions exceed the {n - 1} non-winners")
    _require(len(set(order)) == len(order), f"a seat reacted twice: {order!r}")
    _require(
        all(0 <= seat < n and seat != state.winner for seat in order),
        f"reaction_order {order!r} contains the winner or an invalid seat",
    )


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


def _check_scores(state: GameState) -> None:
    """Score values reachable through M5. Scores change only when a round
    completes. A false-claim round adds -(N-1) to one seat; a valid-win round adds
    N to the winner and N-1, ..., 1 to the others (N(N+1)/2 in total). So, with
    R completed rounds, each seat lies in [-(N-1)R, N*R], and the grand total
    must equal W*N(N+1)/2 - F*(N-1) for some W valid wins and F false claims
    with W + F <= R. ("At most": a game started from a crafted later round has
    completed fewer rounds than its index.) Scores are unchanged while a win's
    reactions are pending, so the same check applies in every phase."""
    n = state.config.num_players
    penalty = false_claim_penalty(n)
    rounds = state.completed_rounds
    for seat, score in enumerate(state.scores):
        _require(
            -penalty * rounds <= score <= winner_score(n) * rounds,
            f"seat {seat} score {score} is outside [{-penalty * rounds}, {winner_score(n) * rounds}] "
            f"after {rounds} completed rounds",
        )
    win_total = valid_win_round_total(n)
    total = sum(state.scores)
    reachable = False
    for wins in range(rounds + 1):
        deficit = wins * win_total - total  # = F * (N-1) for the implied false-claim count F
        if deficit >= 0 and deficit % penalty == 0 and deficit // penalty <= rounds - wins:
            reachable = True
            break
    _require(
        reachable,
        f"total score {total} is not reachable with {rounds} completed rounds "
        f"(valid win = +{win_total}, false claim = -{penalty})",
    )


def _check_pass_streaks(state: GameState) -> None:
    """M6: `pass_streaks` is a tuple of `(seat, chit_name, count)` sorted by
    strictly increasing seat, with a chit name in play and a count from 1 to
    `CONSECUTIVE_PASS_LIMIT - 1` (the limit itself is a draw and never rests in
    state). No pass has happened yet while initial claims are open, and a
    finished game has cleared its streaks, so both must be empty."""
    n = state.config.num_players
    streaks = state.pass_streaks
    _require(isinstance(streaks, tuple), f"pass_streaks must be a tuple, got {streaks!r}")
    names = set(chit_names_for(n))
    previous = -1
    for entry in streaks:
        _require(
            isinstance(entry, tuple) and len(entry) == 3,
            f"a pass streak must be (seat, chit_name, count): {entry!r}",
        )
        seat, name, count = entry
        _require(_is_int(seat) and 0 <= seat < n, f"bad streak seat {seat!r}")
        _require(seat > previous, f"pass_streaks must be sorted with one entry per seat: {streaks!r}")
        previous = seat
        _require(name in names, f"streak chit name {name!r} is not in play")
        _require(
            _is_int(count) and 1 <= count < CONSECUTIVE_PASS_LIMIT,
            f"streak count {count!r} must be in [1, {CONSECUTIVE_PASS_LIMIT - 1}]",
        )
    if state.phase in (Phase.INITIAL_CLAIMS, Phase.GAME_OVER):
        _require(streaks == (), f"no pass streaks expected in {state.phase.value}: {streaks!r}")


def _check_final_hand_shape(state: GameState) -> None:
    """A finished game keeps the hands of its last claim. Chit conservation is
    checked above for every phase; here only the shape: all hands hold four, or
    the claim was a receiver's, so one seat holds five and one (the initiator at
    that time) holds three."""
    sizes = sorted(len(hand) for hand in state.hands)
    n = state.config.num_players
    all_four = [CHITS_PER_HAND] * n
    receive_shape = sorted([CHITS_PER_HAND - 1, CHITS_PER_HAND + 1] + [CHITS_PER_HAND] * (n - 2))
    _require(sizes in (all_four, receive_shape), f"final hand sizes {sizes} are not a claim-time shape")
