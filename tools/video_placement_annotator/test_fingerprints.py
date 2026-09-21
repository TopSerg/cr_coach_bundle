from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

import cv2
import numpy as np

from fingerprints import (
    CardFingerprintMatcher,
    CardFingerprintRecord,
    FingerprintDatabase,
    build_database,
    fingerprint_image,
    hamming64,
)


def card_image(kind: int, *, brightness: float = 1.0) -> np.ndarray:
    img = np.zeros((160, 120, 3), dtype=np.uint8)
    img[:] = (35, 45, 55)
    if kind == 0:
        cv2.circle(img, (60, 70), 33, (40, 180, 240), -1)
        cv2.line(img, (30, 115), (90, 25), (250, 250, 250), 8)
    elif kind == 1:
        cv2.rectangle(img, (26, 31), (94, 112), (190, 70, 70), -1)
        cv2.circle(img, (60, 70), 19, (245, 220, 40), -1)
    else:
        pts = np.array([[60, 20], [102, 116], [19, 101]], np.int32)
        cv2.fillConvexPoly(img, pts, (70, 220, 100))
        cv2.circle(img, (60, 68), 12, (30, 30, 30), -1)
    img = np.clip(img.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    return img


class FingerprintTests(unittest.TestCase):
    def test_phash_survives_brightness_and_resize(self):
        src = card_image(0)
        dim = card_image(0, brightness=0.45)
        dim = cv2.resize(dim, (74, 99), interpolation=cv2.INTER_AREA)
        dim = cv2.resize(dim, (120, 160), interpolation=cv2.INTER_CUBIC)
        a = fingerprint_image(src)
        b = fingerprint_image(dim)
        self.assertLessEqual(hamming64(a.phash, b.phash), 8)
        self.assertLessEqual(hamming64(a.edge_phash, b.edge_phash), 14)

    def test_database_matches_transformed_card(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i, name in enumerate(("golem", "night-witch", "fireball")):
                cv2.imwrite(str(root / f"{name}.png"), card_image(i))
            stats = {
                "cards": {
                    "golem": {"elixir": 8},
                    "night_witch": {"elixir": 4},
                    "fireball": {"elixir": 4},
                }
            }
            stats_path = root / "stats.json"
            stats_path.write_text(json.dumps(stats), encoding="utf-8")
            db = build_database(root, stats_json=stats_path)
            matcher = CardFingerprintMatcher(db)
            query = card_image(1, brightness=0.55)
            query = cv2.GaussianBlur(query, (3, 3), 0)
            card, confidence, margin = matcher.match(query)
            self.assertEqual(card, "night-witch")
            self.assertGreater(confidence, 0.70)
            self.assertGreater(margin, 0.05)

    def test_deck_filter_reduces_candidate_space(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i, name in enumerate(("a", "b", "c")):
                cv2.imwrite(str(root / f"{name}.png"), card_image(i))
            db = build_database(root)
            matcher = CardFingerprintMatcher(db, allowed=["a", "c"])
            card, _, _ = matcher.match(card_image(1))
            self.assertIn(card, {"a", "c"})
            self.assertNotEqual(card, "b")

    def test_elixir_is_strong_tiebreaker(self):
        fp = fingerprint_image(card_image(2))
        db = FingerprintDatabase(
            [
                CardFingerprintRecord("same-art-3", 3, fp),
                CardFingerprintRecord("same-art-6", 6, fp),
            ]
        )
        matcher = CardFingerprintMatcher(db)
        card, confidence, margin = matcher.match(card_image(2), observed_elixir=6)
        self.assertEqual(card, "same-art-6")
        self.assertGreater(confidence, 0.75)
        self.assertGreater(margin, 0.10)

    def test_collision_report_catches_identical_fingerprints(self):
        fp = fingerprint_image(card_image(0))
        db = FingerprintDatabase(
            [
                CardFingerprintRecord("one", 4, fp),
                CardFingerprintRecord("two", 4, fp),
            ]
        )
        a, b, similarity = db.nearest_pairs(limit=1)[0]
        self.assertEqual({a, b}, {"one", "two"})
        self.assertGreaterEqual(similarity, 0.999)


if __name__ == "__main__":
    unittest.main()
