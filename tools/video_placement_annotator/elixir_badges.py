from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ElixirObservation:
    cost: int | None
    confidence: float
    margin: float


def extract_badge_patch(card_crop: np.ndarray) -> np.ndarray | None:
    """Extract a magenta elixir badge from a replay hand-card crop.

    The replay HUD can render the card itself in grayscale when elixir is low.
    The badge remains a much more stable cue. This extractor intentionally uses
    only OpenCV color/shape operations and does not require OCR.
    """
    if card_crop is None or card_crop.size == 0:
        return None
    h, w = card_crop.shape[:2]
    roi = card_crop[int(h * 0.50):]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    magenta = (
        (hsv[:, :, 0] >= 140)
        & (hsv[:, :, 0] <= 179)
        & (hsv[:, :, 1] > 100)
        & (hsv[:, :, 2] > 80)
    ).astype(np.uint8) * 255
    magenta = cv2.morphologyEx(
        magenta, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
    )
    count, labels, stats, centers = cv2.connectedComponentsWithStats(
        magenta, 8
    )
    candidates = []
    for i in range(1, count):
        x, y, ww, hh, area = map(int, stats[i])
        cx, cy = centers[i]
        if area < 30 or hh < 8:
            continue
        # Prefer a compact lower-half component near the horizontal card center.
        score = area - 1.5 * abs(cx - w / 2) + 2.0 * (y + hh)
        candidates.append((score, i))
    if not candidates:
        return None
    _, i = max(candidates)
    x, y, ww, hh, _ = map(int, stats[i])
    pad = 3
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(w, x + ww + pad)
    y2 = min(roi.shape[0], y + hh + pad)
    patch = roi[y1:y2, x1:x2]
    return patch if patch.size else None


class ElixirBadgeBank:
    """Self-calibrating replay elixir-cost recognizer.

    A confident artwork match can label one badge (for example, Skeletons=1).
    Once a few costs have been observed, the same replay UI badge can be found
    in other cards by multi-scale template matching. This handles cards whose
    artwork is ambiguous but whose elixir number is decisive.
    """

    def __init__(
        self,
        *,
        max_templates_per_cost: int = 4,
        min_confidence: float = 0.52,
        min_margin: float = 0.065,
    ):
        self.max_templates_per_cost = int(max_templates_per_cost)
        self.min_confidence = float(min_confidence)
        self.min_margin = float(min_margin)
        self._templates: dict[int, list[np.ndarray]] = defaultdict(list)

    @property
    def costs(self) -> tuple[int, ...]:
        return tuple(sorted(self._templates))

    def observe(self, cost: int, card_crop: np.ndarray) -> bool:
        patch = extract_badge_patch(card_crop)
        if patch is None:
            return False
        cost = int(cost)
        templates = self._templates[cost]
        if len(templates) >= self.max_templates_per_cost:
            return False
        # Avoid storing near-identical copies from adjacent frames.
        if templates:
            p = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            duplicate = False
            for old in templates:
                og = cv2.cvtColor(old, cv2.COLOR_BGR2GRAY)
                rg = cv2.resize(
                    p, (og.shape[1], og.shape[0]), interpolation=cv2.INTER_AREA
                )
                score = float(
                    cv2.matchTemplate(rg, og, cv2.TM_CCOEFF_NORMED)[0, 0]
                )
                if score >= 0.96:
                    duplicate = True
                    break
            if duplicate:
                return False
        templates.append(patch.copy())
        return True

    def classify(self, card_crop: np.ndarray) -> ElixirObservation:
        if not self._templates or card_crop is None or card_crop.size == 0:
            return ElixirObservation(None, 0.0, 0.0)
        lower = card_crop[int(card_crop.shape[0] * 0.50):]
        if lower.size == 0:
            return ElixirObservation(None, 0.0, 0.0)
        gray = cv2.cvtColor(lower, cv2.COLOR_BGR2GRAY)
        scores: dict[int, float] = {}
        for cost, templates in self._templates.items():
            best = -1.0
            for template in templates:
                tg = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                for scale in (0.88, 0.94, 1.00, 1.06, 1.12):
                    tw = max(8, round(tg.shape[1] * scale))
                    th = max(8, round(tg.shape[0] * scale))
                    if th > gray.shape[0] or tw > gray.shape[1]:
                        continue
                    resized = cv2.resize(
                        tg, (tw, th), interpolation=cv2.INTER_AREA
                    )
                    result = cv2.matchTemplate(
                        gray, resized, cv2.TM_CCOEFF_NORMED
                    )
                    best = max(best, float(result.max()))
            scores[cost] = best
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        if not ranked:
            return ElixirObservation(None, 0.0, 0.0)
        confidence = float(ranked[0][1])
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        margin = float(confidence - second)
        cost = int(ranked[0][0])
        if confidence < self.min_confidence or margin < self.min_margin:
            cost = None
        return ElixirObservation(cost, confidence, margin)
