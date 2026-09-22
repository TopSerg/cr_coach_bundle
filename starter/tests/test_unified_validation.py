from cr_coach.validation.unified import compare_reference


def test_first_divergence_reports_first_tick_and_last_exact_tick():
    reference = {
        "snapshots": [
            {"tick": 10, "entities": [{"uid": 1, "hp": 100}]},
            {"tick": 11, "entities": [{"uid": 1, "hp": 90}]},
        ]
    }
    actual = [
        {"tick": 10, "entities": [{"uid": 1, "hp": 100}]},
        {"tick": 11, "entities": [{"uid": 1, "hp": 80}]},
    ]
    report = compare_reference(reference, actual, [])
    assert report["passed"] is False
    assert report["first_divergence"]["tick"] == 11
    assert report["first_divergence"]["last_exact_tick"] == 10
    assert report["first_divergence"]["subsystem"] == "combat"


def test_partial_reference_allows_extra_simulator_fields():
    reference = {"snapshots": [{"tick": 5, "entities": [{"uid": 7, "target_uid": 8}]}]}
    actual = [{
        "tick": 5,
        "phase": "regular",
        "entities": [{"uid": 7, "target_uid": 8, "hp": 500, "movement_state": "ground_idle"}],
    }]
    assert compare_reference(reference, actual, [])["passed"] is True


def test_event_reference_is_checked_by_tick_type_and_payload():
    reference = {"events": [{"tick": 3, "type": "TARGET_ACQUIRED", "uid": 7, "target_uid": 8}]}
    events = [{"tick": 3, "type": "TARGET_ACQUIRED", "uid": 7, "target_uid": 8, "card_id": "hog-rider"}]
    assert compare_reference(reference, [], events)["passed"] is True
