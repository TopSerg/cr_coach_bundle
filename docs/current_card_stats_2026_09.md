# Current Clash Royale public card stats — 2026-09-20

This project keeps **public card values** separate from **hidden engine mechanics**.

The public layer answers the same kind of questions visible on the in-game card
panel: Level-11 HP/damage, hit speed, range, movement category, target class,
deploy time, spell radius, stun/slow durations, Crown Tower damage and similar
published values. Hidden details such as exact collision resolution, target-lock
semantics, projectile sweep geometry and first-divergence timing stay under the
video-fidelity regression suite.

## Snapshot coverage

`tools/cr_hog_fidelity_test/current_card_stats_2026_09.json` currently contains:

| form | entries |
| --- | ---: |
| current base cards | 123 |
| Evolutions | 42 |
| Heroes | 17 |
| total catalog entries | 182 |

The 123 base cards are cross-checked by ID/name against the current official
Clash Royale API-derived card inventory; the cross-check is stored inside the
catalog and currently reports 123/123 with no missing base cards.

## Source hierarchy

1. **Supercell balance notes** override every older value when a patch changes a
   public stat. The overlay includes the August 26, September 8 and September 16
   2026 changes.
2. **Current official API card inventory** is the authority for which base cards
   currently exist, official IDs, rarity/elixir metadata where exposed, and
   Evo/Hero availability.
3. The bulk Level-11 stat table is sourced from the structured ClashAI snapshot
   generated on 2026-08-26 from Clash Royale Wiki/MediaWiki level-11 values.
4. New September content is supplemented from RoyaleAPI release data and then
   updated by later official Supercell balance changes.
5. Video/demo measurements remain the authority for hidden mechanics that are
   not public card-panel facts.

## Sanity anchor: Electro Spirit

The catalog stores the Level-11 public values:

- HP 215
- damage 99
- chain count 9
- stun 0.5 s
- targets air + ground
- very-fast movement category
- range 2.5 tiles
- current chain radius 3 tiles after the August 26 balance update

The user-supplied Level-15 card panel shows 312 HP, 145 damage, chain 9, stun
0.5 s, air+ground and range 2.5, making it a useful visual cross-check that the
stat family and level scaling line up with the live game.

## Applying the catalog to Rudy

After the ordinary Tournament-11 overlay and card-mechanic patches:

```bash
python tools/cr_hog_fidelity_test/apply_current_card_stats.py \
  --data-dir outputs/rudy_tournament11_data \
  --catalog tools/cr_hog_fidelity_test/current_card_stats_2026_09.json

python tools/cr_hog_fidelity_test/assert_current_card_stats.py \
  --data-dir outputs/rudy_tournament11_data \
  --catalog tools/cr_hog_fidelity_test/current_card_stats_2026_09.json \
  --out outputs/rudy_current_cards/summary.json
```

The overlay updates every current **base card** in Rudy's generated data tree.
Cards absent from the old pinned Rudy snapshot receive an explicit current
Level-11 stat record and official card ID so replay ingestion does not silently
reject them.

Evo/Hero public values are also kept in the catalog, but their *unique*
abilities are not flattened into generic base stats. Existing dedicated
Evo/Hero engine systems and fidelity patches remain responsible for those
mechanics.

## What this does not claim

A card having correct public HP/damage/range does **not** certify full gameplay
parity. For example, Firecracker secondary-projectile geometry, Magic Archer
piercing, Goblin Demolisher transformation timing, Suspicious Bush reveal
timing, Hero abilities and crowd/pathing interactions still need their
mechanic-specific regressions.

The intended validation order is therefore:

`public stats -> mechanic regression -> full replay -> first divergence`.
