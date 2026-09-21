#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core import LayoutConfig, default_layout
from cycle_tracker import (
    infer_cycle_path,
    infer_initial_hand,
    track_cycle_with_orb,
)
from fingerprints import CardFingerprintMatcher, FingerprintDatabase, normalize_card_key
from hand_decoder import FixedSlotVideoDecoder


def parse_deck(value: str | None) -> list[str] | None:
    if not value:
        return None
    cards = [normalize_card_key(x) for x in value.replace(",", " ").split() if x.strip()]
    if len(cards) != 8 or len(set(cards)) != 8:
        raise argparse.ArgumentTypeError("deck must contain eight unique card keys")
    return cards


def _labels(deck: tuple[str, ...], indices) -> list[str]:
    return [deck[int(x)] for x in indices]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Recover both players' card plays from a dual-hand replay MP4."
    )
    ap.add_argument("video")
    ap.add_argument(
        "--fingerprints",
        default="tools/video_placement_annotator/card_fingerprints.json",
    )
    ap.add_argument("--config", help="Optional replay layout JSON")
    ap.add_argument("--team-deck", help="Comma/space separated 8-card deck; omit for auto")
    ap.add_argument("--opponent-deck", help="Comma/space separated 8-card deck; omit for auto")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--sample-fps", type=float, default=4.0)
    ap.add_argument("--smooth-window", type=int, default=5)
    ap.add_argument("--transition-penalty", type=float, default=1.2)
    ap.add_argument(
        "--cycle-penalty",
        type=float,
        default=0.8,
        help="Penalty for one legal play in full 8-card cycle inference",
    )
    ap.add_argument(
        "--orb-fps",
        type=float,
        default=5.0,
        help="Sampling rate used to confirm real slot replacements",
    )
    ap.add_argument(
        "--no-orb-refine",
        action="store_true",
        help="Use the older visual-only fixed-slot decoder",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    team_deck = parse_deck(args.team_deck)
    opponent_deck = parse_deck(args.opponent_deck)
    cfg = LayoutConfig.load(args.config) if args.config else default_layout()
    db = FingerprintDatabase.load(args.fingerprints)

    team = FixedSlotVideoDecoder(
        CardFingerprintMatcher(db, team_deck),
        cfg.bottom_slots,
        side="team",
        deck=team_deck,
    )
    opponent = FixedSlotVideoDecoder(
        CardFingerprintMatcher(db, opponent_deck),
        cfg.top_slots,
        side="opponent",
        deck=opponent_deck,
    )

    # Fingerprints + elixir badges establish the card evidence and, when decks
    # were omitted, discover/lock the eight-card candidate set first.
    tt, ts, _ = team.collect_scores(
        args.video, start=args.start, end=args.end, sample_fps=args.sample_fps
    )
    ot, os, _ = opponent.collect_scores(
        args.video, start=args.start, end=args.end, sample_fps=args.sample_fps
    )

    if args.no_orb_refine:
        _, te = team.decode(
            tt, ts,
            smooth_window=args.smooth_window,
            transition_penalty=args.transition_penalty,
        )
        _, oe = opponent.decode(
            ot, os,
            smooth_window=args.smooth_window,
            transition_penalty=args.transition_penalty,
        )
        events = sorted(
            [
                {
                    "video_time": round(e.video_time, 3),
                    "side": e.side,
                    "slot": e.slot,
                    "card": e.card,
                    "incoming": e.incoming,
                    "confidence": round(e.confidence, 4),
                }
                for e in [*te, *oe]
            ],
            key=lambda x: x["video_time"],
        )
        team_initial = []
        opponent_initial = []
        team_queue = []
        opponent_queue = []
        decoder_name = "fixed_slots+fingerprints+elixir"
    else:
        if team.deck is None or opponent.deck is None:
            raise RuntimeError("deck discovery did not finish")

        team_cards = tuple(team.deck)
        opponent_cards = tuple(opponent.deck)

        team_initial_i = infer_initial_hand(ts)
        opponent_initial_i = infer_initial_hand(os)
        team_path, _ = infer_cycle_path(
            ts, team_initial_i, transition_penalty=args.cycle_penalty
        )
        opponent_path, _ = infer_cycle_path(
            os, opponent_initial_i, transition_penalty=args.cycle_penalty
        )
        team_initial = _labels(team_cards, team_initial_i)
        opponent_initial = _labels(opponent_cards, opponent_initial_i)
        team_queue = _labels(team_cards, team_path[0, 4:])
        opponent_queue = _labels(opponent_cards, opponent_path[0, 4:])

        # ORB is replay-native. It distinguishes "same card selected/dragged"
        # from "old card actually disappeared and expected next card arrived".
        te = track_cycle_with_orb(
            args.video,
            cfg.bottom_slots,
            side="team",
            deck=team_cards,
            initial_hand=team_initial,
            initial_queue=team_queue,
            start=args.start,
            end=args.end,
            sample_fps=args.orb_fps,
        )
        oe = track_cycle_with_orb(
            args.video,
            cfg.top_slots,
            side="opponent",
            deck=opponent_cards,
            initial_hand=opponent_initial,
            initial_queue=opponent_queue,
            start=args.start,
            end=args.end,
            sample_fps=args.orb_fps,
        )
        events = sorted(
            [
                {
                    "video_time": round(e.video_time, 3),
                    "confirm_time": round(e.confirm_time, 3),
                    "side": e.side,
                    "slot": e.slot,
                    "card": e.card,
                    "incoming": e.incoming,
                    "old_similarity": round(e.old_similarity, 4),
                    "incoming_similarity": round(e.incoming_similarity, 4),
                }
                for e in [*te, *oe]
            ],
            key=lambda x: x["video_time"],
        )
        decoder_name = "fingerprints+elixir+full_cycle+orb_confirmation"

    payload = {
        "schema": "cr_coach.replay_hand_events.v2",
        "video": Path(args.video).name,
        "decoder": decoder_name,
        "sample_fps": args.sample_fps,
        "orb_fps": None if args.no_orb_refine else args.orb_fps,
        "team_deck": list(team.deck or ()),
        "opponent_deck": list(opponent.deck or ()),
        "team_initial_hand": team_initial,
        "opponent_initial_hand": opponent_initial,
        "team_initial_queue": team_queue,
        "opponent_initial_queue": opponent_queue,
        "team_elixir_templates": list(team.badges.costs),
        "opponent_elixir_templates": list(opponent.badges.costs),
        "events": events,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(events)} hand transitions -> {out}")
    print(f"decoder: {decoder_name}")
    print(f"team deck: {', '.join(payload['team_deck'])}")
    print(f"opponent deck: {', '.join(payload['opponent_deck'])}")
    if team_initial:
        print(f"team initial: {team_initial}; queue: {team_queue}")
        print(f"opponent initial: {opponent_initial}; queue: {opponent_queue}")
    for e in events:
        print(
            f"{e['video_time']:7.2f}  {e['side']:8s} slot={e['slot']}  "
            f"{e['card']} -> {e['incoming']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
