"""Simulation configuration: validation, JSON loading, required caps (M8 Stage 2)."""

from __future__ import annotations

import dataclasses
import json
from types import MappingProxyType

import pytest
from chitai.engine import GameConfig
from chitai.simulation import (
    AgentSpec,
    OutputOptions,
    SimulationConfig,
    SimulationConfigError,
    canonical_json,
)

from .support import CAP_ACTIONS, CAP_DRAWS, config_dict


def load(**overrides) -> SimulationConfig:
    return SimulationConfig.from_dict(config_dict(**overrides))


def bad(**overrides):
    with pytest.raises(SimulationConfigError):
        load(**overrides)


# --- a valid configuration ---------------------------------------------------------------


def test_a_valid_configuration_loads_with_documented_defaults():
    config = load()
    assert (config.num_players, config.num_rounds, config.batch_seed, config.game_count) == (4, 4, 2026, 8)
    assert (config.max_draw_restarts_per_round, config.max_actions_per_attempt) == (CAP_DRAWS, CAP_ACTIONS)
    assert config.pass_timeout_seconds == 15.0 and config.games_per_seed == 1 and config.rotate_seats is True
    assert config.output == OutputOptions(directory=None, public_event_log=True, private_diagnostics=False)
    assert len(config.lineup) == 4 and all(isinstance(spec, AgentSpec) for spec in config.lineup)
    assert config.lineup[0].agent_type == "rulebot" and dict(config.lineup[0].agent_config) == {"avoid_draw": True}


@pytest.mark.parametrize("n", (4, 5, 6, 7, 8))
def test_every_supported_player_count_loads(n):
    config = load(num_players=n, num_rounds=2 * n, lineup=[{"agent_type": "rulebot"}] * n)
    assert config.num_players == n and config.lineup[0].agent_config == {}


def test_game_config_builds_the_engines_validated_config_for_a_game_seed():
    config = load(pass_timeout_seconds=5)
    assert config.game_config(77) == GameConfig(4, 4, 77, 5)


# --- the caps have no default and are validated ------------------------------------------


@pytest.mark.parametrize("cap", ("max_draw_restarts_per_round", "max_actions_per_attempt"))
def test_the_caps_are_required_and_have_no_default(cap):
    data = config_dict()
    del data[cap]
    with pytest.raises(SimulationConfigError, match=cap):
        SimulationConfig.from_dict(data)
    fields = {f.name: f for f in dataclasses.fields(SimulationConfig)}
    for name in ("max_draw_restarts_per_round", "max_actions_per_attempt"):
        assert fields[name].default is dataclasses.MISSING
        assert fields[name].default_factory is dataclasses.MISSING


@pytest.mark.parametrize("cap", ("max_draw_restarts_per_round", "max_actions_per_attempt"))
@pytest.mark.parametrize("value", (True, 2.0, "3", None, -1, [3]))
def test_cap_values_must_be_non_negative_integers(cap, value):
    bad(**{cap: value})


def test_a_draw_cap_of_zero_is_allowed_but_an_action_cap_of_zero_is_not():
    assert load(max_draw_restarts_per_round=0).max_draw_restarts_per_round == 0
    bad(max_actions_per_attempt=0)
    assert load(max_actions_per_attempt=1).max_actions_per_attempt == 1


# --- validation errors -------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"num_players": 3, "lineup": [{"agent_type": "rulebot"}] * 3, "num_rounds": 3},  # engine range
        {"num_players": 9, "lineup": [{"agent_type": "rulebot"}] * 9, "num_rounds": 9},
        {"num_players": 4.0},
        {"num_players": True},
        {"num_rounds": 6},  # not a multiple of 4
        {"num_rounds": 0},
        {"num_rounds": "4"},
        {"pass_timeout_seconds": 0},
        {"pass_timeout_seconds": 15.5},
        {"pass_timeout_seconds": True},
        {"pass_timeout_seconds": "5"},
        {"batch_seed": True},
        {"batch_seed": 1.5},
        {"batch_seed": "7"},
        {"game_count": 0},
        {"game_count": -4},
        {"game_count": 2.0},
        {"games_per_seed": 0},
        {"games_per_seed": 3},  # 8 games is not a multiple of 3
        {"rotate_seats": 1},
        {"rotate_seats": "yes"},
    ],
)
def test_invalid_values_are_rejected(overrides):
    bad(**overrides)


def test_the_engines_own_message_is_reused_for_game_rules():
    with pytest.raises(SimulationConfigError, match="multiple of num_players"):
        load(num_rounds=6)


