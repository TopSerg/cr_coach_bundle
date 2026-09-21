#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from fingerprints import build_database, normalize_card_key


def _read_allowed(values: list[str], deck_file: str | None) -> list[str] | None:
    cards = [normalize_card_key(x) for x in values]
    if deck_file:
        text = Path(deck_file).read_text(encoding="utf-8")
        for token in text.replace(",", "\n").splitlines():
            token = token.strip()
            if token and not token.startswith("#"):
                cards.append(normalize_card_key(token))
    return cards or None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build compact OpenCV card fingerprints from a one-time card image pack."
    )
    ap.add_argument("images_dir", help="Directory containing one PNG/JPG/WebP per card")
    ap.add_argument("--out", required=True, help="Output card_fingerprints.json")
    ap.add_argument(
        "--stats",
        default="tools/cr_hog_fidelity_test/current_card_stats_2026_09.json",
        help="Optional card stats JSON used to attach elixir cost",
    )
    ap.add_argument("--card", action="append", default=[], help="Only include this card (repeatable)")
    ap.add_argument("--deck-file", help="Optional newline/comma-separated allow-list")
    ap.add_argument(
        "--source-label",
        default="RoyaleAPI/cr-api-assets cards-150",
        help="Provenance string stored in the fingerprint DB",
    )
    ap.add_argument(
        "--collision-threshold",
        type=float,
        default=0.94,
        help="Fail if two different cards have combined fingerprint similarity >= this value",
    )
    ap.add_argument("--show-nearest", type=int, default=20)
    args = ap.parse_args()

    allowed = _read_allowed(args.card, args.deck_file)
    stats = args.stats if args.stats and Path(args.stats).exists() else None
    db = build_database(
        args.images_dir,
        stats_json=stats,
        allowed=allowed,
        source_label=args.source_label,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    db.save(out)

    pairs = db.nearest_pairs(limit=args.show_nearest)
    print(f"wrote {len(db.records)} fingerprints -> {out}")
    if pairs:
        print("\nnearest different-card pairs:")
        for a, b, score in pairs:
            flag = "  COLLISION?" if score >= args.collision_threshold else ""
            print(f"  {a:28s} {b:28s} similarity={score:.4f}{flag}")

    collisions = [x for x in pairs if x[2] >= args.collision_threshold]
    if collisions:
        print(
            f"\nERROR: {len(collisions)} pair(s) exceed collision threshold "
            f"{args.collision_threshold:.3f}. Keep PNGs and improve the fingerprint/crops "
            "before treating the database as unambiguous.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
