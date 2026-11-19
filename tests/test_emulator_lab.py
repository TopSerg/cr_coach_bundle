"""Offline regression tests; do not need Android, OpenCV or Rudy wheel."""
import hashlib
import json
import subprocess
from pathlib import Path
import tempfile
import unittest

from emulator_lab.session import (validate_config, screen_cell_to_px, create_session,
                                  start_match, export_replay, atomic_json)
from emulator_lab.reference import build_reference
from emulator_lab.compare import compare_visual, diagnose
from emulator_lab.tuning import estimate_speed


CONFIG = {
    "calibration_confirmed": True,
    "devices": {
        "team": {"serial": "emulator-5554", "arena_rect_px": [0, 0, 180, 320], "hand_slots_px": [[20, 450], [60, 450], [100, 450], [140, 450]], "tower_hp_rois": []},
        "opponent": {"serial": "emulator-5556", "arena_rect_px": [0, 0, 180, 320], "hand_slots_px": [[20, 450], [60, 450], [100, 450], [140, 450]], "tower_hp_rois": []},
    }
}


class SessionTests(unittest.TestCase):
    def test_calibration_rotation(self):
        validate_config(CONFIG)
        self.assertEqual(screen_cell_to_px(CONFIG, "team", 1, 2), (15, 25))
        self.assertEqual(screen_cell_to_px(CONFIG, "opponent", 1, 2), (165, 295))
        with self.assertRaises(ValueError):
            screen_cell_to_px(CONFIG, "team", 18, 2)

    def test_duplicate_devices_rejected(self):
        cloned = json.loads(json.dumps(CONFIG))
        cloned["devices"]["opponent"]["serial"] = cloned["devices"]["team"]["serial"]
        with self.assertRaises(ValueError):
            validate_config(cloned)

    def test_export_uses_world_cells_and_known_action_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "my_config.json"
            atomic_json(config, CONFIG)
            session = root / "run-001"
            create_session(config, session, check_devices=False)
            start_match(session, now_ns=1_000_000_000)
            atomic_json(session / "actions" / "a.json", {"side": "team", "card": "hog-rider", "placement_send_ns": 1_100_000_000,
                                                               "placement_ack_ns": 1_100_000_000, "world_cell": [3, 19], "adb_command_sent": True})
            atomic_json(session / "actions" / "b.json", {"side": "opponent", "card": "cannon", "placement_send_ns": 1_200_000_000,
                                                               "placement_ack_ns": 1_200_000_000, "world_cell": [10, 10], "adb_command_sent": True})
            atomic_json(session / "actions" / "bad.json", {"side": "team", "card": "hog-rider", "placement_send_ns": 1_300_000_000,
                                                                 "placement_ack_ns": 1_300_000_000, "world_cell": [3, 19], "adb_command_sent": False})
            replay = export_replay(session, duration_s=10)
            self.assertEqual([e["tick"] for e in replay["events"]], [2, 4])
            self.assertEqual([e["side"] for e in replay["events"]], ["team", "opponent"])
            self.assertEqual(replay["end_tick"], 200)


