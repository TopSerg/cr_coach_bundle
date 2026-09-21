#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core import LayoutConfig, default_layout
from placement_refiner import refine_placement
from timer_sync import GameTimerSync


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Convert recovered replay hand events into timer-synchronized "
            "tick+x+y simulator placements."
        )
    )
    ap.add_argument("video")
    ap.add_argument("hand_events")
    ap.add_argument("--config")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ticks-per-second", type=int, default=20)
    ap.add_argument("--battle-duration", type=float, default=180.0)
    ap.add_argument(
        "--last-boundary-remaining",
        type=float,
        default=1.0,
        help=(
            "Remaining seconds represented by the last regular timer boundary. "
            "For a complete countdown replay this is 1.0."
        ),
    )
    args = ap.parse_args()

    cfg = LayoutConfig.load(args.config) if args.config else default_layout()
    source = json.loads(Path(args.hand_events).read_text(encoding="utf-8"))
    timer = GameTimerSync.detect(
        args.video,
        last_boundary_remaining=args.last_boundary_remaining,
        ticks_per_second=args.ticks_per_second,
        battle_duration_seconds=args.battle_duration,
    )

    placements = []
    unresolved = []
    for item in source.get("events", []):
        approx_time = float(item["video_time"])
        side = str(item["side"])
        card = str(item["card"])
        obs = refine_placement(
            args.video,
            approx_time,
            cfg,
            side,
            card,
        )
        if obs is None:
            unresolved.append(
                {
                    "video_time": approx_time,
                    "side": side,
                    "card": card,
                    "reason": "placement locator returned no observation",
                }
            )
            continue

        timer_reading = timer.reading_at_frame(obs.frame_index)
        annotation = {
            "game_clock": timer_reading.game_clock,
            "remaining_seconds": round(
                timer_reading.remaining_seconds, 4
            ),
            "battle_elapsed_seconds": round(
                timer_reading.battle_elapsed_seconds, 4
            ),
            "video_frame": obs.frame_index,
            "video_time": round(obs.video_time, 6),
            "hand_event_video_time": round(approx_time, 6),
            "locator": obs.locator,
            "placement_confidence": round(obs.confidence, 4),
            "placement_pixel": [
                round(obs.pixel[0], 3),
                round(obs.pixel[1], 3),
            ],
        }
        if obs.hit_area is not None:
            annotation["hit_area"] = obs.hit_area

        placements.append(
            {
                "tick": timer_reading.tick,
                "side": side,
                "card": card,
                "x": obs.x,
                "y": obs.y,
                "annotation": annotation,
            }
        )

    placements.sort(key=lambda event: event["tick"])
    payload = {
        "schema_version": 1,
        "battle_id": Path(args.video).stem + "_auto_timer_synced",
        "ticks_per_second": args.ticks_per_second,
        "mode": "placements",
        "coordinate_system": "world_cells",
        "level": 11,
        "end_tick": int(
            round(args.battle_duration * args.ticks_per_second)
        ),
        "timer_sync": timer.to_json(),
        "source_hand_events": Path(args.hand_events).name,
        "notes": (
            "Ticks are synchronized to the real in-game countdown timer, not "
            "raw MP4 time. Troops/buildings use the first visible deployment "
            "clock frame. Spells use their first robust hit-area/target-ring "
            "frame and include hit-area metadata in annotation."
        ),
        "events": placements,
        "unresolved": unresolved,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"wrote {len(placements)} placements, "
        f"{len(unresolved)} unresolved -> {out}"
    )
    for event in placements:
        a = event["annotation"]
        print(
            f"{a['game_clock']:>7s} tick={event['tick']:4d} "
            f"{event['side']:8s} {event['card']:20s} "
            f"x={event['x']:2d} y={event['y']:2d} "
            f"{a['locator']}"
        )
    return 0 if not unresolved else 2


if __name__ == "__main__":
    raise SystemExit(main())
