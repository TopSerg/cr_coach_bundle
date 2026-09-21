# Core mechanics validation specification (RU)

Дата: 2026-09-21  
Статус: **ТЗ для переделки ядра + physical fidelity gate**  
Основной backend для текущего fidelity-gate: **Rudy**.  
Принцип: механика считается реализованной только после synthetic regression + real-game reference текущего патча.

## 1. Цель

Нужно перейти от card-specific костылей к композиционному ядру:

```text
Entity
├── Geometry
├── Targeting
├── Movement
├── Combat
├── Projectile
├── Status
└── Abilities
```

Карты в основном задают параметры и набор компонентов. Например:

```text
Hog Rider =
GroundMovement
+ BuildingsOnlyTargeting
+ MeleeCombat
+ RiverJump

Prince =
GroundMovement
+ GroundTargeting
+ MeleeCombat
+ Charge
+ RiverJump

Balloon =
AirMovement
+ BuildingsOnlyTargeting
+ CloseCombat
+ DeathBomb

Electro Wizard =
GroundMovement
+ AirGroundTargeting
+ DualTargetAttack
+ StunOnHit
+ SpawnZap
```

Нельзя лечить расхождения финального HP или тайминга локальными поправками конкретной карты, если first divergence возникает в общей механике.

---

## 2. Базовый контракт trace

Каждая активная сущность должна позволять сохранить на каждом simulation tick:

```text
tick
uid
card/species
team

x / y
vx / vy
hp
shield_hp

movement_state
target_uid
target_locked

combat_phase
windup_remaining
cooldown_remaining
load_progress

active_statuses[]
charge_state

path_target
current_waypoint

active_projectiles[]
```

Обязательные события:

```text
TARGET_ACQUIRED
TARGET_DROPPED
TARGET_CHANGED

MOVE_STARTED
PATH_REBUILT

JUMP_STARTED
JUMP_LANDED

CHARGE_STARTED
CHARGE_RESET

ATTACK_WINDUP_STARTED
MELEE_HIT
PROJECTILE_SPAWNED
PROJECTILE_HIT

STUN_APPLIED
STUN_EXPIRED
KNOCKBACK_STARTED
KNOCKBACK_ENDED

DAMAGE
DEATH
SPAWN
```

Comparator обязан выводить **FIRST_DIVERGENCE**, а не только конечную ошибку:

```text
FIRST_DIVERGENCE
tick = 183

REAL:
Hog target = Cannon#7

SIM:
Hog target = PrincessTower#2

Subsystem:
TARGETING

Last exact agreement:
tick = 182
```

---

## 3. Координаты и временная база

Arena:

```text
18 × 32 tiles
1 tile = 1000 mtile
```

Для placement использовать существующую модель `grid2` из
`tools/cr_hog_fidelity_test/PLACEMENT_MODEL.md`.

Не смешивать:

1. selected tile / player-action anchor;
2. resolved entity center;
3. deployment footprint;
4. collision radius.

Replay / validation timebase: **20 TPS = 50 ms/tick**.

Допускается внутренняя sub-tick физика, но canonical events и comparator остаются привязаны к replay ticks.

---

## 4. Как получать real-game reference

### 4.1. Уже существующие материалы

В `main`:

- `physical_tests/references/d02_hog_cannon_01_crossdemo.json`
- `physical_tests/references/d03_hog_cannon_01_secondary.json`
- `physical_tests/references/d03_hog_cannon_02_primary.json`
- `tools/cr_hog_fidelity_test/fixtures/video/hog_solo_tower.mp4`
- `tools/cr_hog_fidelity_test/fixtures/video/hog_vs_cannon_preplaced.mp4`

В ветке `feat/video-placement-annotator` есть программа, которая уже умеет:

- card recognition;
- hand/cycle reconstruction;
- timer-synchronised placement time;
- `tick + x + y`;
- deployment-clock refinement;
- hit-area extraction для части spells.

Перед массовой подготовкой новых references агенту следует перенести/подключить этот инструмент в рабочую ветку.

### 4.2. Формат reference

Для каждого physical test нужен файл:

```text
physical_tests/references/<test_id>.json
```

Минимальная структура:

```json
{
  "id": "projectile_sparky_tornado_001",
  "patch": "2026-09",
  "level": 11,
  "placements": [],
  "observations": []
}
```

