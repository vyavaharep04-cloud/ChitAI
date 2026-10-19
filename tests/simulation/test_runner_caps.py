"""Draw cap, action cap, precedence and stopped-game invariants (M8 Stage 3).

Every expectation is derived from the engine's own events (the spy log of accepted
actions), not from hard-coded outcomes. Cap values used here are arbitrary test fixtures
and are not proposals: the caps have no default.
"""

from __future__ import annotations

import pytest

from chitai.engine import (
    Accepted,
    AttemptDrawn,
    DealEvent,
    GameCompleted,
    Phase,
)
from chitai.simulation import (
    STATUS_ACTION_CAP_REACHED,
    STATUS_AGENT_FAULT_UNRESOLVABLE,
    STATUS_COMPLETED,
    STATUS_DRAW_CAP_REACHED,
    STOPPED_STATUSES,
)

from .runner_support import (
    BIG_ACTIONS,
    Trigger,
    claim_policy,
    crafted_start,
    misbehaving_policy,
    never_rejected,
    play,
    rule_policy,
    sim_config,
    stall_policy,
)


def stall_then_claim(observation, legal, call):
    """Stalls the first attempt of every round; claims (falsely) from the second attempt on."""
    return claim_policy(observation, legal, call) if observation.attempt >= 2 else stall_policy(observation, legal, call)


def claim_two_rounds_then_stall(observation, legal, call):
    return claim_policy(observation, legal, call) if observation.completed_rounds < 2 else stall_policy(observation, legal, call)


def attempt_lengths(steps):
    """Accepted actions per attempt, from the spy log: [(completed_round, attempt, count, ended)]."""
    lengths, count, key = [], 0, None
    for step in steps:
        key = key or (step.state.completed_rounds, step.state.attempt)
        count += 1
        ended = any(isinstance(e, DealEvent) for e in step.result.events) or step.result.state.phase is Phase.GAME_OVER
        if ended:
            lengths.append((*key, count))
            count, key = 0, None
    if count:
        lengths.append((*key, count))
    return lengths


def stalled(n=4, roles=None, policies=None, **kwargs):
    roles = roles or ["s"] * n
    return play(sim_config(n, roles, **kwargs), 0, policies or {"s": stall_policy})


# --- draw cap ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("cap", [0, 1, 3])
def test_the_draw_cap_stops_on_the_first_draw_beyond_the_allowed_restarts(cap):
    result, steps, _ = stalled(draws=cap)
    drawn = [e for step in steps for e in step.result.events if isinstance(e, AttemptDrawn)]
    assert result.status == STATUS_DRAW_CAP_REACHED
    assert len(drawn) == cap + 1  # `cap` redeals were allowed; the next draw stops the game
    assert result.stopped_attempt == cap + 2 and result.draw_restarts == cap + 1
    assert result.completed_rounds == 0 and result.rounds == ()
    assert steps[-1].result.state.attempt == result.stopped_attempt
    assert never_rejected(steps)


def test_a_draw_cap_leaves_scores_untouched_and_the_record_rankless():
    result, steps, _ = play(sim_config(4, ["s"] * 4, draws=0), 0, {"s": claim_two_rounds_then_stall})
    assert result.status == STATUS_DRAW_CAP_REACHED
    assert result.completed_rounds == 2 and len(result.rounds) == 2
    assert [s.score for s in result.seats] == [-3, -3, 0, 0]  # the two completed rounds' false claims
    assert tuple(s.score for s in result.seats) == steps[-1].result.state.scores
    assert result.stopped_attempt == 2 and result.draw_restarts == 1
    assert all(s.rank is None and s.tied is None for s in result.seats) and result.winning_seats == ()


def test_the_draw_count_restarts_in_every_round():
    # One redeal per round is allowed, yet the game finishes with four restarts in total.
    result, steps, _ = play(sim_config(4, ["s"] * 4, draws=1), 0, {"s": stall_then_claim})
    assert result.status == STATUS_COMPLETED
    assert [r.attempts for r in result.rounds] == [2, 2, 2, 2]
    assert result.draw_restarts == 4
    assert sum(isinstance(e, AttemptDrawn) for step in steps for e in step.result.events) == 4
    # ...but the same game is stopped by a cap of zero at its first draw.
    capped, _, _ = play(sim_config(4, ["s"] * 4, draws=0), 0, {"s": stall_then_claim})
    assert capped.status == STATUS_DRAW_CAP_REACHED and capped.completed_rounds == 0


