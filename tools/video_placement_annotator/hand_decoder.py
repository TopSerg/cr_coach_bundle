from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
import math

import cv2
import numpy as np

from core import RectN, crop_rect
from elixir_badges import ElixirBadgeBank, ElixirObservation
from fingerprints import CardFingerprintMatcher, MatchCandidate, normalize_card_key


@dataclass(frozen=True)
class DeckLock:
    cards: tuple[str, ...]
    evidence: tuple[tuple[str, float, int], ...]


class DeckEvidence:
    """Accumulate repeated visual evidence and lock to eight cards.

    A single small replay card can be ambiguous. Deck discovery therefore uses
    repeated observations across all four slots and requires multiple hits
    before a candidate can participate in a lock.
    """

    def __init__(
        self,
        *,
        deck_size: int = 8,
        min_hits: int = 2,
        min_score: float = 0.58,
        min_margin: float = 0.025,
    ):
        self.deck_size = int(deck_size)
        self.min_hits = int(min_hits)
        self.min_score = float(min_score)
        self.min_margin = float(min_margin)
        self.score: dict[str, float] = defaultdict(float)
        self.hits: Counter[str] = Counter()
        self._locked: DeckLock | None = None

    @property
    def locked(self) -> DeckLock | None:
        return self._locked

    def observe(self, ranked: Sequence[MatchCandidate]) -> None:
        if self._locked is not None or not ranked:
            return
        best = ranked[0]
        second = ranked[1].score if len(ranked) > 1 else 0.0
        margin = best.score - second
        if best.score < self.min_score or margin < self.min_margin:
            return
        # Margin matters because it suppresses repeated weak false positives.
        weight = best.score * (1.0 + min(1.0, margin / 0.12))
        self.score[best.card] += float(weight)
        self.hits[best.card] += 1

    def maybe_lock(self) -> DeckLock | None:
        if self._locked is not None:
            return self._locked
        eligible = [
            (card, self.score[card], self.hits[card])
            for card in self.score
            if self.hits[card] >= self.min_hits
        ]
        eligible.sort(key=lambda x: (x[1], x[2]), reverse=True)
        if len(eligible) < self.deck_size:
            return None
        chosen = eligible[: self.deck_size]
        self._locked = DeckLock(
            tuple(sorted(x[0] for x in chosen)),
            tuple(chosen),
        )
        return self._locked


@dataclass(frozen=True)
class SlotState:
    time: float
    slot: int
    card: str
    confidence: float
    margin: float
    observed_elixir: int | None


@dataclass(frozen=True)
class SlotTransition:
    side: str
    video_time: float
    slot: int
    card: str
    incoming: str
    confidence: float


def _rank_to_vector(ranked: Sequence[MatchCandidate], deck: Sequence[str]) -> np.ndarray:
    by = {x.card: float(x.score) for x in ranked}
    # Candidates omitted by a top-N query should be unattractive, but finite.
    floor = min(by.values(), default=0.0) - 0.18
    return np.asarray([by.get(card, floor) for card in deck], dtype=np.float32)


def smooth_score_cube(scores: np.ndarray, window: int = 5) -> np.ndarray:
    """Centered temporal mean for [time, slot, card] score cubes."""
    if window <= 1:
        return scores.copy()
    radius = int(window) // 2
    out = np.empty_like(scores)
    for i in range(len(scores)):
        out[i] = np.mean(
            scores[max(0, i - radius): min(len(scores), i + radius + 1)],
            axis=0,
        )
    return out


