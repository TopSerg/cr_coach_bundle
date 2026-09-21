from __future__ import annotations

import unittest

import cv2
import numpy as np

from core import HandObservation, StableHandTracker
from elixir_badges import ElixirBadgeBank
from hand_decoder import DeckEvidence, decode_joint_fixed_slots, decode_slot_viterbi, absorb_short_runs
from fingerprints import MatchCandidate


def fake_candidate(card: str, score: float) -> MatchCandidate:
    return MatchCandidate(card, score, score, score, score, None)


def fake_badge(cost: int) -> np.ndarray:
    img = np.zeros((120, 90, 3), dtype=np.uint8)
    cv2.circle(img, (45, 94), 18, (200, 0, 200), -1)
    cv2.putText(
        img, str(cost), (35, 104), cv2.FONT_HERSHEY_SIMPLEX,
        0.65, (255, 255, 255), 2, cv2.LINE_AA,
    )
    return img


class FixedSlotTests(unittest.TestCase):
    def test_tracker_reports_same_slot_replacement(self):
        t = StableHandTracker("team", stable_samples=2, threshold=.4)
        a = HandObservation(("a", "b", "c", "d"), .9, (.9, .9, .9, .9))
        b = HandObservation(("a", "b", "e", "d"), .9, (.9, .9, .9, .9))
        self.assertIsNone(t.push(0.0, a))
        self.assertIsNone(t.push(0.1, a))
        self.assertIsNone(t.push(0.2, b))
        ev = t.push(0.3, b)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.card, "c")
        self.assertEqual(ev.incoming, "e")
        self.assertEqual(ev.slot, 2)

    def test_tracker_rejects_multi_slot_glitch(self):
        t = StableHandTracker("team", stable_samples=2, threshold=.4)
        a = HandObservation(("a", "b", "c", "d"), .9, (.9, .9, .9, .9))
        glitch = HandObservation(("x", "y", "c", "d"), .9, (.9, .9, .9, .9))
        t.push(0.0, a); t.push(0.1, a)
        self.assertIsNone(t.push(0.2, glitch))
        self.assertIsNone(t.push(0.3, glitch))

    def test_elixir_badge_bank_distinguishes_costs(self):
        bank = ElixirBadgeBank(min_confidence=.2, min_margin=.02)
        self.assertTrue(bank.observe(3, fake_badge(3)))
        self.assertTrue(bank.observe(4, fake_badge(4)))
        obs = bank.classify(fake_badge(4))
        self.assertEqual(obs.cost, 4)
        self.assertGreater(obs.confidence, .8)
        self.assertGreater(obs.margin, .05)

    def test_deck_evidence_locks_eight_cards(self):
        ev = DeckEvidence(min_hits=2)
        cards = [f"c{i}" for i in range(8)]
        for _ in range(2):
            for card in cards:
                ev.observe([fake_candidate(card, .8), fake_candidate("noise", .5)])
        lock = ev.maybe_lock()
        self.assertIsNotNone(lock)
        self.assertEqual(set(lock.cards), set(cards))

    def test_joint_decoder_never_duplicates_a_deck_card(self):
        scores = np.full((4, 4, 8), 0.1, dtype=np.float32)
        # Tempt two slots to choose card 0 at the same time.
        scores[:, 0, 0] = .95
        scores[:, 1, 0] = .94
        scores[:, 1, 1] = .90
        scores[:, 2, 2] = .93
        scores[:, 3, 3] = .92
        path = decode_joint_fixed_slots(scores, transition_penalty=.5)
        for row in path:
            self.assertEqual(len(set(map(int, row))), 4)
        self.assertEqual(int(path[-1, 0]), 0)
        self.assertEqual(int(path[-1, 1]), 1)

    def test_slot_viterbi_suppresses_one_frame_glitch(self):
        scores = np.array([
            [.9,.1],
            [.9,.1],
            [.2,.8],  # one bad frame
            [.9,.1],
            [.9,.1],
            [.1,.9],
            [.1,.9],
            [.1,.9],
        ], dtype=np.float32)
        path = decode_slot_viterbi(scores, transition_penalty=1.2)
        path = absorb_short_runs(path, min_samples=2)
        self.assertEqual(list(path[:5]), [0,0,0,0,0])
        self.assertEqual(list(path[-3:]), [1,1,1])


if __name__ == "__main__":
    unittest.main()