def test_the_lineup_must_match_the_player_count():
    bad(lineup=[{"agent_type": "rulebot"}] * 3)
    bad(lineup=[{"agent_type": "rulebot"}] * 5)
    bad(lineup=[])
    bad(lineup="rulebot")
    bad(lineup=None)
    bad(lineup={"agent_type": "rulebot"})


@pytest.mark.parametrize(
    "entry",
    [
        {},
        {"agent_config": {}},
        {"agent_type": ""},
        {"agent_type": "rule bot"},
        {"agent_type": "1bot"},
        {"agent_type": 7},
        {"agent_type": "rulebot", "agent_config": []},
        {"agent_type": "rulebot", "agent_config": {"x": {1, 2}}},
        {"agent_type": "rulebot", "agent_config": {"x": float("nan")}},
        {"agent_type": "rulebot", "agent_config": {"x": float("inf")}},
        {"agent_type": "rulebot", "agent_config": {1: "non-string key"}},
        {"agent_type": "rulebot", "agent_config": {"x": object()}},
        {"agent_type": "rulebot", "colour": "red"},
        "rulebot",
        None,
    ],
)
def test_bad_lineup_entries_are_rejected(entry):
    bad(lineup=[entry] + [{"agent_type": "rulebot"}] * 3)


def test_unknown_and_missing_keys_are_rejected():
    bad(max_draws=5)
    bad(seed=1)  # a typo for batch_seed must not be silently ignored
    for key in ("lineup", "num_players", "num_rounds", "batch_seed", "game_count"):
        data = config_dict()
        del data[key]
        with pytest.raises(SimulationConfigError, match=key):
            SimulationConfig.from_dict(data)
    with pytest.raises(SimulationConfigError):
        SimulationConfig.from_dict([])
    with pytest.raises(SimulationConfigError):
        SimulationConfig.from_dict("{}")


def test_the_schema_version_is_checked():
    assert load(schema_version=1).batch_seed == 2026
    bad(schema_version=2)
    bad(schema_version="1")
    bad(schema_version=True)


# --- output options ----------------------------------------------------------------------


def test_output_options_default_to_public_log_on_and_diagnostics_off():
    options = OutputOptions()
    assert (options.directory, options.public_event_log, options.private_diagnostics) == (None, True, False)


def test_output_options_load_and_validate():
    config = load(output={"directory": "runs/a", "public_event_log": False, "private_diagnostics": True})
    assert config.output == OutputOptions("runs/a", False, True)
    assert load(output={}).output == OutputOptions()
    for output in (
        {"directory": ""},
        {"directory": 5},
        {"directory": "a\0b"},
        {"public_event_log": 1},
        {"private_diagnostics": "no"},
        {"unknown": True},
        [],
        "runs",
    ):
        bad(output=output)


def test_validating_a_configuration_never_touches_the_filesystem(tmp_path):
    target = tmp_path / "not-created"
    load(output={"directory": str(target)})
    assert not target.exists()


# --- JSON --------------------------------------------------------------------------------


def test_to_dict_and_from_dict_round_trip():
    config = load(
        pass_timeout_seconds=7.5,
        games_per_seed=2,
        rotate_seats=False,
        output={"directory": "out", "private_diagnostics": True},
        lineup=[
            {"agent_type": "rulebot", "agent_config": {"avoid_draw": False, "tags": ["a", {"b": None}]}},
            {"agent_type": "rulebot"},
            {"agent_type": "rulebot"},
            {"agent_type": "rulebot"},
        ],
    )
    data = config.to_dict()
    assert data["schema_version"] == 1
    assert SimulationConfig.from_dict(data) == config
    assert SimulationConfig.from_json(config.to_json()) == config
    assert json.loads(json.dumps(data)) == data  # JSON primitives only


def test_to_json_is_canonical_and_stable():
    config = load()
    text = config.to_json()
    assert text == canonical_json(config.to_dict()) == SimulationConfig.from_json(text).to_json()
    assert text.isascii() and "\n" not in text and ": " not in text
    assert text.index('"batch_seed"') < text.index('"game_count"') < text.index('"lineup"')  # sorted keys


def test_from_json_text():
    config = SimulationConfig.from_json(json.dumps(config_dict()))
    assert config == load()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "{",
        "[]",
        "null",
        '{"batch_seed": 1, "batch_seed": 2}',  # duplicate key
        json.dumps(config_dict()).replace('"avoid_draw": true', '"avoid_draw": NaN'),
        json.dumps(config_dict()).replace('"avoid_draw": true', '"avoid_draw": Infinity'),
    ],
)
def test_malformed_json_is_rejected_as_a_configuration_error(text):
    with pytest.raises(SimulationConfigError):
        SimulationConfig.from_json(text)