# --- action cap -------------------------------------------------------------------------------------


def test_an_attempt_ending_on_its_a_th_action_is_not_capped_but_one_still_running_is():
    reference, steps, _ = play(sim_config(4, ["s"] * 4), 0, {"s": stall_then_claim})
    assert reference.status == STATUS_COMPLETED
    lengths = attempt_lengths(steps)
    longest = max(count for *_, count in lengths)
    assert longest > 4, "the stalled first attempts are long"

    exact, _, _ = play(sim_config(4, ["s"] * 4, actions=longest), 0, {"s": stall_then_claim})
    assert exact == reference  # the longest attempt ends on its A-th action: not capped

    capped, capped_steps, _ = play(sim_config(4, ["s"] * 4, actions=longest - 1), 0, {"s": stall_then_claim})
    assert capped.status == STATUS_ACTION_CAP_REACHED
    # It stops in the first attempt that needs more than A actions, right after its A-th action.
    first_long = next(i for i, (*_, count) in enumerate(lengths) if count > longest - 1)
    assert capped.actions == sum(count for *_, count in lengths[:first_long]) + (longest - 1)
    assert (capped.completed_rounds, capped.stopped_attempt) == lengths[first_long][:2]
    assert len(capped_steps) == capped.actions


def test_the_action_counter_restarts_on_every_new_attempt_and_round():
    # With A equal to the longest attempt the whole game completes although it has far more than
    # A actions in total, so neither a draw nor a completed round carries a count forward.
    reference, steps, _ = play(sim_config(4, ["s"] * 4), 0, {"s": stall_then_claim})
    longest = max(count for *_, count in attempt_lengths(steps))
    assert reference.actions > 2 * longest
    result, _, _ = play(sim_config(4, ["s"] * 4, actions=longest), 0, {"s": stall_then_claim})
    assert result.completed and result.actions == reference.actions


def test_reactions_and_the_claim_count_toward_the_attempt():
    # A crafted valid win by seat 0: one claim plus three reactions end the round on action 4.
    config = lambda a: sim_config(4, ["c"] * 4, actions=a)  # noqa: E731
    exact, steps, _ = play(config(4), 0, {"c": claim_policy}, crafted_start({0}))
    assert exact.completed and attempt_lengths(steps)[0] == (0, 1, 4)
    capped, _, _ = play(config(3), 0, {"c": claim_policy}, crafted_start({0}))
    assert capped.status == STATUS_ACTION_CAP_REACHED
    assert (capped.actions, capped.completed_rounds, capped.stopped_attempt) == (3, 0, 1)
    assert capped.rounds == () and all(s.score == 0 for s in capped.seats)  # the win was never scored


def test_a_host_timeout_counts_as_one_action():
    # Seat 0 faults on its first decision; the host-issued timeout (an automatic decline) is action 1,
    # then seat 1's claim ends the round on action 2.
    def trigger():
        return Trigger(lambda o: o.phase == "initial_claims")

    policies = lambda: {"m": misbehaving_policy("none", trigger()), "c": claim_policy}  # noqa: E731
    roles = ["m", "c", "c", "c"]
    exact, steps, _ = play(sim_config(4, roles, actions=2), 0, policies(), crafted_start(set()))
    assert exact.completed and attempt_lengths(steps)[0] == (0, 1, 2)
    assert exact.seats[0].timeouts == 1 and exact.seats[0].agent_faults == 1
    capped, _, _ = play(sim_config(4, roles, actions=1), 0, policies(), crafted_start(set()))
    assert capped.status == STATUS_ACTION_CAP_REACHED and capped.actions == 1
    assert capped.seats[0].timeouts == 1


