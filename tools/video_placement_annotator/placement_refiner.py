from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
import math

import cv2
import numpy as np

from core import LayoutConfig, pixel_to_cell


LINE_SPELLS = {"the-log", "barbarian-barrel"}


@dataclass(frozen=True)
class PlacementObservation:
    frame_index: int
    video_time: float
    x: int
    y: int
    confidence: float
    locator: str
    pixel: tuple[float, float]
    hit_area: dict | None = None


def _clock_template(side: str) -> np.ndarray:
    name = (
        "deployment_clock_team.pgm"
        if side == "team"
        else "deployment_clock_opponent.pgm"
    )
    path = Path(__file__).resolve().with_name("assets") / name
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise RuntimeError(f"missing deployment clock asset: {path}")
    # Text PGM keeps the asset diffable/portable in Git while OpenCV still
    # reads it as a normal image. Resize back to the source replay marker size.
    gray = cv2.resize(gray, (52, 52), interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _clock_hits(
    frame: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = 0.55,
    max_hits: int = 8,
) -> list[tuple[float, float, float]]:
    h, w = frame.shape[:2]
    scale = w / 720.0
    tw = max(20, round(template.shape[1] * scale))
    th = max(20, round(template.shape[0] * scale))
    tpl = cv2.resize(
        template,
        (tw, th),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    y1 = max(0, round(h * 0.20))
    y2 = min(h, round(h * 0.89))
    gray = cv2.cvtColor(frame[y1:y2], cv2.COLOR_BGR2GRAY)
    tg = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(gray, tg, cv2.TM_CCOEFF_NORMED)
    work = result.copy()
    out = []
    for _ in range(max_hits):
        _, peak, _, loc = cv2.minMaxLoc(work)
        if peak < threshold:
            break
        cx = loc[0] + tw / 2
        cy = loc[1] + th / 2 + y1
        out.append((float(peak), float(cx), float(cy)))
        xx1 = max(0, loc[0] - tw // 2)
        yy1 = max(0, loc[1] - th // 2)
        xx2 = min(work.shape[1] - 1, loc[0] + tw // 2)
        yy2 = min(work.shape[0] - 1, loc[1] + th // 2)
        work[yy1 : yy2 + 1, xx1 : xx2 + 1] = -1
    return out


def _cluster_clock_hits(
    rows: Sequence[tuple[int, float, float, float, float]],
    *,
    tolerance_px: float = 18.0,
) -> list[dict]:
    clusters: list[dict] = []
    for frame_index, video_time, score, x, y in rows:
        cluster = next(
            (
                item
                for item in clusters
                if math.hypot(x - item["x"], y - item["y"]) <= tolerance_px
            ),
            None,
        )
        if cluster is None:
            cluster = {
                "x": x,
                "y": y,
                "rows": [],
            }
            clusters.append(cluster)
        cluster["rows"].append(
            (frame_index, video_time, score, x, y)
        )
        cluster["x"] = float(np.mean([r[3] for r in cluster["rows"]]))
        cluster["y"] = float(np.mean([r[4] for r in cluster["rows"]]))
    return clusters


def _locate_deployment_clock_template(
    video_path: str | Path,
    approx_time: float,
    cfg: LayoutConfig,
    side: str,
    *,
    lookback_s: float = 0.80,
    lookahead_s: float = 0.35,
) -> PlacementObservation | None:
    """Find the transient deployment clock and return its first visible frame.

    The hand-replacement detector is normally ~0.15 s late. Candidate clusters
    are therefore scored by both visual strength and an onset prior centered
    around approx_time - 0.15 s. There is intentionally no hard own-half rule:
    deployment territory can expand after a princess tower is destroyed.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    start = max(0, round((approx_time - lookback_s) * fps))
    end = min(
        max(0, frame_count - 1),
        round((approx_time + lookahead_s) * fps),
    )
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    template = _clock_template(side)
    rows = []
    shape = None
    for frame_index in range(start, end + 1):
        ok, frame = cap.read()
        if not ok:
            break
        shape = frame.shape[:2]
        for score, x, y in _clock_hits(frame, template):
            rows.append((frame_index, frame_index / fps, score, x, y))
    cap.release()
    if shape is None or not rows:
        return None

    h, w = shape
    candidates = []
    for cluster in _cluster_clock_hits(rows):
        crow = cluster["rows"]
        peak = max(r[2] for r in crow)
        first = crow[0]
        count = len(crow)
        x = cluster["x"]
        y = cluster["y"]
        if x < 70 and y > h * 0.75:
            # Static false match in this replay UI family.
            continue
        delta = first[1] - approx_time
        if not (-0.40 <= delta <= 0.12):
            continue
        proximity = math.exp(-((delta + 0.15) / 0.22) ** 2)
        score = (
            0.65 * peak
            + 0.20 * min(1.0, count / 8.0)
            + 0.15 * proximity
        )
        candidates.append((score, peak, first, count, x, y))
    if not candidates:
        return None

    _, peak, first, count, x, y = max(candidates, key=lambda item: item[0])
    cell_x, cell_y, _ = pixel_to_cell(x, y, w, h, cfg)
    return PlacementObservation(
        frame_index=int(first[0]),
        video_time=float(first[1]),
        x=cell_x,
        y=cell_y,
        confidence=float(peak),
        locator="deployment_clock",
        pixel=(float(x), float(y)),
        hit_area=None,
    )



def _shape_clock_hits(frame: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Find circular stopwatch-like markers independent of one UI skin."""
    h, w = frame.shape[:2]
    y0 = round(h * 0.20)
    y1 = round(h * 0.89)
    roi = frame[y0:y1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 1.2)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(16, round(w * 0.025)),
        param1=120,
        param2=22,
        minRadius=max(7, round(w * 0.010)),
        maxRadius=max(24, round(w * 0.050)),
    )
    if circles is None:
        return []

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    yy, xx = np.ogrid[:h, :w]
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    colored = (
        (
            (hue <= 12)
            | (hue >= 168)
            | ((hue >= 15) & (hue <= 45))
        )
        & (sat > 85)
        & (val > 80)
    )
    white = (sat < 65) & (val > 165)

    out = []
    for x, y, radius in circles[0]:
        x = float(x)
        y = float(y + y0)
        radius = float(radius)
        distance = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        annulus = (distance >= radius * 0.68) & (distance <= radius * 1.32)
        if not np.any(annulus):
            continue
        color_score = float(np.mean((colored | white)[annulus]))
        if color_score < 0.20:
            continue
        out.append((color_score, x, y, radius))
    out.sort(reverse=True)
    return out


def _locate_deployment_clock_shape(
    video_path: str | Path,
    approx_time: float,
    cfg: LayoutConfig,
    side: str,
    *,
    lookback_s: float = 0.80,
    lookahead_s: float = 0.35,
) -> PlacementObservation | None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    start = max(0, round((approx_time - lookback_s) * fps))
    end = min(max(0, frame_count - 1), round((approx_time + lookahead_s) * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)

    baseline: list[tuple[float, float, float]] = []
    rows: list[tuple[int, float, float, float, float, float]] = []
    shape = None
    stride = max(1, round(fps / 18.0))
    for frame_index in range(start, end + 1):
        ok, frame = cap.read()
        if not ok:
            break
        if (frame_index - start) % stride:
            continue
        shape = frame.shape[:2]
        now = frame_index / fps
        hits = _shape_clock_hits(frame)
        if now < approx_time - 0.42:
            baseline.extend((x, y, r) for score, x, y, r in hits if score >= 0.28)
        else:
            for score, x, y, radius in hits:
                if any(
                    math.hypot(x - bx, y - by) <= max(18.0, radius * 1.15)
                    for bx, by, _ in baseline
                ):
                    continue
                rows.append((frame_index, now, score, x, y, radius))
    cap.release()
    if shape is None or not rows:
        return None

    tolerance = max(16.0, shape[1] * 0.032)
    clusters: list[dict] = []
    for row in rows:
        frame_index, now, score, x, y, radius = row
        cluster = next(
            (
                item for item in clusters
                if math.hypot(x - item["x"], y - item["y"]) <= tolerance
            ),
            None,
        )
        if cluster is None:
            cluster = {"x": x, "y": y, "rows": []}
            clusters.append(cluster)
        cluster["rows"].append(row)
        cluster["x"] = float(np.mean([r[3] for r in cluster["rows"]]))
        cluster["y"] = float(np.mean([r[4] for r in cluster["rows"]]))

    h, w = shape
    candidates = []
    for cluster in clusters:
        crow = cluster["rows"]
        if len(crow) < 2:
            continue
        first = min(crow, key=lambda row: row[0])
        peak = max(row[2] for row in crow)
        delta = first[1] - approx_time
        if not (-0.45 <= delta <= 0.18):
            continue
        proximity = math.exp(-((delta + 0.12) / 0.25) ** 2)
        persistence = min(1.0, len(crow) / 5.0)
        score = 0.58 * peak + 0.27 * persistence + 0.15 * proximity
        candidates.append((score, peak, first, cluster["x"], cluster["y"]))
    if not candidates:
        return None

    score, peak, first, x, y = max(candidates, key=lambda item: item[0])
    cell_x, cell_y, _ = pixel_to_cell(x, y, w, h, cfg)
    return PlacementObservation(
        frame_index=int(first[0]),
        video_time=float(first[1]),
        x=cell_x,
        y=cell_y,
        confidence=float(min(1.0, score)),
        locator="deployment_clock_shape",
        pixel=(float(x), float(y)),
        hit_area=None,
    )


def locate_deployment_clock_precise(
    video_path: str | Path,
    approx_time: float,
    cfg: LayoutConfig,
    side: str,
    *,
    lookback_s: float = 0.80,
    lookahead_s: float = 0.35,
) -> PlacementObservation | None:
    template = _locate_deployment_clock_template(
        video_path,
        approx_time,
        cfg,
        side,
        lookback_s=lookback_s,
        lookahead_s=lookahead_s,
    )
    shape = _locate_deployment_clock_shape(
        video_path,
        approx_time,
        cfg,
        side,
        lookback_s=lookback_s,
        lookahead_s=lookahead_s,
    )
    if template is None:
        return shape
    if shape is None:
        return template
    # Exact-template match wins when strong; otherwise prefer the UI-agnostic
    # persistent circular marker.
    if template.confidence >= 0.72:
        return template
    return shape if shape.confidence > template.confidence else template

def _read_event_frames(
    video_path: str | Path,
    approx_time: float,
    *,
    lookback_s: float = 1.0,
    lookahead_s: float = 0.8,
) -> tuple[float, list[tuple[int, float, np.ndarray]]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise OSError(f"cannot open {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    start = max(0, round((approx_time - lookback_s) * fps))
    end = min(
        max(0, frame_count - 1),
        round((approx_time + lookahead_s) * fps),
    )
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    frames = []
    for frame_index in range(start, end + 1):
        ok, frame = cap.read()
        if not ok:
            break
        frames.append((frame_index, frame_index / fps, frame))
    cap.release()
    return fps, frames


def _new_color_components(
    frames: Sequence[tuple[int, float, np.ndarray]],
    approx_time: float,
    kind: str,
) -> list[tuple[int, float, list[tuple[float, float, float, int, int]]]]:
    pre = [
        frame
        for _, t, frame in frames
        if approx_time - 0.95 <= t <= approx_time - 0.72
    ]
    if not pre:
        return []
    baseline = np.median(np.stack(pre), axis=0).astype(np.uint8)
    baseline_hsv = cv2.cvtColor(baseline, cv2.COLOR_BGR2HSV)
    out = []
    for frame_index, t, frame in frames:
        if t < approx_time - 0.68:
            continue
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        if kind == "goblin-curse":
            current = (
                (hsv[:, :, 0] >= 35)
                & (hsv[:, :, 0] <= 95)
                & (hsv[:, :, 1] > 80)
                & (hsv[:, :, 2] > 70)
            )
            previous = (
                (baseline_hsv[:, :, 0] >= 35)
                & (baseline_hsv[:, :, 0] <= 95)
                & (baseline_hsv[:, :, 1] > 80)
                & (baseline_hsv[:, :, 2] > 70)
            )
        elif kind in LINE_SPELLS:
            current = (
                (hsv[:, :, 0] >= 5)
                & (hsv[:, :, 0] <= 30)
                & (hsv[:, :, 1] > 65)
                & (hsv[:, :, 2] > 35)
                & (hsv[:, :, 2] < 245)
            )
            previous = (
                (baseline_hsv[:, :, 0] >= 5)
                & (baseline_hsv[:, :, 0] <= 30)
                & (baseline_hsv[:, :, 1] > 65)
                & (baseline_hsv[:, :, 2] > 35)
                & (baseline_hsv[:, :, 2] < 245)
            )
        elif kind == "fireball":
            current = (
                (hsv[:, :, 0] <= 35)
                & (hsv[:, :, 1] > 80)
                & (hsv[:, :, 2] > 120)
            )
            previous = (
                (baseline_hsv[:, :, 0] <= 35)
                & (baseline_hsv[:, :, 1] > 80)
                & (baseline_hsv[:, :, 2] > 120)
            )
        else:
            continue
        mask = ((current & ~previous).astype(np.uint8) * 255)
        h = frame.shape[0]
        mask[: round(h * 0.24)] = 0
        mask[round(h * 0.87) :] = 0
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
        )
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)
        )
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        components = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < 80:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            moments = cv2.moments(contour)
            cx = (
                moments["m10"] / moments["m00"]
                if moments["m00"]
                else x + width / 2
            )
            cy = (
                moments["m01"] / moments["m00"]
                if moments["m00"]
                else y + height / 2
            )
            components.append(
                (area, float(cx), float(cy), int(width), int(height))
            )
        if components:
            components.sort(reverse=True)
            out.append((frame_index, t, components))
    return out



def _generic_effect_components(
    frames: Sequence[tuple[int, float, np.ndarray]],
    approx_time: float,
) -> list[tuple[int, float, list[tuple[float, float, float, int, int]]]]:
    """Fallback for spells whose visual effect is not color-specific."""
    pre = [
        frame
        for _, t, frame in frames
        if approx_time - 0.95 <= t <= approx_time - 0.72
    ]
    if not pre:
        return []
    baseline = np.median(np.stack(pre), axis=0).astype(np.uint8)
    base_gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
    h, w = base_gray.shape
    out = []
    for frame_index, t, frame in frames:
        if t < approx_time - 0.58:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray, base_gray)
        diff[: round(h * 0.24)] = 0
        diff[round(h * 0.87) :] = 0
        # Ignore tiny battle motion; spells create a dense local region.
        smooth = cv2.GaussianBlur(diff, (0, 0), sigmaX=5.0, sigmaY=5.0)
        mask = (smooth >= 22).astype(np.uint8) * 255
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
        )
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8)
        )
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        components = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < 120:
                continue
            x, y, width, height = cv2.boundingRect(contour)
            # Very tall/thin regions are usually a moving troop/projectile.
            aspect = max(width, height) / max(1.0, min(width, height))
            if aspect > 7.0:
                continue
            moments = cv2.moments(contour)
            cx = (
                moments["m10"] / moments["m00"]
                if moments["m00"]
                else x + width / 2
            )
            cy = (
                moments["m01"] / moments["m00"]
                if moments["m00"]
                else y + height / 2
            )
            components.append(
                (area, float(cx), float(cy), int(width), int(height))
            )
        if components:
            components.sort(reverse=True)
            out.append((frame_index, t, components))
    return out

def _red_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return (
        ((((hsv[:, :, 0] <= 8) | (hsv[:, :, 0] >= 170)))
        & (hsv[:, :, 1] > 100)
        & (hsv[:, :, 2] > 100)).astype(np.uint8) * 255
    )


def _first_clone_ring(
    frames: Sequence[tuple[int, float, np.ndarray]],
    approx_time: float,
) -> tuple[int, float, float, float, float, float] | None:
    """Find the first *new* large red target ring.

    Static red health bars/tower UI produce many Hough circles. Subtracting a
    pre-cast red mask first makes the detector respond only to the Clone target
    ring that appears in the arena.
    """
    pre = [
        frame
        for _, t, frame in frames
        if approx_time - 0.95 <= t <= approx_time - 0.75
    ]
    if not pre:
        return None
    baseline = np.median(np.stack(pre), axis=0).astype(np.uint8)
    baseline_red = _red_mask(baseline) > 0

    for frame_index, t, frame in frames:
        if t < approx_time - 0.70:
            continue
        current = _red_mask(frame) > 0
        red = ((current & ~baseline_red).astype(np.uint8) * 255)
        red[: round(frame.shape[0] * 0.24)] = 0
        red[round(frame.shape[0] * 0.87) :] = 0
        red = cv2.morphologyEx(
            red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)
        )
        blurred = cv2.GaussianBlur(red, (9, 9), 2)
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=45,
            param1=100,
            param2=15,
            minRadius=55,
            maxRadius=140,
        )
        if circles is None:
            continue

        yy, xx = np.nonzero(red)
        scored = []
        for x, y, radius in circles[0]:
            distance = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
            selected = np.abs(distance - radius) <= 10
            if int(selected.sum()) < 80:
                continue
            angles = np.arctan2(yy[selected] - y, xx[selected] - x)
            bins = np.histogram(
                angles, bins=36, range=(-math.pi, math.pi)
            )[0]
            coverage = float(np.mean(bins > 1))
            if coverage >= 0.60:
                scored.append(
                    (
                        coverage,
                        int(selected.sum()),
                        float(x),
                        float(y),
                        float(radius),
                    )
                )
        if scored:
            coverage, _, x, y, radius = max(scored)
            return frame_index, t, x, y, radius, coverage
    return None


