from __future__ import annotations

import unittest

import numpy as np

from placement_refiner import _clock_template
from timer_sync import GameTimerSync, TimerBoundary


class TimerSyncTests(unittest.TestCase):
    def test_timer_interpolates_between_real_second_boundaries(self):
        sync = GameTimerSync(
            [
                TimerBoundary(100, 2.0, 170.0, .2),
                TimerBoundary(153, 3.0, 169.0, .2),
                TimerBoundary(205, 4.0, 168.0, .2),
            ],
            ticks_per_second=20,
            battle_duration_seconds=180.0,
        )
        reading = sync.reading_at_frame(126.5)
        self.assertAlmostEqual(reading.remaining_seconds, 169.5, places=5)
        self.assertAlmostEqual(reading.battle_elapsed_seconds, 10.5, places=5)
        self.assertEqual(reading.tick, 210)
        self.assertEqual(reading.game_clock, "2:49.50")

    def test_timer_extrapolates_from_local_real_period(self):
        sync = GameTimerSync(
            [
                TimerBoundary(100, 2.0, 2.0, .2),
                TimerBoundary(154, 3.0, 1.0, .2),
            ],
            ticks_per_second=20,
            battle_duration_seconds=180.0,
        )
        self.assertAlmostEqual(sync.remaining_at_frame(208), 0.0, places=5)

    def test_compact_clock_templates_decode_without_binary_assets(self):
        team = _clock_template("team")
        opponent = _clock_template("opponent")
        self.assertEqual(team.shape, (52, 52, 3))
        self.assertEqual(opponent.shape, (52, 52, 3))
        self.assertGreater(float(np.std(team)), 10.0)
        self.assertGreater(float(np.std(opponent)), 10.0)


if __name__ == "__main__":
    unittest.main()
