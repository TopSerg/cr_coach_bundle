# Clash Royale video placement annotator

This tool converts a dual-hand spectator/replay recording into the action stream
used by the CR Coach simulator.

## Card recognition: compact fingerprints

Runtime recognition no longer needs the original card PNGs.

Each card is reduced once to a compact OpenCV fingerprint:

- 64-bit perceptual DCT hash of the central artwork;
- 64-bit perceptual hash of the artwork edges;
- 32-bin luma/hue histogram;
- elixir cost from the current card stats.

The runtime matcher computes the same features from a hand slot and performs a
nearest-neighbour lookup. Once a deck is known, pass its eight card names as an
allow-list; the matcher then compares against only those eight cards.

The original PNG pack is only a **build-time source**. `card_fingerprints.json`
is the versioned runtime database.

### Why more than one hash?

A single exact checksum would break as soon as a card is resized, dimmed for
insufficient elixir, compressed by screen recording or rendered with a
different UI frame. pHash intentionally ignores small pixel changes. Edge pHash
and histogram provide independent tie-breakers. Elixir is a strong discrete
tie-breaker when its HUD digit is available.

### Build/update the database

Only needed when a new card/art is introduced:

    python -m pip install -r tools/video_placement_annotator/requirements.txt

    python tools/video_placement_annotator/build_fingerprints.py \
      path/to/cards-150 \
      --stats tools/cr_hog_fidelity_test/current_card_stats_2026_09.json \
      --out tools/video_placement_annotator/card_fingerprints.json

The builder prints the nearest pairs of *different* cards. If two cards are too
similar, it exits non-zero instead of silently pretending the fingerprint is
unambiguous.

### Runtime

    from fingerprints import CardFingerprintMatcher

    matcher = CardFingerprintMatcher(
        "tools/video_placement_annotator/card_fingerprints.json",
        allowed=[
            "golem", "night-witch", "electro-dragon", "skeletons",
            "valkyrie", "fireball", "the-log", "..."
        ],
    )

    card, confidence, margin = matcher.match(hand_slot_crop)

If an elixir digit detector is available:

    card, confidence, margin = matcher.match(hand_slot_crop, observed_elixir=4)

No card PNG is loaded by the runtime matcher.

## Hand transition logic

For the supplied replay format:

- top four cards = `opponent`;
- bottom four cards = `team`.

After a play Clash Royale shifts the visible hand, so fixed slot-to-slot
comparison is wrong. `StableHandTracker` compares the *multiset* of two stable
four-card states. Exactly one card disappears and one card enters; the
disappearing card is the played card.

## Placement coordinate

Troops/buildings in this spectator UI display a short-lived deployment clock at
the actual release cell. `core.locate_deployment_clock()` finds it in a narrow
window around the hand transition and maps its pixel to the canonical 18 x 32
arena.

Spells without that marker use a lower-confidence visual-change fallback and
remain reviewable.

## Tests

    cd tools/video_placement_annotator
    python -m unittest -v test_fingerprints.py

CI runs the same tests on every feature-branch push.