def test_a_rejected_choice_and_a_reaction_deferral_do_not_count():
    # The valid win takes 4 accepted actions; one reactor faults first (deferral, no engine action).
    # A = 4 still completes the round, so the deferral was not counted.
    trigger = Trigger(lambda o: o.phase == "win_declared" and len(o.pending_reactors) > 1)
    policies = {"m": misbehaving_policy("illegal", trigger)}
    result, steps, _ = play(sim_config(4, ["m"] * 4, actions=4), 0, policies, crafted_start({0}))
    assert attempt_lengths(steps)[0] == (0, 1, 4) and result.rounds[0].outcome == "valid_win"
    assert sum(s.agent_faults for s in result.seats) == 1


# --- precedence --------------------------------------------------------------------------------------


def test_a_game_that_ends_on_its_final_action_completes_even_when_that_action_reaches_a_cap():
    # Every round is a single (false) claim, so with A = 1 the last action both ends the game and
    # is the attempt's A-th action: game over wins.
    result, steps, _ = play(sim_config(4, ["c"] * 4, actions=1, draws=0), 0, {"c": claim_policy}, crafted_start(set()))
    assert result.status == STATUS_COMPLETED and result.actions == 4
    assert isinstance(steps[-1].result.events[-1], GameCompleted)


def test_the_draw_cap_takes_precedence_over_the_action_cap():
    reference, steps, _ = stalled(draws=0)
    first_attempt = attempt_lengths(steps)[0][2]  # the draw happens on this attempt's last action
    both, _, _ = stalled(draws=0, actions=first_attempt)
    assert both.status == STATUS_DRAW_CAP_REACHED and both.actions == first_attempt
    only_actions, _, _ = stalled(draws=0, actions=first_attempt - 1)
    assert only_actions.status == STATUS_ACTION_CAP_REACHED and only_actions.actions == first_attempt - 1
    assert reference.status == STATUS_DRAW_CAP_REACHED


# --- stopped-game invariants ----------------------------------------------------------------------------


def _stopped_cases():
    unresolvable = Trigger(lambda o: o.phase == "win_declared", limit=3)
    return {
        STATUS_DRAW_CAP_REACHED: lambda: play(sim_config(4, ["s"] * 4, draws=0), 0, {"s": claim_two_rounds_then_stall}),
        STATUS_ACTION_CAP_REACHED: lambda: play(sim_config(4, ["c"] * 4, actions=3), 0, {"c": claim_policy}, crafted_start({0})),
        STATUS_AGENT_FAULT_UNRESOLVABLE: lambda: play(
            sim_config(4, ["m"] * 4), 0, {"m": misbehaving_policy("none", unresolvable)}, crafted_start({0})
        ),
    }


@pytest.mark.parametrize("status", STOPPED_STATUSES)
def test_a_stopped_game_has_no_ranks_ties_or_winners_and_keeps_its_raw_scores(status):
    result, steps, _ = _stopped_cases()[status]()
    assert result.status == status and not result.completed and result.tie_for_first is None
    assert result.completed_rounds < result.num_rounds and result.stopped_attempt >= 1
    assert all(s.rank is None and s.tied is None for s in result.seats) and result.winning_seats == ()
    last = [s for s in steps if isinstance(s.result, Accepted)][-1].result.state
    assert tuple(s.score for s in result.seats) == last.scores
    for seat in result.seats:
        assert seat.score == sum(r.score_changes[seat.seat] for r in result.rounds)
    assert result.draw_restarts == sum(r.attempts - 1 for r in result.rounds) + result.stopped_attempt - 1
    assert result.actions == len(steps) and never_rejected(steps)


def test_the_caps_are_required_and_the_source_has_no_numeric_default():
    from chitai.simulation import SimulationConfigError, SimulationConfig

    import ast
    from pathlib import Path

    import chitai.simulation.runner as runner_module

    data = sim_config(4).to_dict()
    for key in ("max_draw_restarts_per_round", "max_actions_per_attempt"):
        missing = {k: v for k, v in data.items() if k != key}
        with pytest.raises(SimulationConfigError):
            SimulationConfig.from_dict(missing)
    tree = ast.parse(Path(runner_module.__file__).read_text(encoding="utf-8"))
    numbers = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool)}
    assert numbers <= {0, 1}, numbers  # no cap-like constant anywhere in the runner
    assert BIG_ACTIONS > 1  # (a fixture value, defined only in the tests)
