from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import itertools

import cv2
import numpy as np

from core import RectN, crop_rect


@dataclass(frozen=True)
class CycleEvent:
    side: str
    video_time: float
    confirm_time: float
    slot: int
    card: str
    incoming: str
    old_similarity: float
    incoming_similarity: float


def play_cycle_state(state: Sequence[int], slot: int) -> tuple[int, ...]:
    """Apply one Clash Royale hand-cycle play to an 8-card state.

    state[0:4] are the four fixed hand slots.
    state[4:8] are the hidden queue in order, with state[4] = next card.
    Playing slot s puts next into that same slot and appends the played card to
    the back of the queue.
    """
    out = list(map(int, state))
    old = out[slot]
    out[slot] = out[4]
    out[4] = out[5]
    out[5] = out[6]
    out[6] = out[7]
    out[7] = old
    return tuple(out)


def infer_initial_hand(
    scores: np.ndarray,
    *,
    stable_samples: int = 4,
) -> tuple[int, int, int, int]:
    """Infer four unique initial hand cards from [time,4,8] score data."""
    scores = np.asarray(scores, dtype=np.float32)
    if scores.ndim != 3 or scores.shape[1:] != (4, 8):
        raise ValueError("scores must be [time, 4, 8]")
    n = min(len(scores), max(1, int(stable_samples)))
    mean = np.mean(scores[:n], axis=0)
    best_state = None
    best_score = -1e30
    for state in itertools.permutations(range(8), 4):
        value = sum(float(mean[slot, card]) for slot, card in enumerate(state))
        if value > best_score:
            best_score = value
            best_state = state
    assert best_state is not None
    return tuple(map(int, best_state))


def _all_cycle_states() -> tuple[np.ndarray, np.ndarray]:
    states = np.asarray(list(itertools.permutations(range(8))), dtype=np.int8)
    index = {tuple(map(int, row)): i for i, row in enumerate(states)}
    predecessors = np.empty((4, len(states)), dtype=np.int32)
    for state_i, row in enumerate(states):
        current = list(map(int, row))
        # Inverse of play_cycle_state for each possible played slot.
        for slot in range(4):
            previous = current.copy()
            previous[slot] = current[7]
            previous[4] = current[slot]
            previous[5] = current[4]
            previous[6] = current[5]
            previous[7] = current[6]
            predecessors[slot, state_i] = index[tuple(previous)]
    return states, predecessors


_CYCLE_STATES, _CYCLE_PREDECESSORS = _all_cycle_states()


def infer_cycle_path(
    scores: np.ndarray,
    initial_hand: Sequence[int],
    *,
    transition_penalty: float = 0.8,
) -> tuple[np.ndarray, list[int | None]]:
    """Infer full hand+queue path while enforcing real deck-cycle mechanics.

    Only 24 initial queue orders are possible once the four visible hand cards
    are known. The dynamic program then permits only:
      - no play;
      - play exactly one of the four hand slots.

    This is intentionally stronger than independent slot decoding: impossible
    incoming-card orders cannot be invented by visual noise.
    """
    scores = np.asarray(scores, dtype=np.float32)
    if scores.ndim != 3 or scores.shape[1:] != (4, 8):
        raise ValueError("scores must be [time, 4, 8]")
    if len(scores) == 0:
        raise ValueError("empty score sequence")
    initial_hand = tuple(map(int, initial_hand))
    if len(initial_hand) != 4 or len(set(initial_hand)) != 4:
        raise ValueError("initial_hand must contain four distinct card indices")

    state_count = len(_CYCLE_STATES)
    valid = np.where(
        np.all(
            _CYCLE_STATES[:, :4]
            == np.asarray(initial_hand, dtype=np.int8)[None, :],
            axis=1,
        )
    )[0]
    dp = np.full(state_count, -1e9, dtype=np.float32)
    emission = np.zeros(state_count, dtype=np.float32)
    for slot in range(4):
        emission += scores[0, slot, _CYCLE_STATES[:, slot]]
    dp[valid] = emission[valid]

    back = np.zeros((len(scores), state_count), dtype=np.int8)
    penalty = float(transition_penalty)
    columns = np.arange(state_count)
    for t in range(1, len(scores)):
        emission.fill(0)
        for slot in range(4):
            emission += scores[t, slot, _CYCLE_STATES[:, slot]]

        candidates = np.empty((5, state_count), dtype=np.float32)
        candidates[0] = dp
        for slot in range(4):
            candidates[slot + 1] = (
                dp[_CYCLE_PREDECESSORS[slot]] - penalty
            )
        choice = np.argmax(candidates, axis=0).astype(np.int8)
        dp = candidates[choice, columns] + emission
        back[t] = choice

    state_indices = np.empty(len(scores), dtype=np.int32)
    actions: list[int | None] = [None] * len(scores)
    state_indices[-1] = int(np.argmax(dp))
    for t in range(len(scores) - 1, 0, -1):
        choice = int(back[t, state_indices[t]])
        if choice == 0:
            state_indices[t - 1] = state_indices[t]
        else:
            slot = choice - 1
            actions[t] = slot
            state_indices[t - 1] = _CYCLE_PREDECESSORS[
                slot, state_indices[t]
            ]
    return _CYCLE_STATES[state_indices], actions