def locate_spell_precise(
    video_path: str | Path,
    approx_time: float,
    cfg: LayoutConfig,
    card: str,
    card_stats: dict | None = None,
) -> PlacementObservation | None:
    _, frames = _read_event_frames(video_path, approx_time)
    if not frames:
        return None
    h, w = frames[0][2].shape[:2]

    if card == "clone":
        ring = _first_clone_ring(frames, approx_time)
        if ring is None:
            return None
        frame_index, t, x, y, radius, coverage = ring
        cell_x, cell_y, _ = pixel_to_cell(x, y, w, h, cfg)
        return PlacementObservation(
            frame_index=frame_index,
            video_time=t,
            x=cell_x,
            y=cell_y,
            confidence=coverage,
            locator="spell_target_ring",
            pixel=(x, y),
            hit_area={
                "shape": "circle",
                "center_px": [x, y],
                "radius_px": radius,
            },
        )

    components = _new_color_components(frames, approx_time, card)
    area_threshold = 1000.0
    if card == "goblin-curse":
        area_threshold = 3000.0
    elif card == "fireball":
        area_threshold = 1800.0

    locator = "spell_hit_area"
    selected = None
    for frame_index, t, items in components:
        candidate = next(
            (item for item in items if item[0] >= area_threshold),
            None,
        )
        if candidate is not None:
            selected = (frame_index, t, candidate)
            break

    if selected is None:
        locator = "spell_effect_change"
        generic = _generic_effect_components(frames, approx_time)
        for frame_index, t, items in generic:
            candidate = next(
                (item for item in items if item[0] >= 500.0),
                None,
            )
            if candidate is not None:
                selected = (frame_index, t, candidate)
                break
    if selected is None:
        return None

    frame_index, t, item = selected
    area, x, y, width, height = item
    cell_x, cell_y, _ = pixel_to_cell(x, y, w, h, cfg)
    if card in LINE_SPELLS:
        hit_area = {
            "shape": "line_rect",
            "initial_center_px": [x, y],
            "bbox_px": [
                x - width / 2,
                y - height / 2,
                x + width / 2,
                y + height / 2,
            ],
        }
        confidence = min(0.92, area / 5000.0)
    else:
        radius_tiles = None
        if card_stats is not None and card_stats.get("radius_tiles") is not None:
            radius_tiles = float(card_stats["radius_tiles"])
        if radius_tiles is not None:
            px_per_tile = (
                cfg.grid_step_norm[0] * w
                + cfg.grid_step_norm[1] * h
            ) / 2.0
            radius = radius_tiles * px_per_tile
        else:
            radius = (width + height) / 4.0
        hit_area = {
            "shape": "circle",
            "center_px": [x, y],
            "radius_px": radius,
        }
        if radius_tiles is not None:
            hit_area["radius_tiles"] = radius_tiles
        confidence = min(
            0.92 if locator == "spell_hit_area" else 0.68,
            area / 5000.0,
        )
    return PlacementObservation(
        frame_index=frame_index,
        video_time=t,
        x=cell_x,
        y=cell_y,
        confidence=float(confidence),
        locator=locator,
        pixel=(x, y),
        hit_area=hit_area,
    )


def refine_placement(
    video_path: str | Path,
    approx_time: float,
    cfg: LayoutConfig,
    side: str,
    card: str,
    *,
    card_kind: str | None = None,
    card_stats: dict | None = None,
) -> PlacementObservation | None:
    if card_kind == "spell":
        return locate_spell_precise(
            video_path, approx_time, cfg, card, card_stats
        )
    return locate_deployment_clock_precise(
        video_path, approx_time, cfg, side
    )