Пример observations:

```json
{
  "type": "PROJECTILE_SPAWNED",
  "tick": 212,
  "entity": "sparky_1",
  "target": "knight_1"
}
```

### 4.3. Политика источников

Для базовых механик лучше записывать собственный Friendly Battle на текущем патче.

Публичные интернет-клипы использовать:

1. чтобы найти edge case;
2. чтобы понять, какой experiment воспроизвести;
3. как вспомогательный reference;
4. но численные timings для VERIFIED gate снимать из собственного current-patch ролика.

---

# 5. Acceptance criteria

Механика получает статус `VERIFIED`, только если:

1. есть общий компонент движка;
2. нет ненужного `if card == ...`;
3. есть deterministic synthetic test;
4. есть real-game video reference текущего патча;
5. reference содержит card/tick/x/y;
6. есть нужные state observations;
7. совпадают target / state transitions / event order;
8. совпадают victim set и damage;
9. timing error <= 0.10 s;
10. trajectory p95 <= 0.25 tile, где применимо;
11. все ранее VERIFIED tests остаются зелёными.

После стабилизации video annotation целевой timing tolerance: **±0.05 s**.

---

# 6. Полная матрица Tier-0 tests

| ID | Механика | Physical experiment | PASS |
|---|---|---|---|
| M01 | Placement / geometry | Hog, Cannon, Tesla в известных клетках | center/footprint/lattice совпадают |
| M02 | Ground pathfinding | Knight из разных точек → Princess Tower | правильный мост + trajectory |
| M03 | Air pathfinding | Minions/Balloon из разных точек | прямой air route, river ignored |
| M04 | Ground building-only | Giant/Hog + troop + Cannon | troop ignored, building acquired |
| M05 | Air building-only | Balloon + Cannon | правильный air pull |
| M06 | Target eligibility ground | Knight + ground + air enemy | air target никогда не выбирается |
| M07 | Target eligibility ranged | Musketeer + ground + air | обе категории допустимы |
| M08 | Sticky target | Musketeer уже бьёт Giant; рядом появляется Skeleton | lock не меняется без причины |
| M09 | Retarget on death | текущая цель умирает | новая цель выбирается в правильный tick |
| M10 | Building pull boundary | Hog + Cannon: grid/time sweep | точная карта PULL / NO_PULL |
| M11 | River jump | Hog рядом с river | jump start/land/path совпадают |
| M12 | Jump targetability | Hog jump + Log + air-capable attacker | ground-only miss, air-capable continues |
| M13 | Collision | fast unit behind slow / swarm bridge | нет прохождения тел друг сквозь друга |
| M14 | Melee impact | Mini P.E.K.K.A → stationary Giant | damage только в impact tick |
| M15 | First-hit/load | Hog/Musketeer после движения | первый hit/release совпадает |
| M16 | Basic projectile | Musketeer → Princess Tower | release отдельно от impact |
| M17 | Moving-target projectile | Sparky/Musketeer target displaced after release | реальная projectile semantics совпадает |
| M18 | Shooter dies after release | Musketeer shoots then dies | выпущенный projectile продолжает жить |
| M19 | Splash projectile | Fireball → 3 targets near radius boundary | точный victim set + knockback |
| M20 | Splash melee | Valkyrie в кольце Skeletons | точный AoE victim set |
| M21 | Stun | Zap → attacking Knight | movement/combat pause duration |
| M22 | Retarget after stun | locked unit + new closer target + Zap | post-stun target совпадает |
| M23 | Special reset | Zap → Sparky / Inferno | charge/ramp reset |
| M24 | Inferno ramp | Inferno Tower → Giant | damage stages/timing совпадают |
| M25 | Inferno + river jump | locked Inferno → jumping Hog | continuity/reset совпадает с real game |
| M26 | E-Wiz dual target | 1 / 2 / 3 enemy targets | два bolt slots работают правильно |
| M27 | Chain lightning | E-Dragon + A-B-C geometry | правильная chain sequence/radius |
| M28 | Knockback | Fireball → ground troop | displacement + replanning |
| M29 | Charge | Prince long straight run → target | charge start + charge hit |
| M30 | Charge reset | charging Prince + Zap | charge reset |
| M31 | Dash | Bandit + stationary target | windup/dash/impact/timing |
| M32 | Building lifetime | Cannon без врагов | HP/lifetime/death tick |
| M33 | Death effect | Balloon/Golem/Tombstone | правильный death effect/spawn |
| M34 | Spawn formation | Skeletons/Royal Hogs | правильные offsets |
| M35 | Piercing | Magic Archer → troop → tower | line projectile hits both |
| M36 | Scatter | Hunter at several distances | pellet hit count/damage |
| M37 | Recoil | Firecracker/Sparky after attack | shooter displacement |
| M38 | Tower targeting | Princess Tower + two valid targets | acquisition/lock/retarget |
| M39 | Deploy-time aggro | Cannon timing sweep before Hog enters sight | точная last-pull boundary |

