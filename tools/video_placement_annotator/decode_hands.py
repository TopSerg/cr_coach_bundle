#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core import LayoutConfig, default_layout
from fingerprints import CardFingerprintMatcher, FingerprintDatabase, normalize_card_key
from hand_decoder import FixedSlotVideoDecoder


def parse_deck(value: str | None) -> list[str] | None:
    if not value:
        return None
    cards = [normalize_card_key(x) for x in value.replace(",", " ").split() if x.strip()]
    if len(cards) != 8 or len(set(cards)) != 8:
        raise argparse.ArgumentTypeError("deck must contain eight unique card keys")
    return cards


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Recover both players' fixed-slot hand changes from a replay MP4."
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
    ap.add_argument("--transition-penalty", type=float, default=2.0)
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

    tt, ts, _ = team.collect_scores(
        args.video, start=args.start, end=args.end, sample_fps=args.sample_fps
    )
    ot, os, _ = opponent.collect_scores(
        args.video, start=args.start, end=args.end, sample_fps=args.sample_fps
    )
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
    payload = {
        "schema": "cr_coach.replay_hand_events.v1",
        "video": Path(args.video).name,
        "sample_fps": args.sample_fps,
        "team_deck": list(team.deck or ()),
        "opponent_deck": list(opponent.deck or ()),
        "team_elixir_templates": list(team.badges.costs),
        "opponent_elixir_templates": list(opponent.badges.costs),
        "events": events,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(events)} hand transitions -> {out}")
    print(f"team deck: {', '.join(payload['team_deck'])}")
    print(f"opponent deck: {', '.join(payload['opponent_deck'])}")
    for e in events:
        print(
            f"{e['video_time']:7.2f}  {e['side']:8s} slot={e['slot']}  "
            f"{e['card']} -> {e['incoming']}  conf={e['confidence']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
