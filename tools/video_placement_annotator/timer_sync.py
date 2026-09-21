from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np


# Binary 20x30 glyphs from the 2026 Clash Royale replay HUD. Each integer is
# one 20-bit row. The recognizer matches against a padded ROI, so 1-4 px HUD
# jitter and compression do not change the digit identity.
_DIGIT_ROWS: dict[int, tuple[int, ...]] = {
    0:(0,0,131068,1048574,1048575,1048575,1048575,1048575,1046655,1040447,1040447,1040447,1040447,1040447,1040447,1040447,1040447,1040447,1040447,1040447,1040511,1040511,1048575,1048575,1048575,1048575,1048575,1048575,262080,0),
    1:(0,8160,32736,65504,65504,65504,32736,8160,8160,8160,8160,8160,8160,8160,8160,8160,8160,8160,8160,8160,73696,106464,106464,8160,73696,8128,8128,8128,65536,98304),
    2:(4092,131070,262142,262143,262143,262143,262143,127,127,255,511,2047,4095,16383,32764,131064,262112,524224,524032,523776,523264,523264,524286,524287,524287,524287,524287,524287,65280,0),
    3:(130848,262136,524284,524284,524286,524286,327678,1022,1022,1022,1020,2040,32752,32752,32760,32766,32767,511,511,511,511,511,2047,131071,1048574,1048574,1048572,524280,524224,491520),
    4:(0,16382,32766,32766,65534,131070,131070,262143,261631,522751,520703,520703,516607,516607,516607,516607,524287,524287,524287,524287,524287,524287,524287,510,510,510,510,510,0,0),
    5:(0,65535,262143,524287,524287,524287,524287,523264,522240,522240,522240,522240,524032,524280,524287,524287,524287,65535,1023,511,511,511,2047,65535,524287,524286,262136,262112,261888,253952),
    6:(8188,131070,524286,1048574,1048574,1048568,1048448,1046528,1044480,1040384,1044480,1048448,1048572,1048575,1048575,1048575,1048575,1048575,1040511,1040511,1040511,1040511,1044735,1048575,1048575,1048575,1048574,262140,32736,0),
    7:(4032,524287,524287,524287,524287,524287,1023,1023,1022,2046,2044,4092,4088,8184,8176,16368,16352,16352,294848,294848,327552,65408,130816,130816,130560,261632,261120,261120,30720,0),
    8:(2046,131071,131071,262143,262143,262143,523327,522303,522303,522303,523327,262143,131071,65535,65535,65535,131071,262143,522271,522271,522271,522271,522271,523839,524287,524287,262143,262143,16382,0),
    9:(6148,32767,65535,131071,131071,262143,262143,261887,261151,261151,523295,523295,524287,524287,524287,524287,524287,262143,127,31,31,63,511,8191,65535,65535,65534,65520,294656,0),
}

# Pixel rectangles were measured on the canonical 720x1600 replay HUD and are
# scaled for other resolutions.
_DIGIT_RECTS = (
    (615, 263, 634, 292),  # minutes
    (649, 263, 668, 292),  # tens of seconds
    (670, 263, 689, 292),  # ones of seconds
)


@dataclass(frozen=True)
class TimerBoundary:
    frame_index: int
    video_time: float
    remaining_seconds: float
    battle_elapsed_seconds: float
    phase: str
    transition_strength: float
    ocr_confidence: float


@dataclass(frozen=True)
class TimerReading:
    frame_index: int
    remaining_seconds: float
    battle_elapsed_seconds: float
    tick: int
    game_clock: str
    phase: str


def _rows_to_template(rows: Sequence[int]) -> np.ndarray:
    out = np.zeros((30, 20), np.uint8)
    for y, bits in enumerate(rows):
        for x in range(20):
            if bits & (1 << (19 - x)):
                out[y, x] = 255
    return out


_DIGIT_TEMPLATES = {d: _rows_to_template(rows) for d, rows in _DIGIT_ROWS.items()}


