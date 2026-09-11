"""Dependency-free tests for the Rudy replay adapter's canonical boundary."""

from __future__ import annotations

from cr_coach.replay.schema import ReplayBattle, ReplayEvent
from cr_coach.runtime.rudy_runner import _changes, _decks, _rudy_xy


AVAILABLE = {
    "hog-rider",
    "cannon",
    "knight",
    "archers",
    "fireball",
    "giant",
    "valkyrie",
    "musketeer",
    "zap",
}


def test_rudy_coordinate_conversion_uses_center_origin_and_upward_y():
    event = ReplayEvent(0, "team", "card_play", "hog-rider", 14_500, 17_500)
    assert _rudy_xy(event) == (5_500, -1_500)


def test_placements_infer_and_pad_one_eight_card_deck_per_side():
    battle = ReplayBattle(
        "probe",
        events=[
            ReplayEvent(0, "team", "card_play", "hog-rider", 14_500, 17_500),
            ReplayEvent(1, "opponent", "card_play", "cannon", 10_500, 10_500),
        ],
    )
    team, opponent = _decks(battle, AVAILABLE)
    assert len(team) == len(opponent) == 8
    assert len(set(team)) == len(set(opponent)) == 8
    assert "hog-rider" in team
    assert "cannon" in opponent


def test_lethal_direct_release_is_preserved_as_damage_then_death():
    hog = {"uid": 7, "owner": 0, "card_id": "hog-rider", "kind": "troop", "hp": 1000, "target_uid": 8, "attack_phase": "windup"}
    cannon = {"uid": 8, "owner": 1, "card_id": "cannon", "kind": "building", "hp": 100, "target_uid": 7}
    previous = {"tick": 20, "entities": [hog, cannon]}
    current = {"tick": 21, "entities": [{**hog, "attack_phase": "backswing"}]}
    events = _changes(previous, current)
    assert [event["kind"] for event in events[:2]] == ["damage_applied", "entity_died"]
    assert events[0]["data"]["source_card_id"] == "hog-rider"
    assert events[0]["data"]["target_card_id"] == "cannon"
