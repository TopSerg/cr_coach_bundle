"""Contract tests for the small JSON/CSV replay input boundary.

The loader is intentionally tested through its public functions.  These tests
do not import the simulator engine: malformed input must be rejected before a
long physics run starts, and a placement replay should remain useful without
an exact hand reconstruction.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / ".physical_deps" / "cr-bot"
if (BACKEND / "simulator").is_dir() and str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


DECK = [
    "hog-rider",
    "cannon",
    "musketeer",
    "skeletons",
    "ice-golem",
    "ice-spirit",
    "fireball",
    "log",
]


def _load_io():
    from cr_coach.replay.io import DEFAULT_RULESET, load_replay, seconds_to_tick

    return DEFAULT_RULESET, load_replay, seconds_to_tick


def _write_json(tmp_path: Path, payload: dict, name: str = "replay.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _field(value, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _event_cell(event):
    cell = _field(event, "cell")
    if cell is not None:
        return tuple(cell)
    x = _field(event, "x")
    y = _field(event, "y")
    if x is not None and y is not None:
        return int(x), int(y)
    x_mtile = _field(event, "x_mtile")
    y_mtile = _field(event, "y_mtile")
    if x_mtile is not None and y_mtile is not None:
        return int(x_mtile) // 1000, int(y_mtile) // 1000
    raise AssertionError(f"event has no recognizable cell: {event!r}")


def _events(spec):
    events = _field(spec, "events")
    assert events is not None
    return list(events)


def test_seconds_to_tick_uses_the_fixed_20_hz_timebase():
    _, _, seconds_to_tick = _load_io()
    assert seconds_to_tick(0) == 0
    assert seconds_to_tick(0.05) == 1
    assert seconds_to_tick(2.45) == 49
    assert seconds_to_tick(13.0) == 260


def test_seconds_to_tick_rejects_negative_and_between_tick_values():
    _, _, seconds_to_tick = _load_io()
    for value in (-0.05, 0.01, 1.234, float("nan"), float("inf")):
        with pytest.raises((TypeError, ValueError)):
            seconds_to_tick(value)


def test_minimal_json_gets_document_defaults(tmp_path: Path):
    default_ruleset, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "duration_s": 3,
                "events": [],
            },
        )
    )
    assert _field(spec, "mode") == "placements"
    assert _field(spec, "ruleset_id") == default_ruleset
    assert _field(spec, "level") == 11
    assert _field(spec, "seed") == 0
    assert _field(spec, "end_tick") == 60


def test_time_event_is_converted_to_an_integer_tick_and_keeps_side_card(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "duration_s": 1,
                "events": [
                    {
                        "time": 0.5,
                        "side": "team",
                        "card": "hog-rider",
                        "x": 9,
                        "y": 18,
                    }
                ],
            },
        )
    )
    event = _events(spec)[0]
    assert _field(event, "tick") == 10
    assert _field(event, "side") == "team"
    assert _field(event, "card") == "hog-rider"
    assert _event_cell(event) == (9, 18)


def test_explicit_tick_is_accepted_without_float_rounding(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "end_tick": 52,
                "events": [
                    {
                        "tick": 49,
                        "side": "opponent",
                        "card": "cannon",
                        "x": 9,
                        "y": 10,
                    }
                ],
            },
        )
    )
    assert _field(_events(spec)[0], "tick") == 49
    assert _field(spec, "end_tick") == 52


def test_time_and_tick_cannot_disagree(tmp_path: Path):
    _, load_replay, _ = _load_io()
    with pytest.raises(ValueError):
        load_replay(
            _write_json(
                tmp_path,
                {
                    "events": [
                        {
                            "time": 1.0,
                            "tick": 21,
                            "side": "team",
                            "card": "hog-rider",
                            "x": 9,
                            "y": 18,
                        }
                    ]
                },
            )
        )


def test_events_are_stably_sorted_by_time(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "events": [
                    {"time": 2, "side": "team", "card": "hog-rider", "x": 9, "y": 18},
                    {"time": 1, "side": "team", "card": "cannon", "x": 8, "y": 20},
                    {"time": 1, "side": "opponent", "card": "musketeer", "x": 14, "y": 10},
                ]
            },
        )
    )
    events = _events(spec)
    assert [_field(event, "tick") for event in events] == [20, 20, 40]
    assert [_field(event, "side") for event in events[:2]] == ["team", "opponent"]


def test_two_sides_may_act_on_the_same_tick(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "events": [
                    {"time": 1, "side": "team", "card": "hog-rider", "x": 9, "y": 18},
                    {"time": 1, "side": "opponent", "card": "cannon", "x": 9, "y": 10},
                ]
            },
        )
    )
    assert [_field(event, "tick") for event in _events(spec)] == [20, 20]


def test_two_plays_by_one_side_on_the_same_tick_are_rejected(tmp_path: Path):
    _, load_replay, _ = _load_io()
    with pytest.raises(ValueError):
        load_replay(
            _write_json(
                tmp_path,
                {
                    "events": [
                        {"time": 1, "side": "team", "card": "hog-rider", "x": 9, "y": 18},
                        {"time": 1, "side": "team", "card": "cannon", "x": 9, "y": 20},
                    ]
                },
            )
        )


def test_player_cells_mirror_both_axes_for_the_opponent(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "coordinate_system": "player_cells",
                "events": [
                    {"time": 0, "side": "team", "card": "hog-rider", "x": 9, "y": 18},
                    {"time": 0.05, "side": "opponent", "card": "cannon", "x": 9, "y": 10},
                ]
            },
        )
    )
    events = _events(spec)
    assert _event_cell(events[0]) == (9, 18)
    assert _event_cell(events[1]) == (8, 21)


def test_world_cells_keep_opponent_coordinates_in_one_world(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "coordinate_system": "world_cells",
                "events": [
                    {"time": 0, "side": "opponent", "card": "cannon", "x": 9, "y": 10}
                ]
            },
        )
    )
    assert _event_cell(_events(spec)[0]) == (9, 10)


def test_world_mtile_centers_are_converted_to_policy_cells(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "coordinate_system": "world_mtile",
                "events": [
                    {
                        "time": 0,
                        "side": "team",
                        "card": "hog-rider",
                        "x": 9_500,
                        "y": 18_500,
                    }
                ]
            },
        )
    )
    assert _event_cell(_events(spec)[0]) == (9, 18)


def test_csv_uses_the_same_event_contract(tmp_path: Path):
    _, load_replay, _ = _load_io()
    path = tmp_path / "placements.csv"
    path.write_text(
        "time,side,card,x,y\n"
        "0,team,hog-rider,9,18\n"
        "2.45,opponent,cannon,9,10\n",
        encoding="utf-8",
    )
    spec = load_replay(path)
    events = _events(spec)
    assert [_field(event, "tick") for event in events] == [0, 49]
    assert [_field(event, "card") for event in events] == ["hog-rider", "cannon"]


def test_csv_requires_the_documented_header(tmp_path: Path):
    _, load_replay, _ = _load_io()
    path = tmp_path / "bad.csv"
    path.write_text("when,owner,card,x,y\n0,team,hog-rider,9,18\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_replay(path)


def test_unknown_side_is_rejected(tmp_path: Path):
    _, load_replay, _ = _load_io()
    with pytest.raises(ValueError):
        load_replay(
            _write_json(
                tmp_path,
                {"events": [{"time": 0, "side": "blue", "card": "hog-rider", "x": 9, "y": 18}]},
            )
        )


def test_missing_card_is_rejected(tmp_path: Path):
    _, load_replay, _ = _load_io()
    with pytest.raises(ValueError):
        load_replay(_write_json(tmp_path, {"events": [{"time": 0, "side": "team", "x": 9, "y": 18}]}))


def test_out_of_bounds_cell_is_rejected(tmp_path: Path):
    _, load_replay, _ = _load_io()
    for x, y in [(-1, 1), (18, 1), (1, -1), (1, 32)]:
        with pytest.raises(ValueError):
            load_replay(
                _write_json(
                    tmp_path,
                    {"events": [{"time": 0, "side": "team", "card": "hog-rider", "x": x, "y": y}]},
                    name=f"bad-{x}-{y}.json",
                )
            )


def test_duration_must_cover_every_event(tmp_path: Path):
    _, load_replay, _ = _load_io()
    with pytest.raises(ValueError):
        load_replay(
            _write_json(
                tmp_path,
                {
                    "duration_s": 1,
                    "events": [{"time": 1.05, "side": "team", "card": "hog-rider", "x": 9, "y": 18}],
                },
            )
        )


def test_default_horizon_is_at_least_one_tick_after_the_last_play(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {"duration_s": 2.45, "events": [{"time": 2.45, "side": "team", "card": "hog-rider", "x": 9, "y": 18}]},
        )
    )
    assert _field(spec, "end_tick") >= 50


def test_match_mode_requires_both_eight_card_decks(tmp_path: Path):
    _, load_replay, _ = _load_io()
    with pytest.raises(ValueError):
        load_replay(_write_json(tmp_path, {"mode": "match", "events": []}))
    with pytest.raises(ValueError):
        load_replay(
            _write_json(
                tmp_path,
                {"mode": "match", "team_deck": DECK, "opponent_deck": DECK[:-1]},
                name="short-deck.json",
            )
        )


def test_match_mode_preserves_decks_and_seed(tmp_path: Path):
    _, load_replay, _ = _load_io()
    spec = load_replay(
        _write_json(
            tmp_path,
            {
                "mode": "match",
                "seed": 42,
                "team_deck": DECK,
                "opponent_deck": list(reversed(DECK)),
                "events": [],
            },
        )
    )
    assert _field(spec, "seed") == 42
    assert tuple(_field(spec, "team_deck")) == tuple(DECK)
    assert tuple(_field(spec, "opponent_deck")) == tuple(reversed(DECK))


def test_initial_queues_must_be_permutations_of_their_decks(tmp_path: Path):
    _, load_replay, _ = _load_io()
    invalid = list(DECK)
    invalid[-1] = "knight"
    with pytest.raises(ValueError):
        load_replay(
            _write_json(
                tmp_path,
                {
                    "mode": "match",
                    "team_deck": DECK,
                    "opponent_deck": DECK,
                    "team_initial_queue": invalid,
                    "opponent_initial_queue": DECK,
                },
            )
        )


def test_initial_state_path_is_resolved_relative_to_the_input(tmp_path: Path):
    _, load_replay, _ = _load_io()
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text("{}", encoding="utf-8")
    input_path = _write_json(
        tmp_path,
        {"initial_state": "checkpoint.json", "duration_s": 1, "events": []},
        name="continuation.json",
    )
    spec = load_replay(input_path)
    assert Path(_field(spec, "initial_state")) == checkpoint.resolve()
