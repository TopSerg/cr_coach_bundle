# P2 (part 1) — deterministic synthetic gates for collision and splash

**State:** implementation proposed in `feat/p2-m13-m19-m20-synthetic-gates`.
These are **synthetic regression gates**, not real-game verification.

The pinned Rudy production patch order is unchanged, except for a read-only
`patch_rudy_p2_collision_observability.py` after the M17/M18 projectile patch.
The patch exposes `collision_radius`, `mass` and `is_flying` from Rust
`Entity` in `step_trace()`. Python must not infer those parameters.

## Tests

| Gate | Scenario | Synthetic assertion | Physical evidence |
| --- | --- | --- | --- |
| M13 | Overlapping friendly Giant + Knight | Units separate; the lighter unit is displaced more; mass/radius come from Rust | **PENDING** |
| M13 | Overlapping ground Knight + flying Balloon | Different collision layers do not repel each other | **PENDING** |
| M19 | Fireball + two near Giants and one distant Giant | Near victim set shares an impact tick; distant target is unaffected; damage is delayed past cast | **PENDING** |
| M20 | Valkyrie + symmetric Giant pair and distant Giant | Shared melee splash impact affects near pair simultaneously, not the distant target | **PENDING** |

The test-only displacement interface from M17/M18 is used *between ticks* to
avoid confusing the physics gate with pathfinding. It never modifies production
movement, combat, collision, projectile, or damage execution.

Run with the same patched Windows wheel and Tournament-11 data as the historical
Hog/Cannon/Princess strict gate:

```powershell
python tools/p2_mechanics_smoke.py
```

CI: `.github/workflows/build-rudy-arena18x32-windows.yml`.

**Do not mark VERIFIED** until current-patch reference recordings are annotated
and pass `validate_mechanics.py`. The tests do not yet establish exact
collision resolution tolerances, Fireball AoE boundaries or Valkyrie splash
radius versus live Clash Royale. P2 M24–M30 and M28 knockback also remain open.

When the first synthetic gate fails, capture the earliest tick and compare
authoritative trace before changing shared mechanics. No card-specific
"compensating" constants are permitted.
