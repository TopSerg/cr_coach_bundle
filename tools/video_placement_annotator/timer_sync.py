from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import math

import cv2
import numpy as np


@dataclass(frozen=True)
class TimerBoundary:
    frame_index: int
    video_time: float
    remaining_seconds: float
    transition_strength: float


@dataclass(frozen=True)
class TimerReading:
    frame_index: int
    remaining_seconds: float
    battle_elapsed_seconds: float
    tick: int
    game_clock: str


def _timer_mask(frame: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    h, w = frame.shape[:2]
    x1 = max(0, min(w, round(roi[0] * w)))
    y1 = max(0, min(h, round(roi[1] * h)))
    x2 = max(0, min(w, round(roi[2] * w)))
    y2 = max(0, min(h, round(roi[3] * h)))
    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    white = gray >= 180
    red = (
        ((hsv[:, :, 0] <= 8) | (hsv[:, :, 0] >= 170))
        & (hsv[:, :, 1] >= 90)
        & (hsv[:, :, 2] >= 80)
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


def _longest_regular_chain(
    candidates: Sequence[tuple[int, float]],
    fps: float,
    *,
    min_period_s: float = 0.72,
    max_period_s: float = 1.30,
) -> list[tuple[int, float]]:
    """Find the longest approximately one-second countdown transition chain."""
    if not candidates:
        return []
    best: list[tuple[int, float]] = []
    for start in range(len(candidates)):
        chain = [candidates[start]]
        last = candidates[start][0]
        for item in candidates[start + 1 :]:
            dt = (item[0] - last) / fps
            if min_period_s <= dt <= max_period_s:
                chain.append(item)
                last = item[0]
            elif dt > max_period_s:
                break
        if len(chain) > len(best):
            best = chain
    return best


class GameTimerSync:
    """Synchronize frame index to the actual Clash Royale countdown clock.

    The detector does not trust MP4 timestamps for battle time. It detects the
    exact video frames where the displayed integer second changes, assigns each
    boundary an integer remaining-time value, then linearly interpolates inside
    each real timer second. This compensates for screen-recording drift.

    For a complete replay that reaches 0:00, the last normal digit transition
    is the 0:01 -> 0:00 boundary and therefore corresponds to 1.00 seconds
    remaining just before the display changes.
    """

    DEFAULT_TIMER_ROI = (600 / 720, 255 / 1600, 710 / 720, 295 / 1600)

    def __init__(
        self,
        boundaries: Sequence[TimerBoundary],
        *,
        ticks_per_second: int = 20,
        battle_duration_seconds: float = 180.0,
    ):
        if len(boundaries) < 2:
            raise ValueError("timer synchronization requires at least two boundaries")
        self.boundaries = tuple(boundaries)
        self.ticks_per_second = int(ticks_per_second)
        self.battle_duration_seconds = float(battle_duration_seconds)
        self._frames = np.asarray([b.frame_index for b in boundaries], dtype=np.float64)
        self._remaining = np.asarray([b.remaining_seconds for b in boundaries], dtype=np.float64)

    @classmethod
    def detect(
        cls,
        video_path: str | Path,
        *,
        timer_roi: tuple[float, float, float, float] | None = None,
        change_threshold: float = 0.020,
        last_boundary_remaining: float = 1.0,
        ticks_per_second: int = 20,
        battle_duration_seconds: float = 180.0,
    ) -> "GameTimerSync":
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise OSError(f"cannot open {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        roi = timer_roi or cls.DEFAULT_TIMER_ROI
        previous = None
        spike_frames: list[int] = []
        spike_strengths: list[float] = []
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
            frame_index += 1
        cap.release()

        grouped = _group_spikes(spike_frames, spike_strengths)
        chain = _longest_regular_chain(grouped, fps)
        if len(chain) < 20:
            raise RuntimeError(
                f"timer transition chain too short: {len(chain)} boundaries"
            )

        # The chain runs in countdown order. For complete replays the last
        # boundary is 1.00 s remaining; values before it are exact integers.
        count = len(chain)
        remaining = [
            float(last_boundary_remaining + (count - 1 - i))
            for i in range(count)
        ]
        boundaries = [
            TimerBoundary(
                frame_index=int((item[0])),
                video_time=float(item[0] / fps),
                remaining_seconds=remaining[i],
                transition_strength=float(item[1]),
            )
            for i, item in enumerate(chain)
        ]
        return cls(
            boundaries,
            ticks_per_second=ticks_per_second,
            battle_duration_seconds=battle_duration_seconds,
        )

    def remaining_at_frame(self, frame_index: int | float) -> float:
        frame = float(frame_index)
        frames = self._frames
        values = self._remaining
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

    @staticmethod
    def format_clock(remaining_seconds: float) -> str:
        remaining = max(0.0, float(remaining_seconds))
        minutes = int(remaining // 60)
        seconds = remaining - minutes * 60
        return f"{minutes}:{seconds:05.2f}"

    def reading_at_frame(self, frame_index: int | float) -> TimerReading:
        remaining = self.remaining_at_frame(frame_index)
        elapsed = self.battle_duration_seconds - remaining
        tick = int(round(elapsed * self.ticks_per_second))
        return TimerReading(
            frame_index=int(round(frame_index)),
            remaining_seconds=remaining,
            battle_elapsed_seconds=elapsed,
            tick=tick,
            game_clock=self.format_clock(remaining),
        )

    def to_json(self) -> dict:
        periods = np.diff(self._frames)
        return {
            "ticks_per_second": self.ticks_per_second,
            "battle_duration_seconds": self.battle_duration_seconds,
            "boundary_count": len(self.boundaries),
            "first_boundary": self.boundaries[0].__dict__,
            "last_boundary": self.boundaries[-1].__dict__,
            "median_timer_second_frames": float(np.median(periods)),
            "boundaries": [b.__dict__ for b in self.boundaries],
        }