class ReferenceTests(unittest.TestCase):
    def sample(self, t, hp, side="team", confidence=0.98, role="left"):
        return {"timestamp_ns": t * 50_000_000, "time_uncertainty_ns": 1_000_000,
                "kind": "tower_hp", "hp": hp, "owner": 1, "role": role, "side": side,
                "confidence": confidence, "frame": f"{side}-{t}.png"}

    def test_repetition_gate(self):
        rows = [self.sample(10, 3000), self.sample(12, 3000), self.sample(14, 0, confidence=0.2)]
        ref = build_reference(rows, start_ns=0)
        self.assertEqual([o["hp"] for o in ref["observations"]], [3000, 3000])
        self.assertEqual(ref["rejected"]["low_confidence"], 1)
        self.assertEqual(ref["snapshots"][0]["entities"][0]["card_id"], "princess-tower")

    def test_conflicting_two_device_ocr_excluded(self):
        rows = [self.sample(10, 3000), self.sample(11, 3000), self.sample(10, 2500, side="opponent")]
        ref = build_reference(rows, 0)
        self.assertTrue(ref["rejected"]["conflicting_two_device_ocr"] >= 1)

    def test_empty_evidence_inconclusive(self):
        result = compare_visual({"observations": []}, [])
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "INCONCLUSIVE")

    def test_repeated_wrong_hp_first_divergence(self):
        obs = [{"tick": tick, "kind": "tower_hp", "owner": 1, "role": "left", "hp": hp,
                "confidence": 0.98, "evidence": [f"f{tick}"], "tick_uncertainty": 1}
               for tick, hp in [(10, 3000), (12, 2900), (14, 2900)]]
        sim = [{"tick": tick, "entities": [{"owner": 1, "role": "left", "card_id": "princess-tower", "hp": hp}]}
               for tick, hp in [(10, 3000), (12, 3000), (14, 3000)]]
        report = compare_visual({"observations": obs}, sim)
        self.assertEqual(report["status"], "FIRST_DIVERGENCE")
        self.assertEqual(report["first_divergence"]["tick"], 12)
        self.assertEqual(report["first_divergence"]["last_exact_tick"], 10)
        self.assertFalse(diagnose(report)["ready_to_patch"])


    def test_timing_interval_can_match_adjacent_rudy_tick(self):
        obs = [{"tick": 10, "kind": "tower_hp", "owner": 1, "role": "left", "hp": 2800,
                "confidence": 0.98, "tick_uncertainty": 2}]
        sim = [{"tick": t, "entities": [{"owner": 1, "role": "left", "card_id": "princess-tower", "hp": hp}]}
               for t, hp in [(10, 3000), (11, 2800)]]
        report = compare_visual({"observations": obs}, sim)
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "PASS_OBSERVED")

    def test_one_wrong_hp_not_pass(self):
        obs = [{"tick": 10, "kind": "tower_hp", "owner": 1, "role": "left", "hp": 100,
                "confidence": 0.99}]
        sim = [{"tick": 10, "entities": [{"owner": 1, "role": "left", "card_id": "princess-tower", "hp": 200}]}]
        self.assertEqual(compare_visual({"observations": obs}, sim)["status"], "INCONCLUSIVE")


class CalibrationTests(unittest.TestCase):
    SOURCE = '''old_speed = """s if s <= 90 => 75,  // old"""
new_speed = """
        s if s <= 90 => 90,   // Fast: 1.8 tiles/s = 90 units/tick
"""
'''

    def experiments(self, speed=94):
        return [{"experiment_id": f"run-{j}", "isolated_motion_verified": True, "source": "human_reviewed_trajectory",
                 "positions": [{"tick": i * 2, "x_mtile": i * speed * 2, "y_mtile": 1000} for i in range(4)]} for j in range(3)]

    def test_speed_fit_is_bounded_and_not_automatically_applied(self):
        proposal = estimate_speed(self.experiments(), "fast", self.SOURCE)
        self.assertTrue(proposal["ready"])
        self.assertEqual(proposal["proposed"], 94)
        self.assertIn("s if s <= 90 => 94", proposal["new"])
        self.assertIn("human review", proposal["requires"])


    def test_apply_uses_new_branch_and_preserves_base(self):
        from emulator_lab.tuning import apply_proposal, SPEED_SCRIPT
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            patch = repo / SPEED_SCRIPT
            patch.parent.mkdir(parents=True)
            patch.write_text(self.SOURCE, encoding="utf-8")
            def git(*args):
                return subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()
            git("init", "-b", "main")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Fixture")
            git("add", ".")
            git("commit", "-m", "initial")
            proposal = estimate_speed(self.experiments(), "fast", self.SOURCE)
            with self.assertRaises(ValueError):
                apply_proposal(repo, proposal, "calibration/test-speed", approved=False, run_tests=False)
            commit = apply_proposal(repo, proposal, "calibration/test-speed", approved=True, run_tests=False)
            self.assertEqual(git("rev-parse", "HEAD"), commit)
            self.assertIn("s if s <= 90 => 94", patch.read_text(encoding="utf-8"))
            git("switch", "main")
            self.assertEqual(patch.read_text(encoding="utf-8"), self.SOURCE)

    def test_speed_fit_requires_three_verified_experiments(self):
        with self.assertRaises(ValueError):
            estimate_speed(self.experiments()[:2], "fast", self.SOURCE)
        cases = self.experiments()
        cases[0]["isolated_motion_verified"] = False
        with self.assertRaises(ValueError):
            estimate_speed(cases, "fast", self.SOURCE)


if __name__ == "__main__":
    unittest.main()