def test_duplicate_keys_nested_in_the_lineup_are_also_rejected():
    text = json.dumps(config_dict()).replace(
        '"agent_type": "rulebot", "agent_config"', '"agent_type": "rulebot", "agent_type": "x", "agent_config"', 1
    )
    with pytest.raises(SimulationConfigError, match="duplicate"):
        SimulationConfig.from_json(text)


# --- immutability ------------------------------------------------------------------------


def test_the_configuration_is_isolated_from_the_data_it_was_built_from():
    data = config_dict(lineup=[{"agent_type": "rulebot", "agent_config": {"opts": {"k": [1]}}}] * 4)
    config = SimulationConfig.from_dict(data)
    data["lineup"][0]["agent_config"]["opts"]["k"].append(2)
    data["batch_seed"] = 0
    assert config.to_dict()["lineup"][0]["agent_config"] == {"opts": {"k": [1]}}
    assert config.batch_seed == 2026


def test_the_configuration_cannot_be_mutated():
    config = load()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.batch_seed = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.lineup[0].agent_config["avoid_draw"] = False  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.output.directory = "x"  # type: ignore[misc]
    assert isinstance(config.lineup, tuple)


def test_a_python_list_lineup_is_normalised_to_a_tuple():
    config = SimulationConfig(
        lineup=[AgentSpec("rulebot")] * 4,  # type: ignore[arg-type]
        num_players=4, num_rounds=4, batch_seed=1, game_count=1,
        max_draw_restarts_per_round=0, max_actions_per_attempt=1,
    )  # fmt: skip
    assert isinstance(config.lineup, tuple)


# --- recursive immutability of agent_config ----------------------------------------------

NESTED = {
    "opts": {"deep": {"deeper": [1, {"x": [2, 3]}]}, "flag": True},
    "tags": ["a", ["b", {"c": None}]],
    "name": "n",
}


def nested_spec() -> AgentSpec:
    return AgentSpec("rulebot", NESTED)


def _walk_containers(value):
    """Yield every container reachable from `value`."""
    if isinstance(value, (dict, list, tuple, set, type(MappingProxyType({})))):
        yield value
        items = value.values() if isinstance(value, (dict, MappingProxyType)) else value
        for item in items:
            yield from _walk_containers(item)


def test_only_read_only_containers_are_reachable_from_agent_config():
    containers = list(_walk_containers(nested_spec().agent_config))
    assert len(containers) >= 8  # the walk really reached the nested levels
    for container in containers:
        assert isinstance(container, (MappingProxyType, tuple)), type(container)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.__setitem__("new", 1),
        lambda c: c.__delitem__("name"),
        lambda c: c["opts"].__setitem__("flag", False),
        lambda c: c["opts"].__delitem__("flag"),
        lambda c: c["opts"].update({"flag": False}),
        lambda c: c["opts"].pop("flag"),
        lambda c: c["opts"].popitem(),
        lambda c: c["opts"].clear(),
        lambda c: c["opts"].setdefault("z", 1),
        lambda c: c["opts"]["deep"].__setitem__("deeper", []),
        lambda c: c["opts"]["deep"]["deeper"].append(4),
        lambda c: c["opts"]["deep"]["deeper"].__setitem__(0, 9),
        lambda c: c["opts"]["deep"]["deeper"][1].__setitem__("x", []),
        lambda c: c["opts"]["deep"]["deeper"][1]["x"].append(4),
        lambda c: c["opts"]["deep"]["deeper"][1]["x"].extend([4]),
        lambda c: c["opts"]["deep"]["deeper"][1]["x"].clear(),
        lambda c: c["tags"].append("z"),
        lambda c: c["tags"].__setitem__(0, "z"),
        lambda c: c["tags"].pop(),
        lambda c: c["tags"].sort(),
        lambda c: c["tags"][1].append("z"),
        lambda c: c["tags"][1][1].__setitem__("c", 1),
        lambda c: c["tags"][1][1].pop("c"),
    ],
)
def test_nested_dictionaries_and_lists_cannot_be_mutated(mutate):
    spec = nested_spec()
    before = canonical_json(spec.agent_config)
    with pytest.raises((TypeError, AttributeError)):
        mutate(spec.agent_config)
    assert canonical_json(spec.agent_config) == before


