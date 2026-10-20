"""The behavioural estimator behind MindBot (M9, memory-only inference).

Hypothesis (a hypothesis, not a fact): an opponent tends to collect ONE chit name and
to pass other names. MindBot models only its immediate predecessor (the seat that
passes to it) and keeps an *uncertain* belief about which name that seat is collecting.

Information used: the agent's own hand at its own decision points and its own previous
action. Nothing else: no opponent hand, no private chit exchanged between other players,
no engine state, no seed, no reaction order, no timing.

Why a hand difference reveals the received chit (verified against the engine, see
tests/agents/test_belief.py and PROJECT_CONTEXT.md, M9 entry): between two of its own
decisions inside one deal a seat receives exactly one chit, from its predecessor, and
passes at most one chit itself. So::

    received = hand_now - (hand_at_previous_decision - name_it_passed_then)

With the multiset difference this is empty at the initiator's first pass (nothing has
arrived yet: 4 -> 4), one name at a non-initiator's receive (4 -> 5) and one name at the
initiator's return (3 -> 4). Any other difference means the transition cannot be
reconstructed; the estimator then leaves the belief untouched and resynchronises.

Belief model
------------
* Prior at a deal's first observation (own four dealt chits): weight(name) =
  COPIES_PER_NAME - copies held. Names I hold fewer of have more copies elsewhere, so
  they are likelier to be what someone else is collecting. A name I hold four times has
  weight 0.
* Evidence: the predecessor passed me name n. A collector passes its target only by
  leakage, so weight(n) is multiplied by `epsilon` (0 < epsilon <= 1; epsilon = 1
  ignores the evidence). The default 0.2 is an *untuned* round number, to be varied in a
  sensitivity check, not a fitted value.
* The weights are renormalised after every update, so `probabilities()` always sums to 1.

Every public method is total: no input makes it raise, so a bookkeeping problem can
never turn into an agent fault. Pure standard library; no randomness, so the same
inputs always give the same belief.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

# The engine's deal rules (CHITS_PER_HAND, COPIES_PER_NAME), restated here like RuleBot's
# CLAIM_COPIES so that agents import nothing from the engine beyond action classes.
# tests/agents/test_belief.py cross-checks both values against the engine.
CHITS_PER_HAND = 4
COPIES_PER_NAME = 4

DEFAULT_EPSILON = 0.2
_INFINITY = float("inf")

# Outcomes of `observe_hand`.
RECEIVED = "received"  # exactly one chit arrived; the belief was updated
NO_CHANGE = "no_change"  # nothing arrived (the initiator's first pass); belief unchanged
UNRECONSTRUCTABLE = "unreconstructable"  # belief left untouched, bookkeeping resynchronised
INACTIVE = "inactive"  # no deal has been started


def validate_epsilon(epsilon: object) -> float:
    """`epsilon` as a float. Raises TypeError/ValueError unless 0 < epsilon <= 1."""
    if isinstance(epsilon, bool) or not isinstance(epsilon, (int, float)):
        raise TypeError(f"epsilon must be a number, got {epsilon!r}")
    value = float(epsilon)
    if not 0.0 < value <= 1.0:  # also false for NaN; infinity is above 1
        raise ValueError(f"epsilon must satisfy 0 < epsilon <= 1, got {epsilon!r}")
    return value


class BeliefEstimator:
    """Belief over which chit name the predecessor is collecting (one deal at a time)."""

    def __init__(self, epsilon: float = DEFAULT_EPSILON) -> None:
        self.epsilon = validate_epsilon(epsilon)
        self._names: tuple[str, ...] = ()
        self._prior: dict[str, float] = {}
        self._weights: dict[str, float] = {}
        self._expected: Counter[str] | None = None
        self._active = False
        self.last_received: str | None = None  # name read by the latest RECEIVED, else None
        self._stats = {
            "deals": 0,
            "updates": 0,
            "no_change": 0,
            "unreconstructable": 0,
            "uniform_priors": 0,
            "normalisation_resets": 0,
        }

    # --- deal boundary ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    def start_deal(self, chit_names: Sequence[str], hand: Sequence[str], at_deal_start: bool) -> None:
        """Begin a fresh belief for a new deal or attempt (call on every deal boundary).

        `hand` is the agent's own hand now. When `at_deal_start` is true and the hand is
        the four dealt chits, the prior comes from it. Otherwise (the first sight of a
        deal is mid-deal, so the hand includes a received chit that cannot be separated
        out) the prior is uniform and `uniform_priors` is incremented.
        """
        names = tuple(name for name in chit_names if isinstance(name, str))
        self._names = names
        hand_names = tuple(hand)
        held = Counter(name for name in hand_names if isinstance(name, str))
        reliable = (
            at_deal_start
            and len(hand_names) == CHITS_PER_HAND
            and all(name in names for name in held)
            and all(count <= COPIES_PER_NAME for count in held.values())
        )
        if reliable:
            weights = {name: float(COPIES_PER_NAME - held[name]) for name in names}
        else:
            weights = {name: 1.0 for name in names}
            self._stats["uniform_priors"] += 1
        if not names or not self._normalise(weights):
            weights = {name: 1.0 for name in names}
            self._normalise(weights)
        self._prior = dict(weights)
        self._weights = dict(weights)
        self._expected = self._counter_or_none(hand_names, names)
        self._active = bool(names)
        self._stats["deals"] += 1

    # --- evidence -----------------------------------------------------------------------

    def observe_hand(self, hand: Sequence[str]) -> str:
        """Compare `hand` with what was expected after the previous decision.

        Updates the belief only when exactly one chit name arrived. Returns RECEIVED,
        NO_CHANGE, UNRECONSTRUCTABLE or INACTIVE. Never raises.
        """
        self.last_received = None
        if not self._active:
            return INACTIVE
        current = self._counter_or_none(tuple(hand), self._names)
        expected = self._expected
        if current is None or expected is None:
            self._stats["unreconstructable"] += 1
            return UNRECONSTRUCTABLE
        arrived = current - expected
        missing = expected - current
        if missing or sum(arrived.values()) > 1:
            self._stats["unreconstructable"] += 1
            return UNRECONSTRUCTABLE
        if not arrived:
            self._stats["no_change"] += 1
            return NO_CHANGE
        (name,) = arrived  # exactly one name with count one
        updated = dict(self._weights)
        updated[name] *= self.epsilon
        if self._normalise(updated):
            self._weights = updated
        else:  # underflow or corruption: fall back to the deal's prior rather than guess
            self._weights = dict(self._prior)
            self._stats["normalisation_resets"] += 1
        self._stats["updates"] += 1
        self.last_received = name
        return RECEIVED

    def after_decision(self, hand: Sequence[str], passed_name: str | None) -> None:
        """Record the hand the agent just decided with and what it passed (None for a
        claim, decline or reaction). The next `observe_hand` is judged against it."""
        if not self._active:
            return
        counter = self._counter_or_none(tuple(hand), self._names)
        if counter is not None and passed_name is not None:
            if counter[passed_name] > 0:
                counter[passed_name] -= 1
                counter += Counter()  # drop zero entries
            else:
                counter = None  # the pass does not match the hand: cannot reconstruct next time
        self._expected = counter

    # --- readout ------------------------------------------------------------------------

    def probabilities(self) -> dict[str, float]:
        """Belief that the predecessor is collecting each name (sums to 1; empty if inactive)."""
        return dict(self._weights) if self._active else {}

    def probability(self, name: str) -> float:
        return self._weights.get(name, 0.0) if self._active else 0.0

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    # --- helpers ------------------------------------------------------------------------

    @staticmethod
    def _counter_or_none(hand: tuple, names: tuple[str, ...]) -> Counter[str] | None:
        """The hand as a multiset, or None when it holds an unknown name or too many copies."""
        if not all(isinstance(name, str) and name in names for name in hand):
            return None
        counter = Counter(hand)
        if any(count > COPIES_PER_NAME for count in counter.values()):
            return None
        return counter

    @staticmethod
    def _normalise(weights: dict[str, float]) -> bool:
        """Scale `weights` to sum to 1 in place. False (weights untouched) if impossible."""
        total = sum(weights.values())
        if not weights or not 0.0 < total < _INFINITY:  # rejects NaN, zero, negative, infinite
            return False
        for name in weights:
            weights[name] /= total
        return True


__all__ = [
    "CHITS_PER_HAND",
    "COPIES_PER_NAME",
    "DEFAULT_EPSILON",
    "INACTIVE",
    "NO_CHANGE",
    "RECEIVED",
    "UNRECONSTRUCTABLE",
    "BeliefEstimator",
    "validate_epsilon",
]