def decode_slot_viterbi(
    scores: np.ndarray,
    *,
    transition_penalty: float = 2.0,
) -> np.ndarray:
    """Decode one fixed card slot from a [time, card] score matrix."""
    scores = np.asarray(scores, dtype=np.float32)
    if scores.ndim != 2 or scores.shape[0] == 0:
        raise ValueError("scores must be non-empty [time, card]")
    t_count, card_count = scores.shape
    dp = np.full((t_count, card_count), -1e9, np.float32)
    back = np.zeros((t_count, card_count), np.int16)
    dp[0] = scores[0]
    penalty = float(transition_penalty)
    for t in range(1, t_count):
        prev = dp[t - 1]
        for card in range(card_count):
            candidates = prev - penalty
            candidates = candidates.copy()
            candidates[card] = prev[card]
            best = int(np.argmax(candidates))
            dp[t, card] = candidates[best] + scores[t, card]
            back[t, card] = best
    path = np.empty(t_count, np.int16)
    path[-1] = int(np.argmax(dp[-1]))
    for t in range(t_count - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def decode_joint_fixed_slots(
    scores: np.ndarray,
    *,
    transition_penalty: float = 1.2,
) -> np.ndarray:
    """Jointly decode all four fixed slots with unique-card constraints.

    State = ordered assignment of four distinct deck cards to the four visible
    slots (8P4 = 1680 states). A legal transition either keeps the hand
    unchanged or replaces exactly one slot with one of the four cards currently
    outside the hand. This prevents impossible duplicate-card hands.
    """
    scores = np.asarray(scores, dtype=np.float32)
    if scores.ndim != 3 or scores.shape[1] != 4:
        raise ValueError("scores must be [time, 4 slots, cards]")
    t_count, _, card_count = scores.shape
    if card_count != 8:
        raise ValueError("joint fixed-slot decoder requires an eight-card deck")

    states = np.asarray(
        list(__import__("itertools").permutations(range(card_count), 4)),
        dtype=np.int8,
    )
    state_index = {tuple(map(int, row)): i for i, row in enumerate(states)}
    state_count = len(states)

    predecessors = np.empty((state_count, 16), dtype=np.int16)
    for state_i, state in enumerate(states):
        used = set(map(int, state))
        missing = [x for x in range(card_count) if x not in used]
        q = 0
        for slot in range(4):
            for old_card in missing:
                previous = list(map(int, state))
                previous[slot] = old_card
                predecessors[state_i, q] = state_index[tuple(previous)]
                q += 1

    emission = np.zeros((t_count, state_count), dtype=np.float32)
    for slot in range(4):
        emission += scores[:, slot, states[:, slot]]

    dp = emission[0].copy()
    back = np.zeros((t_count, state_count), dtype=np.int8)
    penalty = float(transition_penalty)
    for t in range(1, t_count):
        candidates = np.empty((17, state_count), dtype=np.float32)
        candidates[0] = dp
        for j in range(16):
            candidates[j + 1] = dp[predecessors[:, j]] - penalty
        choice = np.argmax(candidates, axis=0).astype(np.int8)
        best = np.take_along_axis(candidates, choice[None, :], axis=0)[0]
        dp = best + emission[t]
        back[t] = choice

    path = np.empty(t_count, dtype=np.int16)
    path[-1] = int(np.argmax(dp))
    for t in range(t_count - 1, 0, -1):
        choice = int(back[t, path[t]])
        path[t - 1] = (
            path[t] if choice == 0
            else predecessors[path[t], choice - 1]
        )
    return states[path]


def absorb_short_runs(path: np.ndarray, min_samples: int = 3) -> np.ndarray:
    """Remove one-off/few-frame label glitches after Viterbi."""
    out = np.asarray(path, dtype=np.int16).copy()
    if len(out) < 3 or min_samples <= 1:
        return out
    changed = True
    while changed:
        changed = False
        runs = []
        a = 0
        for i in range(1, len(out) + 1):
            if i == len(out) or out[i] != out[a]:
                runs.append((a, i, int(out[a])))
                a = i
        for ri in range(1, len(runs) - 1):
            a, b, label = runs[ri]
            if b - a < min_samples and runs[ri - 1][2] == runs[ri + 1][2]:
                out[a:b] = runs[ri - 1][2]
                changed = True
                break
    return out


class FixedSlotVideoDecoder:
    """Decode four fixed replay-hand slots using fingerprints + elixir badges."""

    def __init__(
        self,
        matcher: CardFingerprintMatcher,
        slots: Sequence[RectN],
        *,
        side: str,
        deck: Iterable[str] | None = None,
        badge_bank: ElixirBadgeBank | None = None,
        topn: int = 12,
    ):
        if len(slots) != 4:
            raise ValueError("fixed-slot decoder expects exactly four hand slots")
        self.matcher = matcher
        self.slots = tuple(slots)
        self.side = side
        self.badges = badge_bank or ElixirBadgeBank()
        self.topn = int(topn)
        self.deck = tuple(normalize_card_key(x) for x in deck) if deck else None
        self.evidence = DeckEvidence()
        if self.deck:
            if len(set(self.deck)) != 8:
                raise ValueError("Clash Royale deck must contain eight unique cards")
            self.matcher.set_allowed(self.deck)

    def _bootstrap_badge(
        self,
        crop: np.ndarray,
        ranked_without_cost: Sequence[MatchCandidate],
    ) -> None:
        if len(ranked_without_cost) < 2:
            return
        best, second = ranked_without_cost[0], ranked_without_cost[1]
        if best.score < 0.63 or best.score - second.score < 0.045:
            return
        cost = self.matcher.elixir_for(best.card)
        if cost is not None:
            self.badges.observe(cost, crop)

    def rank_crop(self, crop: np.ndarray) -> tuple[list[MatchCandidate], ElixirObservation]:
        raw = self.matcher.rank(crop, None, limit=self.topn)
        self._bootstrap_badge(crop, raw)
        obs = self.badges.classify(crop)
        if obs.cost is None:
            ranked = raw
        else:
            ranked = self.matcher.rank(crop, obs.cost, limit=self.topn)
        if self.deck is None:
            self.evidence.observe(ranked)
            lock = self.evidence.maybe_lock()
            if lock is not None:
                self.deck = lock.cards
                self.matcher.set_allowed(self.deck)
                # Re-rank immediately in the much smaller candidate space.
                ranked = self.matcher.rank(crop, obs.cost, limit=8)
        return ranked, obs

    def collect_scores(
        self,
        video_path: str | Path,
        *,
        start: float = 0.0,
        end: float | None = None,
        sample_fps: float = 4.0,
    ) -> tuple[np.ndarray, np.ndarray, list[list[ElixirObservation]]]:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise OSError(f"cannot open {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = frame_count / fps if frame_count else 0.0
        stop = duration if end is None else min(float(end), duration or float(end))
        start_frame = max(0, round(float(start) * fps))
        stop_frame = round(stop * fps)
        stride = max(1, round(fps / float(sample_fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        # If the deck is not known yet, a discovery pass is required before the
        # score cube can have a fixed card axis.
        if self.deck is None:
            discover_stride = max(stride, round(fps / 1.5))
            idx = start_frame
            next_take = start_frame
            while idx <= stop_frame:
                ok, frame = cap.read()
                if not ok:
                    break
                if idx >= next_take:
                    for rect in self.slots:
                        self.rank_crop(crop_rect(frame, rect))
                    if self.deck is not None:
                        break
                    next_take += discover_stride
                idx += 1
            if self.deck is None:
                cap.release()
                raise RuntimeError(
                    f"{self.side}: could not lock an eight-card deck automatically"
                )
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        deck = tuple(self.deck)
        times: list[float] = []
        score_rows: list[list[np.ndarray]] = []
        cost_rows: list[list[ElixirObservation]] = []
        idx = start_frame
        next_take = start_frame
        while idx <= stop_frame:
            ok, frame = cap.read()
            if not ok:
                break
            if idx >= next_take:
                times.append(idx / fps)
                row = []
                costs = []
                for rect in self.slots:
                    crop = crop_rect(frame, rect)
                    ranked, obs = self.rank_crop(crop)
                    row.append(_rank_to_vector(ranked, deck))
                    costs.append(obs)
                score_rows.append(row)
                cost_rows.append(costs)
                next_take += stride
            idx += 1
        cap.release()
        return (
            np.asarray(times, dtype=np.float64),
            np.asarray(score_rows, dtype=np.float32),
            cost_rows,
        )

    def decode(
        self,
        times: np.ndarray,
        scores: np.ndarray,
        *,
        smooth_window: int = 5,
        transition_penalty: float = 2.0,
        min_run_samples: int = 3,
    ) -> tuple[list[list[SlotState]], list[SlotTransition]]:
        if self.deck is None:
            raise RuntimeError("deck is not locked")
        deck = tuple(self.deck)
        smoothed = smooth_score_cube(scores, smooth_window)
        joint = decode_joint_fixed_slots(
            smoothed,
            transition_penalty=transition_penalty,
        )
        states: list[list[SlotState]] = [[] for _ in range(4)]
        transitions: list[SlotTransition] = []
        for i in range(len(joint)):
            assigned = set(map(int, joint[i]))
            for slot in range(4):
                card_i = int(joint[i, slot])
                row = smoothed[i, slot]
                # Runner-up must also yield a legal unique hand.
                alternatives = [
                    j for j in range(len(deck))
                    if j == card_i or j not in (assigned - {card_i})
                ]
                ranked = sorted(
                    ((float(row[j]), j) for j in alternatives),
                    reverse=True,
                )
                best = float(row[card_i])
                runner = ranked[1][0] if len(ranked) > 1 else 0.0
                states[slot].append(
                    SlotState(
                        float(times[i]), slot, deck[card_i],
                        best, best - runner, None,
                    )
                )
            if i:
                changed = np.where(joint[i] != joint[i - 1])[0]
                if len(changed) == 1:
                    slot = int(changed[0])
                    old_i = int(joint[i - 1, slot])
                    new_i = int(joint[i, slot])
                    row = smoothed[i, slot]
                    assigned = set(map(int, joint[i]))
                    legal_runner = max(
                        (
                            float(row[j]) for j in range(len(deck))
                            if j != new_i and j not in (assigned - {new_i})
                        ),
                        default=0.0,
                    )
                    best = float(row[new_i])
                    margin = best - legal_runner
                    confidence = max(
                        0.0, min(1.0, (best + max(0.0, margin)) / 1.2)
                    )
                    transitions.append(
                        SlotTransition(
                            self.side, float(times[i]), slot,
                            deck[old_i], deck[new_i], confidence,
                        )
                    )
        transitions.sort(key=lambda x: x.video_time)
        return states, transitions
