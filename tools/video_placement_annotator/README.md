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
      --out tools/video_placement_annotator/card_fingerprints.json \\
      --only-stats-cards

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

The replay HUD keeps the four hand positions fixed. When a card is played, the
new card replaces it in **the same slot**. This is more useful than multiset
tracking: the outgoing card is the played card and the incoming card is the
replacement in that exact slot.

`StableHandTracker` and `FixedSlotVideoDecoder` therefore debounce persistent
one-slot replacements. Multi-slot jumps are treated as UI/classification noise.

## Elixir-cost recognition

`elixir_badges.py` adds a self-calibrating OpenCV-only cost recognizer. A
high-confidence artwork match labels one magenta cost badge; later frames find
that same badge by multi-scale template matching. No OCR engine is required.

The cost is used as an additional fingerprint constraint. For example, a
five-elixir visual candidate is penalized when the replay badge clearly shows
four.

## Deck narrowing

`DeckEvidence` accumulates repeated card observations. Once eight unique cards
have enough support, the matcher locks to that deck and every following lookup
compares against only those eight fingerprints. You can also supply both decks
explicitly when validating a known replay.

## Exact deck cycle + ORB play confirmation

Once the four initial hand cards are known, only **24** orders remain for the
four hidden cards. `cycle_tracker.infer_cycle_path()` evaluates those orders
while enforcing the actual Clash Royale cycle:

    [hand0 hand1 hand2 hand3] [next q1 q2 q3]
                 play slot 2
    [hand0 hand1 next  hand3] [q1 q2 q3 played]

So visual noise can no longer invent an arbitrary incoming card. The incoming
card is dictated by the queue.

The second problem is timing. Selecting or dragging a card changes its border,
scale and position before the card is actually played. `OrbReplayTemplateBank`
learns the card as it is rendered in this exact replay and keeps matching the
art through that selection animation. A play is confirmed only when the old
art disappears and the **expected next card** appears in the same fixed slot.

This split is deliberate:

- fingerprint + elixir => card identity and the eight-card deck;
- full-cycle Viterbi => hidden queue order;
- replay-native ORB => real replacement time, not selection time;
- deployment clock => final placement cell/time refinement.

### Decode both hands

    python tools/video_placement_annotator/decode_hands.py replay.mp4 \
      --start 15 \
      --out outputs/replay_hands.json

Or with known decks:

    python tools/video_placement_annotator/decode_hands.py replay.mp4 \
      --start 15 \
      --team-deck "skeleton-dragons skeletons electro-dragon night-witch the-log valkyrie golem fireball" \
      --opponent-deck "goblin-gang clone dart-goblin goblin-cage goblin-curse goblin-demolisher golden-knight suspicious-bush" \
      --out outputs/replay_hands.json

The default decoder now returns the cycle-consistent result. The JSON includes
the inferred initial hand and hidden queue plus timestamp, confirmation time,
side, fixed slot, outgoing card and incoming card for every real replacement.

Use `--no-orb-refine` only for debugging the older visual-only decoder.

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