def _scaled_rect(rect: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = rect
    return (
        round(x1 * w / 720),
        round(y1 * h / 1600),
        round(x2 * w / 720),
        round(y2 * h / 1600),
    )


def _digit_mask(frame: np.ndarray, rect: tuple[int, int, int, int], *, padx: int = 4, pady: int = 2) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = _scaled_rect(rect, w, h)
    roi = frame[
        max(0, y1 - pady):min(h, y2 + pady),
        max(0, x1 - padx):min(w, x2 + padx),
    ]
    if roi.size == 0:
        return np.zeros((34, 28), np.uint8)
    roi = cv2.resize(roi, (28, 34), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    white = (gray > 150) & (hsv[:, :, 1] < 110)
    red = (
        ((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 168))
        & (hsv[:, :, 1] > 80)
        & (hsv[:, :, 2] > 80)
    )
    return ((white | red).astype(np.uint8) * 255)


def _classify_digit(frame: np.ndarray, rect: tuple[int, int, int, int]) -> tuple[int, float, float]:
    candidate = _digit_mask(frame, rect)
    ranked = []
    for digit, template in _DIGIT_TEMPLATES.items():
        result = cv2.matchTemplate(candidate, template, cv2.TM_CCOEFF_NORMED)
        ranked.append((float(result.max()), digit))
    ranked.sort(reverse=True)
    best_score, best_digit = ranked[0]
    second_score = ranked[1][0]
    return best_digit, best_score, best_score - second_score


def read_timer_value(frame: np.ndarray) -> tuple[int | None, float, float]:
    digits = []
    confidences = []
    margins = []
    for rect in _DIGIT_RECTS:
        digit, confidence, margin = _classify_digit(frame, rect)
        digits.append(digit)
        confidences.append(confidence)
        margins.append(margin)
    seconds = digits[0] * 60 + digits[1] * 10 + digits[2]
    confidence = float(min(confidences))
    margin = float(min(margins))
    if seconds > 180:
        return None, confidence, margin
    return seconds, confidence, margin


def _timer_mask(frame: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    h, w = frame.shape[:2]
    x1 = max(0, min(w, round(roi[0] * w)))
    y1 = max(0, min(h, round(roi[1] * h)))
    x2 = max(0, min(w, round(roi[2] * w)))
    y2 = max(0, min(h, round(roi[3] * h)))
    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    white = gray >= 170
    red = (
        ((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 168))
        & (hsv[:, :, 1] >= 80)
        & (hsv[:, :, 2] >= 70)
    )
    return ((white | red).astype(np.uint8) * 255)


def _group_spikes(
    frame_indices: Sequence[int],
    strengths: Sequence[float],
    *,
    merge_gap_frames: int = 4,
) -> list[tuple[int, float]]:
    if not frame_indices:
        return []
    groups: list[list[int]] = [[0]]
    for i in range(1, len(frame_indices)):
        if frame_indices[i] - frame_indices[i - 1] <= merge_gap_frames:
            groups[-1].append(i)
        else:
            groups.append([i])
    out = []
    for group in groups:
        best_i = max(group, key=lambda i: strengths[i])
        out.append((int(frame_indices[best_i]), float(strengths[best_i])))
    return out


def _cluster_offsets(
    reads: Sequence[tuple[int, float, int, float, float]],
    *,
    tolerance_s: float = 2.0,
    min_size: int = 6,
) -> list[dict]:
    points = sorted(
        (
            (video_time + seconds, frame_index, video_time, seconds, confidence, margin)
            for frame_index, video_time, seconds, confidence, margin in reads
        ),
        key=lambda item: item[0],
    )
    clusters: list[list[tuple]] = []
    current: list[tuple] = []
    for item in points:
        if not current:
            current = [item]
            continue
        center = float(np.median([x[0] for x in current]))
        if abs(item[0] - center) <= tolerance_s:
            current.append(item)
        else:
            if len(current) >= min_size:
                clusters.append(current)
            current = [item]
    if len(current) >= min_size:
        clusters.append(current)

    result = []
    for cluster in clusters:
        result.append(
            {
                "center": float(np.median([x[0] for x in cluster])),
                "size": len(cluster),
                "min_time": min(x[2] for x in cluster),
                "max_time": max(x[2] for x in cluster),
                "points": cluster,
            }
        )
    result.sort(key=lambda item: item["size"], reverse=True)
    return result


def _nearest_spike(
    grouped: Sequence[tuple[int, float]],
    target_frame: float,
    fps: float,
    *,
    max_error_s: float = 0.38,
) -> tuple[int, float] | None:
    if not grouped:
        return None
    best = min(grouped, key=lambda item: abs(item[0] - target_frame))
    if abs(best[0] - target_frame) / fps > max_error_s:
        return None
    return best


class GameTimerSync:
    """Frame-accurate sync against the timer actually rendered by the game.

    OCR is used only to identify the displayed M:SS values and separate normal
    time from overtime. Exact hundredths come from the video frame where the HUD
    changes to the next integer second. Between two real timer boundaries the
    game clock is linearly interpolated, so MP4 clock drift does not accumulate.
    """

    DEFAULT_TIMER_ROI = (600 / 720, 255 / 1600, 710 / 720, 295 / 1600)

    def __init__(
        self,
        boundaries: Sequence[TimerBoundary],
        *,
        ticks_per_second: int = 20,
        regular_duration_seconds: float = 180.0,
        overtime_duration_seconds: float = 120.0,
        regular_offset: float | None = None,
        overtime_offset: float | None = None,
        fps: float | None = None,
    ):
        if len(boundaries) < 2:
            raise ValueError("timer synchronization requires at least two boundaries")
        ordered = sorted(boundaries, key=lambda item: item.frame_index)
        self.boundaries = tuple(ordered)
        self.ticks_per_second = int(ticks_per_second)
        self.regular_duration_seconds = float(regular_duration_seconds)
        self.overtime_duration_seconds = float(overtime_duration_seconds)
        self.regular_offset = regular_offset
        self.overtime_offset = overtime_offset
        self.fps = fps
        self._frames = np.asarray([b.frame_index for b in ordered], dtype=np.float64)
        self._elapsed = np.asarray([b.battle_elapsed_seconds for b in ordered], dtype=np.float64)

    @property
    def battle_start_video_time(self) -> float:
        if self.regular_offset is not None:
            return float(self.regular_offset - self.regular_duration_seconds)
        first = self.boundaries[0]
        return float(first.video_time - first.battle_elapsed_seconds)

    @classmethod
    def detect(
        cls,
        video_path: str | Path,
        *,
        timer_roi: tuple[float, float, float, float] | None = None,
        change_threshold: float = 0.020,
        ticks_per_second: int = 20,
        regular_duration_seconds: float = 180.0,
        overtime_duration_seconds: float = 120.0,
        coarse_fps: float = 2.0,
        ocr_confidence: float = 0.42,
        ocr_margin: float = 0.08,
    ) -> "GameTimerSync":
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise OSError(f"cannot open {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        roi = timer_roi or cls.DEFAULT_TIMER_ROI
        stride = max(1, round(fps / coarse_fps))

        previous = None
        spike_frames: list[int] = []
        spike_strengths: list[float] = []
        reads: list[tuple[int, float, int, float, float]] = []
        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            mask = _timer_mask(frame, roi)
            if previous is not None:
                strength = float(np.mean(cv2.absdiff(mask, previous)) / 255.0)
                if strength >= change_threshold:
                    spike_frames.append(frame_index)
                    spike_strengths.append(strength)
            previous = mask

            if frame_index % stride == 0:
                seconds, confidence, margin = read_timer_value(frame)
                if (
                    seconds is not None
                    and confidence >= ocr_confidence
                    and margin >= ocr_margin
                ):
                    reads.append(
                        (
                            frame_index,
                            frame_index / fps,
                            int(seconds),
                            confidence,
                            margin,
                        )
                    )
            frame_index += 1
        cap.release()

        clusters = _cluster_offsets(reads)
        if not clusters:
            raise RuntimeError("could not find a stable in-game timer OCR sequence")

        # The dominant cluster is normal 3:00 countdown. Overtime has the same
        # slope but its intercept is ~120 s later after the 0:00 -> 2:00 reset.
        regular = clusters[0]
        regular_center = float(regular["center"])
        overtime = None
        candidates = [
            item
            for item in clusters[1:]
            if item["min_time"] > regular["min_time"]
            and abs((item["center"] - regular_center) - overtime_duration_seconds) <= 5.0
        ]
        if candidates:
            overtime = max(candidates, key=lambda item: item["size"])

        grouped = _group_spikes(spike_frames, spike_strengths)
        boundaries: list[TimerBoundary] = []

        def add_phase(
            phase: str,
            center: float,
            duration: float,
            global_base: float,
            max_remaining: int,
        ) -> None:
            # Each integer s is the new displayed value immediately after the
            # transition. Match that expected moment to the strongest nearby
            # timer-mask change frame.
            for remaining in range(max_remaining, -1, -1):
                target_time = center - remaining
                if target_time < 0:
                    continue
                target_frame = target_time * fps
                spike = _nearest_spike(grouped, target_frame, fps)
                if spike is None:
                    continue
                frame, strength = spike
                # OCR confidence is measured from the closest coarse sample in
                # this phase; exact time still comes from the spike frame.
                phase_points = regular["points"] if phase == "regular" else overtime["points"]
                nearest = min(
                    phase_points,
                    key=lambda item: abs(item[2] - frame / fps),
                )
                confidence = float(nearest[4])
                elapsed = global_base + (duration - remaining)
                boundaries.append(
                    TimerBoundary(
                        frame_index=int(frame),
                        video_time=float(frame / fps),
                        remaining_seconds=float(remaining),
                        battle_elapsed_seconds=float(elapsed),
                        phase=phase,
                        transition_strength=float(strength),
                        ocr_confidence=confidence,
                    )
                )

        add_phase(
            "regular",
            regular_center,
            regular_duration_seconds,
            0.0,
            int(regular_duration_seconds) - 1,
        )
        if overtime is not None:
            add_phase(
                "overtime",
                float(overtime["center"]),
                overtime_duration_seconds,
                regular_duration_seconds,
                int(overtime_duration_seconds) - 1,
            )

        # Remove duplicate spike frames that can be claimed by adjacent expected
        # seconds when the mask has a wide transition.
        dedup: dict[int, TimerBoundary] = {}
        for boundary in boundaries:
            old = dedup.get(boundary.frame_index)
            if old is None or boundary.ocr_confidence > old.ocr_confidence:
                dedup[boundary.frame_index] = boundary
        boundaries = sorted(dedup.values(), key=lambda item: item.frame_index)

        if len(boundaries) < 20:
            raise RuntimeError(
                f"timer synchronization produced only {len(boundaries)} valid boundaries"
            )

        return cls(
            boundaries,
            ticks_per_second=ticks_per_second,
            regular_duration_seconds=regular_duration_seconds,
            overtime_duration_seconds=overtime_duration_seconds,
            regular_offset=regular_center,
            overtime_offset=None if overtime is None else float(overtime["center"]),
            fps=fps,
        )

    def elapsed_at_frame(self, frame_index: int | float) -> float:
        frame = float(frame_index)
        frames = self._frames
        values = self._elapsed
        if frame <= frames[0]:
            a, b = 0, 1
        elif frame >= frames[-1]:
            a, b = len(frames) - 2, len(frames) - 1
        else:
            b = int(np.searchsorted(frames, frame))
            a = b - 1
        span = frames[b] - frames[a]
        frac = 0.0 if span == 0 else (frame - frames[a]) / span
        return float(values[a] + frac * (values[b] - values[a]))

    def remaining_at_frame(self, frame_index: int | float) -> float:
        elapsed = self.elapsed_at_frame(frame_index)
        if elapsed < self.regular_duration_seconds:
            return float(self.regular_duration_seconds - elapsed)
        return float(
            max(
                0.0,
                self.overtime_duration_seconds
                - (elapsed - self.regular_duration_seconds),
            )
        )

    @staticmethod
    def format_clock(remaining_seconds: float) -> str:
        remaining = max(0.0, float(remaining_seconds))
        minutes = int(remaining // 60)
        seconds = remaining - minutes * 60
        return f"{minutes}:{seconds:05.2f}"

    def reading_at_frame(self, frame_index: int | float) -> TimerReading:
        elapsed = self.elapsed_at_frame(frame_index)
        phase = "regular" if elapsed < self.regular_duration_seconds else "overtime"
        remaining = self.remaining_at_frame(frame_index)
        tick = int(round(elapsed * self.ticks_per_second))
        return TimerReading(
            frame_index=int(round(frame_index)),
            remaining_seconds=remaining,
            battle_elapsed_seconds=elapsed,
            tick=tick,
            game_clock=self.format_clock(remaining),
            phase=phase,
        )

    def to_json(self) -> dict:
        periods = np.diff(self._frames)
        return {
            "ticks_per_second": self.ticks_per_second,
            "regular_duration_seconds": self.regular_duration_seconds,
            "overtime_duration_seconds": self.overtime_duration_seconds,
            "regular_offset": self.regular_offset,
            "overtime_offset": self.overtime_offset,
            "battle_start_video_time": self.battle_start_video_time,
            "boundary_count": len(self.boundaries),
            "first_boundary": self.boundaries[0].__dict__,
            "last_boundary": self.boundaries[-1].__dict__,
            "median_timer_second_frames": float(np.median(periods)),
            "boundaries": [b.__dict__ for b in self.boundaries],
        }