def test_nested_arrays_are_tuples_and_nested_objects_are_read_only_mappings():
    config = nested_spec().agent_config
    assert isinstance(config["tags"], tuple) and isinstance(config["tags"][1], tuple)
    assert isinstance(config["opts"], MappingProxyType)
    assert isinstance(config["opts"]["deep"]["deeper"][1], MappingProxyType)
    assert isinstance(config["opts"]["deep"]["deeper"][1]["x"], tuple)


def test_serialisation_still_yields_ordinary_json_objects_and_arrays():
    spec = nested_spec()

    def plain(value):
        if isinstance(value, dict):
            return all(type(k) is str and plain(v) for k, v in value.items())
        if isinstance(value, list):
            return all(plain(v) for v in value)
        return value is None or type(value) in (bool, int, float, str)

    data = spec.to_dict()
    assert type(data) is dict and type(data["agent_config"]) is dict and plain(data["agent_config"])
    assert data["agent_config"] == NESTED  # lists are lists again, not tuples
    assert json.loads(json.dumps(data)) == data

    text = canonical_json(spec.agent_config)  # accepts the frozen value directly
    assert json.loads(text) == NESTED
    assert text == canonical_json(NESTED) == canonical_json(data["agent_config"])
    assert '"tags":["a",["b",{"c":null}]]' in text and text.startswith('{"name":"n","opts":{')

    config = SimulationConfig.from_dict(config_dict(lineup=[{"agent_type": "rulebot", "agent_config": NESTED}] * 4))
    whole = config.to_dict()
    assert whole["lineup"][0]["agent_config"] == NESTED and plain(whole["lineup"][0]["agent_config"])
    assert json.loads(config.to_json())["lineup"][3]["agent_config"] == NESTED
    assert SimulationConfig.from_json(config.to_json()) == config


def test_the_dictionary_from_to_dict_is_a_free_copy():
    spec = nested_spec()
    data = spec.to_dict()
    data["agent_config"]["opts"]["deep"]["deeper"].append("changed")
    data["agent_config"]["tags"].clear()
    assert spec.to_dict()["agent_config"] == NESTED
    assert spec.agent_config["tags"][0] == "a"


def test_agent_config_is_isolated_from_nested_input_in_both_directions():
    source = {"a": {"b": [1, {"c": [2]}]}}
    spec = AgentSpec("rulebot", source)
    source["a"]["b"].append(3)
    source["a"]["b"][1]["c"].append(4)
    source["a"]["new"] = 1
    assert spec.to_dict()["agent_config"] == {"a": {"b": [1, {"c": [2]}]}}
    # and a spec built from another spec's frozen config shares nothing with it
    twin = AgentSpec("rulebot", spec.agent_config)
    assert twin == spec and twin.agent_config is not spec.agent_config
    assert twin.agent_config["a"] is not spec.agent_config["a"]


def test_equality_and_round_trip_are_unchanged_by_freezing():
    assert nested_spec() == nested_spec()
    assert AgentSpec("rulebot", {"k": [1, 2]}) == AgentSpec("rulebot", {"k": (1, 2)})  # list or tuple input
    assert AgentSpec("rulebot", {"k": [1, 2]}) != AgentSpec("rulebot", {"k": [1, 3]})
    assert AgentSpec("rulebot", {"a": {"b": 1}}) != AgentSpec("rulebot", {"a": {"b": 2}})
    spec = nested_spec()
    assert AgentSpec.from_dict(spec.to_dict()) == spec
    assert AgentSpec.from_dict(json.loads(canonical_json(spec.to_dict()))) == spec
    assert AgentSpec("rulebot").agent_config == {} and AgentSpec("rulebot", {}).to_dict()["agent_config"] == {}


def test_the_public_schema_is_unchanged_by_freezing():
    config = load(lineup=[{"agent_type": "rulebot", "agent_config": NESTED}] * 4)
    data = config.to_dict()
    assert set(data) == {
        "schema_version", "lineup", "num_players", "num_rounds", "pass_timeout_seconds", "batch_seed",
        "game_count", "games_per_seed", "rotate_seats", "max_draw_restarts_per_round",
        "max_actions_per_attempt", "output",
    }  # fmt: skip
    assert set(data["lineup"][0]) == {"agent_type", "agent_config"}
    assert SimulationConfig.from_dict(data) == config


def test_validation_still_rejects_non_json_values_at_any_depth():
    for value in ({"a": [1, {"b": {1, 2}}]}, {"a": {"b": [float("nan")]}}, {"a": [object()]}, {"a": {1: "x"}}):
        with pytest.raises(SimulationConfigError):
            AgentSpec("rulebot", value)
