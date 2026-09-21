from __future__ import annotations

import unittest

import cv2
import numpy as np

from cycle_tracker import (
    OrbReplayTemplateBank,
    infer_cycle_path,
    infer_initial_hand,
    play_cycle_state,
)


class CycleTrackerTests(unittest.TestCase):
    def test_play_cycle_replaces_same_slot_and_appends_played_card(self):
        state = (0, 1, 2, 3, 4, 5, 6, 7)
        self.assertEqual(
            play_cycle_state(state, 2),
            (0, 1, 4, 3, 5, 6, 7, 2),
        )

    def test_initial_hand_uses_unique_assignment(self):
        scores = np.full((4, 4, 8), .1, dtype=np.float32)
        wanted = (1, 3, 5, 7)
        for slot, card in enumerate(wanted):
            scores[:, slot, card] = .95
        self.assertEqual(infer_initial_hand(scores), wanted)

    def test_full_cycle_recovers_hidden_queue_and_play_slots(self):
        true = (0, 1, 2, 3, 4, 5, 6, 7)
        states = []
        actions = {3: 2, 6: 0, 9: 3}
        current = true
        for t in range(12):
            if t in actions:
                current = play_cycle_state(current, actions[t])
            states.append(current)

        scores = np.full((12, 4, 8), .05, dtype=np.float32)
        for t, state in enumerate(states):
            for slot in range(4):
                scores[t, slot, state[slot]] = .95

        # One misleading frame must not invent an impossible queue order.
        scores[5, 1, :] = .05
        scores[5, 1, 7] = .98

        path, decoded_actions = infer_cycle_path(
            scores,
            true[:4],
            transition_penalty=.45,
        )
        self.assertEqual(tuple(map(int, path[0, 4:])), true[4:])
        self.assertEqual(decoded_actions[3], 2)
        self.assertEqual(decoded_actions[6], 0)
        self.assertEqual(decoded_actions[9], 3)
        for t, state in enumerate(states):
            self.assertEqual(
                tuple(map(int, path[t, :4])),
                tuple(map(int, state[:4])),
            )

    def test_orb_replay_template_survives_selection_transform(self):
        rng = np.random.default_rng(42)
        image = rng.integers(0, 256, (120, 90, 3), dtype=np.uint8)
        cv2.circle(image, (45, 58), 24, (255, 255, 255), 3)
        cv2.putText(
            image, "CR", (18, 73), cv2.FONT_HERSHEY_SIMPLEX,
            .8, (0, 0, 0), 2, cv2.LINE_AA,
        )
        transform = cv2.getRotationMatrix2D((45, 60), 2.0, 1.04)
        selected = cv2.warpAffine(
            image, transform, (90, 120),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
        other = rng.integers(0, 256, (120, 90, 3), dtype=np.uint8)

        bank = OrbReplayTemplateBank()
        self.assertTrue(bank.add("card-a", bank.describe(image)))
        same, _ = bank.similarity("card-a", bank.describe(selected))
        different, _ = bank.similarity("card-a", bank.describe(other))
        self.assertGreater(same, .15)
        self.assertGreater(same, different * 2.0)


if __name__ == "__main__":
    unittest.main()