class OrbReplayTemplateBank:
    """Replay-native ORB descriptors used to distinguish selection from play."""

    def __init__(self, *, max_templates_per_card: int = 8):
        self.max_templates_per_card = int(max_templates_per_card)
        self.orb = cv2.ORB_create(
            nfeatures=300,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=5,
            patchSize=15,
            fastThreshold=5,
        )
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.templates: dict[str, list[np.ndarray]] = defaultdict(list)

    def describe(self, image: np.ndarray) -> np.ndarray | None:
        if image is None or image.size == 0:
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, descriptors = self.orb.detectAndCompute(gray, None)
        return descriptors

    def add(self, card: str, descriptors: np.ndarray | None) -> bool:
        if descriptors is None or len(descriptors) < 20:
            return False
        bucket = self.templates[card]
        if len(bucket) >= self.max_templates_per_card:
            return False
        bucket.append(descriptors.copy())
        return True

    def has(self, card: str) -> bool:
        return bool(self.templates.get(card))

    def similarity(
        self,
        card: str,
        descriptors: np.ndarray | None,
    ) -> tuple[float, int]:
        if descriptors is None or len(descriptors) < 8:
            return 0.0, 0
        best = (0.0, 0)
        for reference in self.templates.get(card, ()):
            if reference is None or len(reference) < 8:
                continue
            good = 0
            for pair in self.matcher.knnMatch(reference, descriptors, k=2):
                if len(pair) != 2:
                    continue
                first, second = pair
                if first.distance < 0.75 * second.distance:
                    good += 1
            candidate = (good / max(1, len(reference)), good)
            if candidate[0] > best[0]:
                best = candidate
        return best


def track_cycle_with_orb(
    video_path: str | Path,
    slots: Sequence[RectN],
    *,
    side: str,
    deck: Sequence[str],
    initial_hand: Sequence[str],
    initial_queue: Sequence[str],
    start: float,
    end: float | None = None,
    sample_fps: float = 5.0,
    old_low: float = 0.12,
    incoming_good: float = 0.16,
    first_seen_confirm_s: float = 0.30,
) -> list[CycleEvent]:
    """Refine actual replacement times with replay-native ORB matching.

    Selection/dragging changes borders and position but still retains many ORB
    matches to the same card. A real play removes the old artwork and, shortly
    afterwards, the expected next card appears in the same fixed slot.

    The queue order is already known here, so after all eight cards have been
    seen once, a candidate transition is confirmed only when the *expected*
    incoming card matches. This prevents low-elixir greyscale UI changes from
    being mistaken for plays.
    """
    if len(slots) != 4:
        raise ValueError("expected four fixed hand slots")
    if len(deck) != 8 or len(set(deck)) != 8:
        raise ValueError("deck must contain eight unique cards")
    if len(initial_hand) != 4 or len(initial_queue) != 4:
        raise ValueError("initial hand/queue must contain four cards each")
    if set(initial_hand) | set(initial_queue) != set(deck):
        raise ValueError("initial hand + queue must equal the deck")

    hand = list(initial_hand)
    queue = deque(initial_queue)
    bank = OrbReplayTemplateBank()

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
    ok, seed = cap.read()
    if not ok:
        cap.release()
        raise OSError("cannot read initial replay frame")
    for slot, card in enumerate(hand):
        bank.add(card, bank.describe(crop_rect(seed, slots[slot])))

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    index = start_frame
    next_sample = start_frame
    candidates: list[dict | None] = [None] * 4
    delayed_learning: list[tuple[float, int, str]] = []
    events: list[CycleEvent] = []

    while index <= stop_frame:
        ok, frame = cap.read()
        if not ok:
            break
        if index >= next_sample:
            now = index / fps
            descriptors = [
                bank.describe(crop_rect(frame, rect))
                for rect in slots
            ]

            for item in list(delayed_learning):
                when, slot, card = item
                if now >= when:
                    bank.add(card, descriptors[slot])
                    delayed_learning.remove(item)

            for slot in range(4):
                current = hand[slot]
                incoming = queue[0]
                old_similarity, _ = bank.similarity(
                    current, descriptors[slot]
                )
                incoming_similarity, _ = bank.similarity(
                    incoming, descriptors[slot]
                )
                candidate = candidates[slot]

                if candidate is None:
                    if old_similarity < old_low:
                        candidates[slot] = {
                            "first": now,
                            "min_old": old_similarity,
                        }
                    continue

                candidate["min_old"] = min(
                    candidate["min_old"], old_similarity
                )
                # Same card clearly came back: selection/animation only.
                if old_similarity >= max(old_low * 1.6, 0.20):
                    candidates[slot] = None
                    continue

                age = now - candidate["first"]
                if bank.has(incoming):
                    confirm = (
                        incoming_similarity >= incoming_good
                        and incoming_similarity > old_similarity * 1.35
                    )
                else:
                    # First cycle: queue identity came from cycle inference.
                    # Wait until old artwork stays gone and a real card image
                    # occupies the slot, then learn the replay-native template.
                    desc = descriptors[slot]
                    confirm = (
                        age >= first_seen_confirm_s
                        and desc is not None
                        and len(desc) >= 30
                    )

                if not confirm:
                    continue

                old = current
                new = queue.popleft()
                queue.append(old)
                hand[slot] = new
                events.append(
                    CycleEvent(
                        side=side,
                        video_time=float(candidate["first"]),
                        confirm_time=float(now),
                        slot=slot,
                        card=old,
                        incoming=new,
                        old_similarity=float(old_similarity),
                        incoming_similarity=float(incoming_similarity),
                    )
                )
                bank.add(new, descriptors[slot])
                delayed_learning.append((now + 0.60, slot, new))
                candidates = [None] * 4
                break

            next_sample += stride
        index += 1

    cap.release()
    return events
