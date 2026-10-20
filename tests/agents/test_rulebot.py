"""RuleBot: legality, decisions, duplicates, draw avoidance, determinism (M8 Stage 1)."""

from __future__ import annotations

import ast
import itertools
import json
import random
from dataclasses import replace
from pathlib import Path

import pytest
from engine.helpers import do_pass, start

import chitai.agents as agents_pkg
from chitai.agents import Agent, RuleBot, is_claimable
from chitai.engine import (
    Accepted,
    AttemptDrawn,
    Chit,
    ChitPassed,
    ClaimAction,
    DeclineAction,
    DecisionKind,
    Phase,
    ReactAction,
    apply_action,
    chit_names_for,
    is_valid_claim,
    pending_reactors,
)
from chitai.observations import NamePassAction, legal_actions_for, observe, to_engine_action

from .support import PLAYER_COUNTS, passing_state, phase_states, seeded_config, view, walk, winning_state

BOT = RuleBot()


def choose(state, seat, bot=BOT):
    obs, legal = view(state, seat)
    return bot.choose_action(obs, legal), legal


def acting_seats(state):
    return [s for s in range(state.config.num_players) if legal_actions_for(state, s)]


# --- legality in every decision phase ---------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_every_phase_and_acting_seat_gets_a_legal_action_the_engine_accepts(n):
    for name, state in phase_states(n).items():
        for seat in acting_seats(state):
            choice, legal = choose(state, seat)
            assert choice in legal, (name, seat)
            engine_action = to_engine_action(state, choice)
            assert engine_action is not None
            assert isinstance(apply_action(state, engine_action), Accepted), (name, seat)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_a_seat_with_nothing_to_decide_gets_no_action(n):
    for name, state in phase_states(n).items():
        for seat in range(n):
            if not legal_actions_for(state, seat):
                obs = observe(state, seat)
                with pytest.raises(ValueError):
                    BOT.choose_action(obs, ())


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_the_game_over_state_offers_and_yields_nothing(n):
    state = phase_states(n)["game_over"]
    assert state.phase is Phase.GAME_OVER and acting_seats(state) == []


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_rulebot_reacts_whenever_a_reaction_is_offered(n):
    state = winning_state(n)
    pending = pending_reactors(state)
    assert pending
    for seat in pending:
        choice, _ = choose(state, seat)
        assert choice == ReactAction(seat)
        assert isinstance(apply_action(state, to_engine_action(state, choice)), Accepted)


# --- initial claims ---------------------------------------------------------------------


def test_initial_claim_is_made_only_with_a_matching_hand():
    config = seeded_config(4)
    matching = start(config, matching={0})
    choice, _ = choose(matching, 0)
    assert choice == ClaimAction(0)
    assert is_valid_claim(matching.decision_kind, matching.hands[0])

    mixed = start(config, matching=set())
    choice, _ = choose(mixed, 0)
    assert choice == DeclineAction(0)


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_rulebot_never_claims_a_hand_the_engine_would_judge_false(n):
    for name in ("initial", "receive", "return"):
        state = phase_states(n)[name]
        seat = state.decision_seat
        choice, _ = choose(state, seat)
        assert not isinstance(choice, ClaimAction)
        assert not is_valid_claim(state.decision_kind, state.hands[seat])


# --- claim opportunities while passing --------------------------------------------------

RECEIVE_HANDS = {0: ["Sun", "Moon", "Star", "Cloud"], 1: ["Sun", "Sun", "Sun", "Moon"]}


def test_a_receiver_claims_four_of_five():
    state = passing_state(4, RECEIVE_HANDS)
    state, _ = do_pass(state, name="Sun")  # seat 1 now holds Sun x4 and Moon
    assert state.decision_kind is DecisionKind.NON_INITIATOR_RECEIVE and state.decision_seat == 1
    choice, _ = choose(state, 1)
    assert choice == ClaimAction(1)
    assert is_valid_claim(state.decision_kind, state.hands[1])


def test_a_receiver_one_short_of_four_passes_instead_of_claiming():
    state = passing_state(4, RECEIVE_HANDS)
    state, _ = do_pass(state, name="Moon")  # seat 1 holds Sun x3 and Moon x2
    choice, _ = choose(state, 1)
    assert choice == NamePassAction(1, "Moon")  # keeps the Sun target


