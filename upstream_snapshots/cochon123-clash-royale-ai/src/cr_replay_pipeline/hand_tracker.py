"""Exact Clash Royale hand / cycle reconstruction from observed plays.

CR cycle model
--------------
- 8-card queue; hand = first 4.
- Playing a hand card removes it from its hand slot; the head of the wait
  queue enters the hand; the played card goes to the back of the queue.

The initial queue order is an unknown permutation of the 8 deck slots.
We enumerate initials consistent with the observed card_play sequence and
form a posterior over which slots are in hand at each play.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import permutations
from typing import Any, Iterable, Sequence

import numpy as np

from .policy_dataset import acting_cycle_features, deck_slot_for_card
from .winner_dataset import BattleExample

HAND_SIZE = 4
DECK_SIZE = 8


@lru_cache(maxsize=1)
def _all_initial_queues() -> np.ndarray:
    return np.asarray(list(permutations(range(DECK_SIZE))), dtype=np.int8)


def side_play_sequence(battle: BattleExample, side: str) -> tuple[list[int], list[int]] | None:
    if side not in ("team", "opponent"):
        raise ValueError(f"side must be team|opponent, got {side!r}")
    deck = battle.team_deck if side == "team" else battle.opponent_deck
    event_indices: list[int] = []
    slots: list[int] = []
    for index, event in enumerate(battle.events):
        if event["side"] != side or event["event_type"] != "card_play":
            continue
        slot = deck_slot_for_card(deck, event["card"])
        if slot is None:
            return None
        event_indices.append(index)
        slots.append(int(slot))
    return event_indices, slots


def _advance_queues(queues: np.ndarray, play: int) -> np.ndarray:
    pos = np.argmax(queues[:, :HAND_SIZE] == play, axis=1)
    out = np.empty_like(queues)
    for hand_pos in range(HAND_SIZE):
        mask = pos == hand_pos
        if not np.any(mask):
            continue
        cols = [i for i in range(DECK_SIZE) if i != hand_pos]
        out[mask, : DECK_SIZE - 1] = queues[mask][:, cols]
        out[mask, DECK_SIZE - 1] = play
    return out


def consistent_initial_indices(play_slots: Sequence[int]) -> np.ndarray:
    all_q = _all_initial_queues()
    alive = np.arange(all_q.shape[0], dtype=np.int32)
    if not play_slots:
        return alive
    current = all_q.copy()
    for play in play_slots:
        play = int(play)
        batch = current[alive]
        in_hand = (batch[:, :HAND_SIZE] == play).any(axis=1)
        alive = alive[in_hand]
        if alive.size == 0:
            return alive
        current[alive] = _advance_queues(current[alive], play)
    return alive


def hand_posteriors_smoothed(play_slots: Sequence[int]) -> tuple[np.ndarray, int] | None:
    if not play_slots:
        return np.full((0, DECK_SIZE), 0.5, dtype=np.float64), int(_all_initial_queues().shape[0])
    alive = consistent_initial_indices(play_slots)
    n = int(alive.size)
    if n == 0:
        return None
    curs = _all_initial_queues()[alive].copy()
    posts = np.empty((len(play_slots), DECK_SIZE), dtype=np.float64)
    for t, play in enumerate(play_slots):
        counts = np.bincount(curs[:, :HAND_SIZE].ravel(), minlength=DECK_SIZE)
        posts[t] = counts / float(n)
        curs = _advance_queues(curs, int(play))
    return posts, n


def hand_posteriors_causal(play_slots: Sequence[int]) -> tuple[np.ndarray, list[int]] | None:
    all_q = _all_initial_queues()
    alive = np.arange(all_q.shape[0], dtype=np.int32)
    current = all_q.copy()
    posts = np.empty((len(play_slots), DECK_SIZE), dtype=np.float64)
    n_alive: list[int] = []
    for t, play in enumerate(play_slots):
        n = int(alive.size)
        if n == 0:
            return None
        n_alive.append(n)
        batch = current[alive]
        counts = np.bincount(batch[:, :HAND_SIZE].ravel(), minlength=DECK_SIZE)
        posts[t] = counts / float(n)
        play = int(play)
        in_hand = (batch[:, :HAND_SIZE] == play).any(axis=1)
        alive = alive[in_hand]
        if alive.size == 0:
            return None
        current[alive] = _advance_queues(current[alive], play)
    return posts, n_alive


@dataclass
class SideHandTrack:
    side: str
    event_indices: list[int]
    play_slots: list[int]
    trackable: bool
    n_consistent: int
    smoothed: np.ndarray
    causal: np.ndarray
    _row_by_event: dict[int, int]

    def posterior_at(self, event_index: int, *, smoothed: bool = True) -> np.ndarray | None:
        if not self.trackable:
            return None
        row = self._row_by_event.get(event_index)
        if row is not None:
            src = self.smoothed if smoothed else self.causal
            return src[row]
        prev_row = -1
        for play_i, ei in enumerate(self.event_indices):
            if ei >= event_index:
                break
            prev_row = play_i
        if prev_row < 0:
            return np.full(DECK_SIZE, 0.5, dtype=np.float64)
        return self._posterior_after_play(prev_row, smoothed=smoothed)

    def _posterior_after_play(self, play_row: int, *, smoothed: bool) -> np.ndarray:
        if smoothed:
            alive = consistent_initial_indices(self.play_slots)
            curs = _all_initial_queues()[alive].copy()
            for play in self.play_slots[: play_row + 1]:
                curs = _advance_queues(curs, int(play))
            n = max(int(curs.shape[0]), 1)
            counts = np.bincount(curs[:, :HAND_SIZE].ravel(), minlength=DECK_SIZE)
            return counts / float(n)
        all_q = _all_initial_queues()
        alive = np.arange(all_q.shape[0], dtype=np.int32)
        current = all_q.copy()
        for play in self.play_slots[: play_row + 1]:
            play = int(play)
            batch = current[alive]
            in_hand = (batch[:, :HAND_SIZE] == play).any(axis=1)
            alive = alive[in_hand]
            if alive.size == 0:
                return np.zeros(DECK_SIZE, dtype=np.float64)
            current[alive] = _advance_queues(current[alive], play)
        batch = current[alive]
        n = max(int(batch.shape[0]), 1)
        counts = np.bincount(batch[:, :HAND_SIZE].ravel(), minlength=DECK_SIZE)
        return counts / float(n)

    def mask_at(self, event_index: int, *, threshold: float = 0.5, smoothed: bool = False, fallback: np.ndarray | None = None) -> tuple[np.ndarray, str]:
        post = self.posterior_at(event_index, smoothed=smoothed)
        if post is None:
            if fallback is None:
                fallback = np.zeros(DECK_SIZE, dtype=bool)
            return fallback.astype(bool), "heuristic_fallback"
        return (post >= threshold), "exact"


def track_side(battle: BattleExample, side: str, *, mode: str = "both") -> SideHandTrack:
    empty = np.zeros((0, DECK_SIZE), dtype=np.float64)
    seq = side_play_sequence(battle, side)
    if seq is None:
        return SideHandTrack(side, [], [], False, 0, empty, empty, {})
    event_indices, play_slots = seq
    row_map = {ei: i for i, ei in enumerate(event_indices)}
    if not play_slots:
        return SideHandTrack(side, [], [], True, int(_all_initial_queues().shape[0]), empty, empty, {})
    want_s = mode in ("smoothed", "both")
    want_c = mode in ("causal", "both")
    smoothed = empty
    causal = empty
    n_consistent = 0
    trackable = True
    if want_s:
        pack = hand_posteriors_smoothed(play_slots)
        if pack is None:
            trackable = False
        else:
            smoothed, n_consistent = pack
    if want_c:
        pack = hand_posteriors_causal(play_slots)
        if pack is None:
            trackable = False
        else:
            causal, _ = pack
    if not trackable:
        return SideHandTrack(side, event_indices, play_slots, False, 0, empty, empty, row_map)
    return SideHandTrack(side, event_indices, play_slots, True, n_consistent, smoothed, causal, row_map)


def track_battle(battle: BattleExample, *, mode: str = "both") -> dict[str, SideHandTrack]:
    return {side: track_side(battle, side, mode=mode) for side in ("team", "opponent")}


def heuristic_hand_mask(battle: BattleExample, event_index: int, costs: dict[str, int], side: str) -> np.ndarray:
    swap = side == "opponent"
    _feats, hand_mask = acting_cycle_features(battle, event_index, costs, swap)
    return hand_mask.detach().cpu().numpy().astype(bool)


def side_play_count_before(battle: BattleExample, event_index: int, side: str) -> int:
    return sum(1 for event in battle.events[:event_index] if event["side"] == side and event["event_type"] == "card_play")


def bucket_play_count(n: int) -> str:
    if n <= 3:
        return "0-3"
    if n <= 7:
        return "4-7"
    return "8+"


def iter_play_decision_points(battle: BattleExample) -> Iterable[tuple[str, int, int]]:
    for index, event in enumerate(battle.events):
        if event["event_type"] != "card_play":
            continue
        side = event["side"]
        deck = battle.team_deck if side == "team" else battle.opponent_deck
        slot = deck_slot_for_card(deck, event["card"])
        if slot is None:
            continue
        yield side, index, int(slot)


def summarize_trackability(battles: Sequence[BattleExample]) -> dict[str, Any]:
    total = 0
    untrackable = 0
    n_consistent: list[int] = []
    for battle in battles:
        for side in ("team", "opponent"):
            track = track_side(battle, side)
            if not track.play_slots:
                continue
            total += 1
            if not track.trackable:
                untrackable += 1
            else:
                n_consistent.append(track.n_consistent)
    return {
        "sides_with_plays": total,
        "untrackable_sides": untrackable,
        "untrackable_rate": (untrackable / total) if total else 0.0,
        "mean_n_consistent": float(np.mean(n_consistent)) if n_consistent else 0.0,
        "median_n_consistent": float(np.median(n_consistent)) if n_consistent else 0.0,
    }