---

# 7. Detailed test specifications

## M01 — Placement / geometry

### Scenario

Place:

- Hog Rider on a normal troop tile;
- Cannon as ordinary odd-footprint building;
- Tesla as even-footprint building.

### Check

- selected anchor;
- resolved center;
- `grid2` phase;
- deployment footprint;
- collision radius stored separately.

### PASS

No movement/combat parameter may compensate for wrong placement resolution.

---

## M02 — Ground pathfinding calibration board

### Current-patch recording

Opponent does nothing. Sequentially deploy Knight at:

```text
left edge
left-center
center-left
center-right
right-center
right edge
```

Repeat mirrored.

### Extract

Every 100 ms:

```text
t, x, y
```

Plus:

```text
bridge chosen
first turn point
bridge entry
bridge exit
tower approach point
```

### PASS

- exact bridge;
- no river crossing outside bridge;
- p95 position error <= 0.25 tile.

---

## M03 — Air pathfinding calibration board

Repeat M02 with Minions and Balloon.

### PASS

- river/bridge do not constrain route;
- ground buildings are not terrain obstacles;
- trajectory p95 <= 0.25 tile.

---

## M04/M05 — Building-only targeting

### Ground

```text
Giant or Hog
enemy Knight near path
enemy Cannon farther but inside sight
```

Expected: Knight ignored; Cannon can become target.

### Air

Repeat with Balloon.

Expected: same targeting category, but different movement geometry.

---

## M08 — Sticky target

### Scenario

1. Musketeer acquires Giant.
2. First windup/release starts.
3. Spawn Skeleton significantly closer.

Repeat Skeleton spawn during:

```text
UNLOCKED
APPROACHING
WINDUP
PROJECTILE_RELEASED
COOLDOWN
```

### Record

```text
target_uid before
target_uid after
TARGET_DROPPED?
TARGET_ACQUIRED?
```

### PASS

Simulator reproduces the real state-machine boundary instead of recalculating nearest target every tick.

A useful 2026 public edge-case for lock semantics is:
https://ru.reddit.com/r/ClashRoyale/comments/1utvclz/why_did_it_do_this/

It should be treated as an edge-case clue, then reproduced in a controlled current-patch battle.

---

## M10 — Hog/Cannon pull matrix

Existing primary reference gives, relative to Hog placement:

```text
Cannon play        2.45 s
Hog hit #1         4.30 s
Hog hit #2         5.90 s
Hog hit #3         7.50 s
Cannon death       7.50 s
Hog death          8.70 s
```

### New experiment

Fix Hog placement and sweep Cannon:

```text
x: center -2 ... center +2 tiles
y: baseline -2 ... baseline +2 tiles
```

Then timing sweep:

```text
-0.50 ... +0.50 s
step = 0.05 s
```

### Output

```text
PULL / NO_PULL
target acquisition tick
minimum edge distance
first hit tick
```

### PASS

Whole pull boundary matches, not only one hand-picked placement.

---

## M11/M12 — River jump

Reference card: Hog Rider.

Public edge-case:
https://www.reddit.com/r/ClashRoyale/comments/s5jn15

It shows the important hypothesis that a Hog crossing the river can pass over The Log.

### Controlled current-patch experiments

#### A. Hog only

Record:

```text
JUMP_STARTED
jump_start x/y
JUMP_LANDED
landing x/y
target before/during/after
```

Expected: crosses open river without using bridge when jump geometry permits.