def test_the_initiator_claims_when_four_of_a_name_return():
    hands = {
        0: ["Sun", "Sun", "Sun", "Moon"],
        1: ["Moon", "Moon", "Star", "Star"],
        2: ["Moon", "Star", "Star", "Cloud"],
        3: ["Sun", "Cloud", "Cloud", "Cloud"],
    }
    state = passing_state(4, hands)
    for name in ("Moon", "Moon", "Moon", "Sun"):
        state, _ = do_pass(state, name=name)
    assert state.decision_kind is DecisionKind.INITIATOR_RETURN and state.decision_seat == 0
    choice, _ = choose(state, 0)
    assert choice == ClaimAction(0)
    assert is_valid_claim(state.decision_kind, state.hands[0])


def test_the_initiator_passes_when_a_returned_chit_does_not_complete_four():
    hands = {
        0: ["Sun", "Sun", "Sun", "Moon"],
        1: ["Moon", "Moon", "Star", "Star"],
        2: ["Moon", "Star", "Star", "Cloud"],
        3: ["Sun", "Cloud", "Cloud", "Cloud"],
    }
    state = passing_state(4, hands)
    for name in ("Moon", "Moon", "Moon", "Cloud"):
        state, _ = do_pass(state, name=name)
    choice, _ = choose(state, 0)
    assert choice == NamePassAction(0, "Cloud")  # holds Sun x3 and the returned Cloud


# --- passing: commit to target, duplicates ----------------------------------------------


def test_the_only_non_target_name_is_passed():
    state = passing_state(4, {0: ["Sun", "Sun", "Sun", "Moon"]})
    choice, _ = choose(state, 0)
    assert choice == NamePassAction(0, "Moon")


def test_equal_counts_are_broken_by_canonical_name_order():
    # Moon precedes Star in the canonical order, so Moon is the target and Star is passed.
    state = passing_state(4, {0: ["Star", "Star", "Moon", "Moon"]})
    for order in ("most_copies", "fewest_copies"):
        choice, _ = choose(state, 0, RuleBot(non_target_order=order))
        assert choice == NamePassAction(0, "Star")


def test_the_two_provisional_non_target_orders_differ_as_documented():
    hands = {0: ["Star", "Cloud", "Cloud", "Cloud"], 1: ["Sun", "Sun", "Moon", "Moon"]}
    state, _ = do_pass(passing_state(4, hands), name="Star")  # seat 1: Sun x2, Moon x2, Star
    most, _ = choose(state, 1, RuleBot(non_target_order="most_copies"))
    fewest, _ = choose(state, 1, RuleBot(non_target_order="fewest_copies"))
    assert most == NamePassAction(1, "Moon")  # breaks the second pair first
    assert fewest == NamePassAction(1, "Star")  # sheds the singleton first


def test_a_hand_of_one_name_that_cannot_claim_still_passes_that_name():
    state = passing_state(4, {0: ["Sun", "Sun", "Sun", "Sun"]})  # first pass: no claim exists
    choice, legal = choose(state, 0)
    assert legal == (NamePassAction(0, "Sun"),)
    assert choice == NamePassAction(0, "Sun")


def test_duplicate_names_are_handled_by_name_and_no_copy_id_is_involved():
    state = passing_state(4, {0: ["Sun", "Sun", "Moon", "Moon"]})
    choice, legal = choose(state, 0)
    assert len(legal) == 2 and sorted(a.chit_name for a in legal) == ["Moon", "Sun"]
    assert choice in legal and not hasattr(choice, "chit")
    engine_action = to_engine_action(state, choice)
    assert engine_action.chit.name == choice.chit_name
    assert engine_action.chit == min(
        (c for c in state.hands[0] if c.name == choice.chit_name), key=lambda c: c.copy
    )


# --- draw avoidance ---------------------------------------------------------------------


def with_streak(state, seat, name, count):
    return replace(state, pass_streaks=((seat, name, count),))


