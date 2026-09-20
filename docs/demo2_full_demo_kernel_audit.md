# Full-demo kernel audit

Source reviewed: `XRecorder_20260920_02(1).mp4` (`720x1600`, 10,122 video
frames, 191.89 s container duration). The match begins around source timestamp
11 s. Both deck-history screens and the full battle were reviewed.

## Source identity correction

The supplied demo-pack README has the two replay labels reversed. The file
above is the Golem replay, not the Hog/Tesla/Firecracker replay described as
`demo2` in that README. The `demo2_*` clips in the pack are excerpts of this
same Golem replay. The Hog/Tesla deck is the other source replay and remains
the source for the Firecracker/Magic Archer projectile gate.

## Visible decks

| Side | Cards |
| --- | --- |
| topserg | Golem, Baby Dragon, Skeleton Dragons, Fireball, The Log, Night Witch, Valkyrie, Skeletons |
| EgoRkaa | Dart Goblin, Goblin Curse, Giant, Goblins, Goblin Demolisher, Goblin Drill, Suspicious Bush, Clone |

## Kernel result by card

| Card | Mechanic exercised by the full replay | Current result |
| --- | --- | --- |
| Golem | death blast and two Golemites | Existing data path; now covered by the full-demo card gate. |
| Baby Dragon | flying splash projectile | Existing data path; included in full-demo smoke gate. |
| Skeleton Dragons | two flying splash units | Existing data path; included in full-demo smoke gate. |
| Fireball | ballistic area damage | Existing data path; included in full-demo smoke gate. |
| The Log | rolling hitbox and bridge traversal | Fixed in this change and covered by the strict bridge probe. |
| Night Witch | timed Bat waves and death Bat | Existing data path; strict Bat-wave probe added. |
| Valkyrie | ground splash melee | Existing data path; included in full-demo smoke gate. |
| Skeletons | three-unit formation and collision | Existing data path; included in full-demo smoke gate. |
| Dart Goblin | ranged single-target projectile | Existing data path; included in full-demo smoke gate. |
| Goblin Curse | six-second damage/slow zone and death Goblin | Added to the generated Tournament-11 overlay and covered by a strict zone probe. |
| Giant | building-only targeting | Existing data path; included in full-demo smoke gate. |
| Goblins | fast melee group | Existing data path; included in full-demo smoke gate. |
| Goblin Demolisher | ranged ground splash and death blast | Added to the generated overlay; charge-threshold timing remains a video-calibration item. |
| Goblin Drill | burrow, building morph, Goblin waves | Existing data path; strict morph/spawn probe added. |
| Suspicious Bush | stealth building-targeting contact and two Goblins | Added to the generated overlay; contact timing remains a video-calibration item. |
| Clone | one-HP troop duplicate | Existing data path; strict duplicate probe added. |

## Regressions added

- `assert_line_projectile_mechanics.py`: Firecracker five-spark fan and Magic
  Archer continuation through a stationary target to the tower behind it.
- `assert_demo2_card_mechanics.py`: acceptance of the Hog/Tesla replay cards,
  Log bridge traversal, Barbarian Barrel termination position, and Electro
  Spirit multi-target damage/stun.
- `patch_full_demo_cards.py`: data overlay for the three newer cards absent
  from the pinned Rudy snapshot (`Goblin Curse`, `Goblin Demolisher`, and
  `Suspicious Bush`).
- `assert_full_demo_cards.py`: acceptance and strict interaction probes for
  every card in the actual full Golem replay.
- Both gates run after the patched Rudy wheel is built on Linux and Windows.

## Remaining full-match gate

This audit is not a claim of frame-exact full-match agreement. The next gate is
to annotate every play in the actual Golem replay with source time and 18x32
placement cell, then replay from the start and stop at the first
entity/target/HP divergence. The first likely calibration points are Goblin
Demolisher charge timing, Suspicious Bush contact/reveal timing, Goblin Curse
DOT cadence, and the existing Golem death-spawn timing.