#### B. Hog + Log during AIRBORNE

Expected: Log does not damage the airborne Hog.

#### C. Hog + air-capable ranged attacker

Expected: verify whether the existing attack/projectile continues during jump.

#### D. Hog already locked by Inferno

Expected: determine whether continuous lock/ramp survives transition to AIRBORNE.

### PASS

Jump is implemented as a gameplay movement state, not a visual z-animation.

---

## M13 — Collision

### Scenarios

1. fast troop directly behind slow troop;
2. two opposite units meet head-on;
3. swarm enters bridge;
4. unit slides around building corner.

### Measure

```text
minimum center distance
overlap duration
position(t)
path replans
```

### PASS

No persistent illegal overlap; outcome/order deterministic.

---

## M14/M15 — Melee + first-hit/load

Reference cards:

- Mini P.E.K.K.A for single-target melee;
- Hog for movement → first hit;
- Musketeer for ranged release timing.

Need separate timestamps:

```text
IN_RANGE
WINDUP_STARTED
IMPACT / PROJECTILE_SPAWN
NEXT_ATTACK
```

The engine should model hit/load semantics rather than only `first_hit_delay + hit_speed`.

Useful background:
https://royaleapi.com/blog/secret-stats

---

## M16 — Musketeer projectile

Existing user/demo material contains a relatively clean Musketeer → Princess Tower interval around 01:56–02:01.

Current level-11 snapshot in this repository:

```text
damage            217
hit speed         1.0 s
range             6 tiles
projectile speed  1000
deploy             1 s
```

### Record

For each shot:

```text
ATTACK_WINDUP_STARTED
PROJECTILE_SPAWNED
PROJECTILE_HIT
tower HP before/after
```

### PASS

- release interval exact within tolerance;
- damage happens at impact, not release;
- damage value exact;
- projectile remains an independent event after release.

---

## M17 — Projectile tracking / target displacement

This is deliberately an investigative test: do not hardcode the expected tracking model before the experiment.

### Preferred setup

```text
Sparky locks a durable ground target
Sparky fires
PROJECTILE_SPAWNED
Tornado moves target strongly after release
observe impact
```

Test hypotheses:

```text
H1: projectile stores original impact point
H2: projectile homes on target UID
H3: projectile continues along a fixed trajectory and collides physically
```

### Reference requirement

Find/use a public Sparky + displacement trick clip as a clue, but record our own current-patch Friendly Battle for the numeric gate.

### PASS

Simulator matches the observed target/impact semantics after projectile release.

---

## M18 — Projectile survives shooter death

### Scenario

```text
Musketeer releases projectile at Giant
immediately kill Musketeer
```

### Check

```text
PROJECTILE_SPAWNED
MUSKETEER_DEATH
PROJECTILE_HIT
GIANT_DAMAGE
```

### PASS

If real game shows continued flight, projectile lifetime must not depend on shooter lifetime.

---

## M19 — Fireball projectile + splash + knockback

Existing demo contains a useful Fireball interaction around 01:12–01:15.

Current level-11 repository snapshot:

```text
damage        688
tower damage  159
speed         600
radius        2.5 tiles
```

### Controlled radius test

Place:

```text
A at impact center
B around 2.3 tiles
C around 2.7 tiles
```

### Record

```text
cast
impact
victim set
damage
knockback start/end
final x/y
```

### PASS

A/B hit and C miss for the measured geometry, subject to actual collision radii.

---

## M20 — Valkyrie splash melee

Place Valkyrie in a controlled Skeleton ring.

### Record

- impact tick;
- exact victim set;
- damage;
- survivors.

### PASS

AoE uses a generic melee-AoE component, not Valkyrie-specific neighbour logic.

---

## M21/M22/M23 — Stun, retarget, reset

Current repository data has Zap stun duration = 0.5 s.

### M21 ordinary stun

```text
Knight A attacks Knight B
Zap A
```

Record:

```text
STUN_APPLIED
attack interruption
movement interruption
STUN_EXPIRED
next attack
```

### M22 retarget after stun

```text
Musketeer locked on Giant
spawn closer Skeleton
Zap Musketeer
```

Do not assume desired target. The current-patch recording defines ground truth.

### M23 special resets

Two isolated tests:

```text
Sparky nearly charged → Zap
Inferno stage/ramp established → Zap
```

Expected high-level behavior: charge/ramp reset.

The code should express this through component hooks such as:

```text
on_stun():
    movement.pause()
    combat.interrupt()
    targeting.invalidate()
    ability.reset_if_configured()
```

not card-name switches.

---

## M24/M25 — Inferno

### M24 stationary ramp

Inferno Tower → Giant, no other interaction.

Record every damage event and ramp stage.

Current level-11 repository snapshot:

```text
Inferno Tower damage stages: 43 / 158 / 847
hit interval: 0.4 s
```

### M25 jump continuity

Inferno already locked onto Hog; Hog reaches river and jumps.

Record:

```text
target_uid
continuous_lock_time
damage_stage
jump start/end
```

The physical test decides whether jump causes reset or continuity.

---

## M26 — Electro Wizard dual target

Current repository snapshot:

```text
hits_per_attack  2
range            5
stun             0.5 s
```

### Scenes

```text
A: one Giant
B: Giant + Knight
C: Giant + Knight + Skeleton
```

### Record

For each attack:

```text
bolt1 target
bolt2 target
damage per target
stun per target
```

### PASS

Two explicit target slots; not splash.

---

## M27 — Electro Dragon chain

Useful public video:
https://www.youtube.com/watch?v=XhMage6v6rA

It demonstrates E-Dragon chain interactions and King activation.

### Controlled geometry

Case 1:

```text
A --- 3.0 tiles --- B --- 3.0 tiles --- C
```

Case 2:

```text
A --- 3.0 tiles --- B --- 4.2 tiles --- C
```

Record exact bounce sequence.

### PASS

Chain search proceeds from the previous victim according to real-game radius/order, not from the Dragon every time.

---

## M28 — Knockback

Fireball → stationary ground troop.

Record:

```text
impact
KNOCKBACK_STARTED
position during displacement
KNOCKBACK_ENDED
PATH_REBUILT
```

PASS: normal pathfinding does not fight the displacement while knockback is active.

---

## M29/M30 — Charge

Reference: Prince.

Current repository snapshot:

```text
normal damage    391
charge damage    783
charge distance  2.5 tiles
base speed       1
charge speed     2
river_jump       true
```

### M29

Prince walks enough distance → charge → hit stationary target.

### M30

Prince reaches charge → Zap → verify reset and re-charge timing.

Battle Ram should be used as a negative architectural control:

```text
Charge = yes
RiverJump = no
```

Charge and RiverJump must therefore remain separate components.

---

## M31 — Dash

Reference: normal Bandit.

### Scenario

Stationary target inside controlled dash range.

Record:

```text
target acquired
dash windup
DASH_STARTED
position(t)
targetability/damage state
DASH_IMPACT
```

Additional shots/spells should be timed into different dash phases to measure the true immunity/targetability window.

PASS: dash is an explicit state / movement override, not just a temporary huge speed.

---

## M32 — Building lifetime / decay

Reference: Cannon, no enemies.

Current level-11 snapshot:

```text
HP        824
lifetime  30 s
```

Record:

```text
spawn tick
HP(t)
death tick
```

PASS: lifetime model reproduces the real HP/death sequence without external damage.

---

## M33 — Death effects

Isolated references:

- Balloon death bomb;
- Tombstone death spawn;
- Golem child spawn.

Pipeline contract:

```text
HP <= 0
→ DYING
→ death effects
→ child spawns
→ target invalidation
→ parent removal
```

Record exact ordering inside a tick.

---

## M34 — Spawn formation

Use Skeletons and Royal Hogs.

Record child centers on first active frame.

PASS:

- correct count;
- correct offsets;
- side mirroring;
- no same-point spawn shortcut.

---

## M35 — Magic Archer piercing

Useful public examples:

https://www.reddit.com/r/ClashRoyale/comments/jd9zc5  
https://www.reddit.com/r/ClashRoyale/comments/16688oz

The second also discusses using Tornado to place a troop on a Magic Archer line to the tower.

Current repository snapshot:

```text
attack range       7
projectile range  11
projectile width   0.5 tile
```

### Controlled test

```text
Magic Archer
     ↓
durable troop
     ↓
Princess Tower
```

Sweep troop X by small steps.

Output:

```text
PIERCE_TOWER / MISS_TOWER
line intersections
victim order
```

PASS: line collision matches boundary; projectile is not implemented as ordinary splash.

---

## M36 — Hunter scatter

Very important: as of September 2026 there are public reports of Hunter pellet/collision edge cases, so current-patch recording is mandatory.

Recent clip/report:
https://www.reddit.com/r/ClashRoyale/comments/1wfz8ag/2_glitches_with_the_hunter/

Another 2026 pellet/shield interaction:
https://www.reddit.com/r/ClashRoyale/comments/1scze4t/how_did_hunter_one_shot_my_delivery/

Current repository snapshot:

```text
projectiles/attack  10
damage per pellet   84
range               4
projectile range    6.5
projectile speed    550
```

### Controlled distances

```text
0.5 tile
3.0 tiles
~maximum pellet range
```

Record:

```text
pellet rays
pellet collision target
hit count
total damage
```

PASS: scatter uses independent projectile collision/order and reproduces the current-patch behavior, including any reproducible live-game bug until Supercell changes it.

---

## M37 — Recoil

Use Firecracker first, Sparky as secondary.

Record shooter x/y immediately before and after attack.

After recoil, verify:

- range relationship;
- target retention;
- path rebuild if needed.

Implement as self-displacement, not enemy knockback.

---

## M38 — Tower targeting

Place two valid targets with controlled arrival timing.

Sweep:

```text
target A first by 50/100/200 ms
target B closer/farther
A dies during tower windup
```

Record:

```text
TARGET_ACQUIRED
shot releases
TARGET_DROPPED
new target
```

PASS: same locking rules are reused where appropriate rather than maintaining a completely unrelated tower-combat implementation.

---

## M39 — Deploy-time aggro boundary

Use the same Hog path and Cannon cell.

Sweep Cannon play time in 50 ms increments around the pull boundary.

Output:

```text
play tick
entity spawn tick
targetable tick
Hog target acquisition tick
PULL / NO_PULL
```

This test defines whether deployment entities participate in sight/collision/targeting before becoming fully active.

---

# 8. Additional card/mechanic probes after Tier-0

После M01–M39:

```text
shields / overflow
slow
freeze
rage
heal
invisibility
burrow / Miner
Tornado continuous displacement
Log rolling collision
returning projectile
clone semantics
transformations
champion abilities
heroes
evolutions
tower troops
```

Каждый новый тип сначала получает отдельный physical reference, а уже потом используется в full-match fidelity.

---

# 9. Agent implementation order

Переделывать код в таком порядке:

```text
P0
1. Geometry / collision radii / placement
2. Target eligibility
3. Target acquisition
4. Sticky target + retarget
5. Ground pathfinding + bridges
6. Building pull

P1
7. Air pathfinding
8. River jump
9. Combat state machine / hit-load timing
10. Projectile lifecycle
11. Stun / retarget / special reset

P2
12. Collision/mass
13. Splash
14. Knockback
15. Charge
16. Inferno ramp
17. Dual-target / chain

P3
18. Death effects
19. Spawn formations
20. Piercing
21. Scatter
22. Recoil
23. Dash
```

Нельзя переходить к следующему блоку, если новый общий фикс ломает уже VERIFIED gate.

---

# 10. Naming / repository layout

Recommended:

```text
physical_tests/
├── references/
│   ├── m01_...
│   ├── m02_...
│   └── ...
├── test_m01_...
├── test_m02_...
└── ...

outputs/
└── physical_tests/
    ├── <test_id>.json
    └── <test_id>_divergence.json
```

Every test should support:

```text
--reference <json>
--output <json>
--strict
```

Strict mode fails CI if any required acceptance criterion is outside tolerance.

---

# 11. Definition of Done for the simulator core

Tier-0 core is considered sufficiently faithful for full-match work when:

- M01–M39 relevant stable tests are green;
- no decision-relevant first divergence appears in the chosen simple full-match replay for a meaningful interval;
- ordinary cards are assembled from shared mechanics, not per-card movement/targeting copies;
- patch-dependent values come from a versioned stats/rules layer;
- full regression suite is run after every mechanics change.

Only after this gate should Policy/Value/counterfactual rollout work treat simulator states as reliable training/evaluation data.