def test_rulebot_does_not_make_the_tenth_same_name_pass_when_it_can_avoid_it():
    state = with_streak(passing_state(4, {0: ["Sun", "Sun", "Moon", "Star"]}), 0, "Moon", 9)
    choice, _ = choose(state, 0)
    assert choice == NamePassAction(0, "Star")
    result = apply_action(state, to_engine_action(state, choice))
    assert [type(e) for e in result.events] == [ChitPassed]

    careless, _ = choose(state, 0, RuleBot(avoid_draw=False))
    assert careless == NamePassAction(0, "Moon")
    drawn = apply_action(state, to_engine_action(state, careless))
    assert isinstance(drawn.events[0], AttemptDrawn)


def test_draw_avoidance_falls_back_to_the_target_when_it_is_the_only_alternative():
    state = with_streak(passing_state(4, {0: ["Sun", "Sun", "Sun", "Moon"]}), 0, "Moon", 9)
    choice, _ = choose(state, 0)
    assert choice == NamePassAction(0, "Sun")
    assert isinstance(apply_action(state, to_engine_action(state, choice)).events[0], ChitPassed)


@pytest.mark.parametrize(
    ("name", "count", "expected"),
    [("Moon", 8, "Moon"), ("Star", 9, "Moon"), ("Sun", 9, "Moon")],
)
def test_draw_avoidance_only_acts_on_a_ninth_pass_of_the_candidate_name(name, count, expected):
    state = with_streak(passing_state(4, {0: ["Sun", "Sun", "Sun", "Moon"]}), 0, name, count)
    choice, _ = choose(state, 0)
    assert choice == NamePassAction(0, expected)


def test_an_unavoidable_draw_is_not_hidden_by_rulebot():
    state = with_streak(passing_state(4, {0: ["Sun", "Sun", "Sun", "Sun"]}), 0, "Sun", 9)
    choice, legal = choose(state, 0)
    assert legal == (NamePassAction(0, "Sun"),) and choice == legal[0]
    assert isinstance(apply_action(state, to_engine_action(state, choice)).events[0], AttemptDrawn)


# --- the claim predicate matches the engine's rule --------------------------------------


@pytest.mark.parametrize("n", (4, 8))
def test_is_claimable_agrees_with_the_engine_for_every_hand_composition(n):
    names = chit_names_for(n)
    for size, kinds in (
        (4, (DecisionKind.INITIAL_CLAIM, DecisionKind.INITIATOR_RETURN)),
        (5, (DecisionKind.NON_INITIATOR_RECEIVE,)),
    ):
        for combo in itertools.combinations_with_replacement(names, size):
            if any(combo.count(name) > 4 for name in names):
                continue
            used: dict[str, int] = {}
            hand = []
            for name in combo:
                hand.append(Chit(name, used.get(name, 0)))
                used[name] = used.get(name, 0) + 1
            for kind in kinds:
                assert is_claimable(combo) == is_valid_claim(kind, tuple(hand)), (kind, combo)


def target_of(hand, chit_names):
    counts = {name: hand.count(name) for name in set(hand)}
    return min(counts, key=lambda name: (-counts[name], chit_names.index(name)))


@pytest.mark.parametrize("n", (4, 6, 8))
def test_rulebot_decisions_over_random_game_states_follow_the_rules(n):
    checked = 0
    for seed in range(8):
        rng = random.Random(seed)
        config = seeded_config(n)
        for state in walk(config, rng, max_steps=60):
            if state.phase not in (Phase.INITIAL_CLAIMS, Phase.PASSING):
                continue
            seat = state.decision_seat
            obs, legal = view(state, seat)
            choice = BOT.choose_action(obs, legal)
            assert choice in legal
            assert isinstance(apply_action(state, to_engine_action(state, choice)), Accepted)
            can_claim = ClaimAction(seat) in legal
            valid = can_claim and is_valid_claim(state.decision_kind, state.hands[seat])
            assert isinstance(choice, ClaimAction) == valid
            if isinstance(choice, NamePassAction):
                target = target_of(list(obs.my_hand), list(obs.chit_names))
                others = {a.chit_name for a in legal if isinstance(a, NamePassAction)} - {target}
                forced = obs.my_pass_streak_count >= 9 and others == {obs.my_pass_streak_name}
                assert choice.chit_name != target or not others or forced
            checked += 1
    assert checked > 50


# --- determinism ------------------------------------------------------------------------


@pytest.mark.parametrize("n", PLAYER_COUNTS)
def test_choices_repeat_and_do_not_depend_on_the_order_of_the_legal_tuple(n):
    for name, state in phase_states(n).items():
        for seat in acting_seats(state):
            obs, legal = view(state, seat)
            first = BOT.choose_action(obs, legal)
            assert all(BOT.choose_action(obs, legal) == first for _ in range(5))
            assert BOT.choose_action(obs, tuple(reversed(legal))) == first
            assert RuleBot().choose_action(obs, legal) == first  # no state carried between agents


def test_a_lone_unusable_claim_is_a_loud_error_not_a_guess():
    state = passing_state(4, {0: ["Sun", "Sun", "Moon", "Star"]})
    obs = observe(state, 0)
    with pytest.raises(ValueError):
        BOT.choose_action(obs, (ClaimAction(0),))


# --- interface and configuration --------------------------------------------------------


def test_rulebot_satisfies_the_agent_interface_and_describes_itself_in_json():
    assert isinstance(BOT, Agent)
    assert (BOT.agent_type, BOT.agent_version) == ("rulebot", "1")
    assert json.loads(json.dumps(BOT.agent_config)) == {"avoid_draw": True, "non_target_order": "most_copies"}
    assert RuleBot(avoid_draw=False, non_target_order="fewest_copies").agent_config == {
        "avoid_draw": False,
        "non_target_order": "fewest_copies",
    }


def test_invalid_configuration_is_rejected():
    with pytest.raises(TypeError):
        RuleBot(avoid_draw="yes")
    with pytest.raises(ValueError):
        RuleBot(non_target_order="random")


# --- privacy boundary (structural) ------------------------------------------------------

PACKAGE_DIR = Path(agents_pkg.__file__).parent
ALLOWED_ENGINE_NAMES = {"CONSECUTIVE_PASS_LIMIT", "ClaimAction", "DeclineAction", "ReactAction"}
ALLOWED_OBSERVATION_NAMES = {"AgentAction", "NamePassAction", "Observation"}
FORBIDDEN_ATTRIBUTES = {
    "debug_view", "seed", "hands", "config", "copy", "chit", "state", "pass_streaks", "timeout_chit",
}  # fmt: skip


def _trees():
    return {path.name: ast.parse(path.read_text(encoding="utf-8")) for path in PACKAGE_DIR.glob("*.py")}


def test_agents_import_only_the_sibling_modules_the_stdlib_and_allowlisted_names():
    for file_name, tree in _trees().items():
        for node in ast.walk(tree):
            assert not isinstance(node, ast.Import), (file_name, "plain imports are not used")
            if not isinstance(node, ast.ImportFrom):
                continue
            imported = {alias.name for alias in node.names}
            if node.level == 0:
                assert node.module in {"__future__", "collections", "typing"}, (file_name, node.module)
            elif node.level == 1:
                assert node.module in {"base", "belief", "mindbot", "rulebot"}, (file_name, node.module)
            else:
                assert node.level == 2, (file_name, node.level)
                allowed = {"engine": ALLOWED_ENGINE_NAMES, "observations": ALLOWED_OBSERVATION_NAMES}
                assert node.module in allowed, (file_name, node.module)
                assert imported <= allowed[node.module], (file_name, imported - allowed[node.module])


def test_agents_never_read_hidden_or_physical_fields_and_use_no_randomness():
    for file_name, tree in _trees().items():
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not attributes & FORBIDDEN_ATTRIBUTES, (file_name, attributes & FORBIDDEN_ATTRIBUTES)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not names & {"random", "time", "os", "hash", "open", "print"}, file_name


def test_the_engine_and_the_observation_layer_do_not_depend_on_agents():
    for sibling in ("engine", "observations"):
        for path in (PACKAGE_DIR.parent / sibling).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                elif isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                assert not any("agents" in module for module in modules), path.name
