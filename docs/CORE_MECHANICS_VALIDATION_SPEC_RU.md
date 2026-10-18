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

---

<!-- CR_DEMO_COVERAGE_20261018_START -->
# 12. Реальные видеоэталоны: Google Drive / CR demo (18.10.2026)

> **Статус: каталог кандидатов, НЕ результаты валидации.** Это дополнение к §4–§7 и не меняет acceptance criteria §5. Видеопериоды получены первичным просмотром кадров с шагом и выборочными контрольными кадрами, **не покадровой** синхронизацией. Для каждой механики ниже перечислены **все сцены, отмеченные в имеющемся индексе**, включая слабые/косвенные кандидаты. Отсутствие сцены в этом индексе не доказывает её отсутствие внутри ролика. Ни одна новая M01–M39 не получает статус VERIFIED до аннотации и запуска Rudy + strict validator.

Источники: [папка CR demo](https://drive.google.com/drive/folders/1ou-dqIJKyasCPD5w_ubjeOHsSjvBj3Xr) (аккаунт mcsergspb), 10 видео `XRecorder_20261018_01–10.mp4`, 37 мин 14 с суммарно, исходные ролики 720×1600, около 50–54 FPS. **Все интервалы ниже — время проигрывателя MP4, не игровые секунды/tick.** Для прогона: синхронизировать игровой HUD-таймер, восстановить реальные card/tick/x/y и уровни, пометить обычная/Evo/hero/ability, исключить влияние неучтённых эффектов. Большинство башен на видео уровня 16, некоторые войска уровня 15; численный урон нельзя напрямую сравнивать с level-11 fixture.

### 12.1. Каталог просмотренных эпизодов (все 25 кандидатов)

Код `DxxA/B/C` означает отдельный временной диапазон **в файле xx**. Ссылка ведёт к оригинальному видео в Google Drive; в указанное время следует перейти внутри проигрывателя.

| Сцена / время MP4 | Визуальный контекст (пока без точной разметки карт) | Возможные M-тесты |
|---|---|---|
| [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view) | Одиночные юниты у мостов, дальние атаки | M02, M14, M15, M16, M38 |
| [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view) | Группы справа, бой у моста и башни, визуальные эффекты | M09, M13, M14, M15, M19, M34, M38 |
| [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view) | Правый фланг: одиночные юниты, дальний бой, башня | M02, M14, M15, M16, M38 |
| [D02B 02:25–03:11](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view) | Группы в зоне моста, урон башне | M09, M13, M14, M15, M19, M38 |
| [D03A 00:45–01:15](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view) | Правый мост: движение и атаки | M02, M14, M15, M38 |
| [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view) | Здание и группы справа, меняющиеся взаимодействия | M01, M09, M13, M14, M38 |
| [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view) | Плотные схватки у башни и моста | M09, M13, M14, M15, M34, M38 |
| [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view) | Правый мост, оборонительное здание и ответная атака | M01, M02, M14, M15, M38 |
| [D04B 02:27–03:11](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view) | Групповой бой у правой башни и атака на верхнюю | M09, M13, M14, M15, M34, M38 |
| [D05A 00:35–01:07](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view) | Группа слева и видимый эффект по площади на мосту | M02, M13, M19, M34 |
| [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view) | Оборонительное здание и бой внизу слева | M01, M09, M13, M14, M38 |
| [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view) | Массовый бой и эффекты по площади у мостов | M09, M13, M14, M19, M34, M38 |
| [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view) | Правый мост: группа, бой, предполагаемый эффект контроля (тип не установлен) | M02, M09, M13, M14, M21, M38 |
| [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view) | Оборонительное здание, мост, атаки по башне | M01, M02, M14, M15, M38 |
| [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view) | Два фланга, массовый бой и взрывное воздействие | M09, M13, M14, M19, M28, M34, M38 |
| [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view) | Группы у мостов и атака верхней башни | M02, M13, M14, M15, M34, M38 |
| [D07B 01:47–02:31](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view) | Защитные взаимодействия и реакции на появление юнитов | M09, M13, M14, M38 |
| [D07C 02:55–03:22](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view) | Плотная группа у нижней башни, башенная защита | M09, M13, M14, M34, M38 |
| [D08A 00:30–01:08](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view) | Правый мост, нижняя башня, атакующее продвижение | M02, M09, M14, M15, M38 |
| [D08B 01:29–02:19](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view) | Атака Princess Tower и затем King Tower с заметным падением HP | M02, M14, M15, M38 |
| [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view) | Два фланга и дальние атаки по верхней правой башне | M02, M14, M15, M16, M38 |
| [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view) | Группы внизу, воздушный/подвесной объект и возможный эффект гибели (карта неизвестна) | M09, M13, M19, M33, M34, M38 |
| [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view) | Правый мост: группы, дальний и ближний бой | M02, M13, M14, M15, M16, M34, M38 |
| [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view) | Оборона справа, плотные столкновения и эффекты площади | M01, M09, M13, M14, M19, M28, M34, M38 |
| [D10C 04:08–04:48](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view) | Овертайм: групповой бой справа и эффект по площади | M09, M13, M14, M19, M34, M38 |

### 12.2. Протокол фальсификации для каждого M01–M39

**Как читать:** «кандидаты» — это ВСЕ диапазоны из каталога 12.1, связанные с конкретной механикой при первичном просмотре; не доказательство, что в них есть вся нужная причинная последовательность. «Смежные» — места для повторной покадровой проверки, **не засчитанные даже как прямые кандидаты**. Только `annotated → validated → VERIFIED` по §5 закрывает механику. Для любого теста сохранять `FIRST_DIVERGENCE`, реальные состояния, видео-кадры и конфигурацию движка/патча.

#### M01

- **Кандидаты из разметки:** [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** В начале появления юнита/здания сопоставить отметку постановки, клетку, центр, footprint и радиус; отделить момент высадки от момента начала действий.
- **Что опровергнет реализацию в Rudy:** Неверный центр или фаза сетки, размещение внутри недопустимой клетки либо искажённая стартовая траектория.
- **Чего сейчас не хватает:** Нужны кадры появления и синхронизация с deployment-clock; выбранный центр нельзя выводить только из позднего положения.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M02

- **Кандидаты из разметки:** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D03A 00:45–01:15](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05A 00:35–01:07](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D08A 00:30–01:08](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D08B 01:29–02:19](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Для каждого наземного юнита снять последовательность x/y, выбор моста, точки входа/выхода и обход препятствий.
- **Что опровергнет реализацию в Rudy:** Реальный юнит выбрал иной мост, прошёл другой маршрут или систематически опередил/отстал от Rudy за пределами допуска.
- **Чего сейчас не хватает:** Выделить обычных наземных юнитов и отфильтровать замедление, отталкивание, Evo/hero-побочные эффекты.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M03

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view).
- **Что должно быть видно для подтверждения:** Наблюдать подтверждённый летающий юнит от появления до цели; движение над рекой независимо от моста.
- **Что опровергнет реализацию в Rudy:** Rudy ведёт летуна через мост либо неправильно обходит наземное препятствие.
- **Чего сейчас не хватает:** В первичном каталоге нет установленного воздушного юнита с полной траекторией.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M04

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Установить, что Giant/Hog игнорирует находящегося на пути бойца и выбирает разрешённое вражеское здание.
- **Что опровергнет реализацию в Rudy:** Rudy атакует бойца или игнорирует здание, хотя в записи оно доступно и допустимо.
- **Чего сейчас не хватает:** На кадрах с оборонительными зданиями тип и приоритет наступающего юнита ещё не подтверждены.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M05

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Подтвердить воздушный buildings-only (например Balloon) и его переключение на здание; измерить маршрут и выбор цели.
- **Что опровергнет реализацию в Rudy:** Rudy не притягивается зданием либо ошибочно переключается на наземную цель.
- **Чего сейчас не хватает:** Визуально предполагаемый воздушный объект D09B не идентифицирован и не даёт чистого теста.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M06

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view).
- **Что должно быть видно для подтверждения:** Выделить наземного атакующего и одновременно доступные наземную и воздушную цели.
- **Что опровергнет реализацию в Rudy:** Ground-only атакует воздушного противника или ошибочно переключается на него.
- **Чего сейчас не хватает:** Ни одна сцена пока не подтверждает одновременные разнокатегорийные цели.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M07

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Наблюдать дальнобойного бойца при последовательном появлении доступных наземной и воздушной целей.
- **Что опровергнет реализацию в Rudy:** Реальный стрелок атакует воздух, а Rudy его игнорирует (или наоборот); расходится выбранная цель.
- **Чего сейчас не хватает:** Дальний бой в кадре есть, но возможность атаковать обе категории не доказана.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M08

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D07C 02:55–03:22](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view).
- **Что должно быть видно для подтверждения:** Найти кадры, где стрелок уже захватил цель, а затем ближе появляется иной допустимый враг; проверить lock до/после.
- **Что опровергнет реализацию в Rudy:** Rudy переключил цель без реального основания или удержал цель, которую игра сбросила.
- **Чего сейчас не хватает:** Общие групповые схватки не показывают однозначно предыдущий target_uid и причинность.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M09

- **Кандидаты из разметки:** [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02B 02:25–03:11](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04B 02:27–03:11](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07B 01:47–02:31](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07C 02:55–03:22](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D08A 00:30–01:08](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10C 04:08–04:48](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Проверить кадры смерти текущей цели и следующую атаку того же юнита/башни; снять tick смены цели.
- **Что опровергнет реализацию в Rudy:** Rudy дольше держит мёртвую цель или выбирает не того следующего противника.
- **Чего сейчас не хватает:** Во всех указанных окнах сначала подтвердить смерть именно текущей цели, а не соседнего юнита.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M10

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Взять атакующего здания юнита и оборонительное здание, измерить переход target на building при конкретных x/y.
- **Что опровергнет реализацию в Rudy:** В игре здание меняет маршрут/цель, а Rudy не меняет (или наоборот).
- **Чего сейчас не хватает:** Ни одно окно не даёт подтверждённую контролируемую матрицу Hog+Cannon по клеткам; строгую границу PULL/NO_PULL этими матчами не закрыть.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M11

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D03A 00:45–01:15](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Установить, есть ли Hog/Prince и именно прыжок над открытой рекой; отметить начало, посадку, x/y.
- **Что опровергнет реализацию в Rudy:** Rudy идёт по мосту вместо прыжка либо расходятся старт/посадка.
- **Чего сейчас не хватает:** В первичной разметке нет однозначно распознанного прыжка.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M12

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Нужен прыгающий юнит и атакующий ground-only/air-capable во время AIRBORNE; отдельно Log.
- **Что опровергнет реализацию в Rudy:** Rudy наносит ground-only урон в воздухе или неверно сохраняет воздушно-допустимую атаку.
- **Чего сейчас не хватает:** Нужного сочетания на текущих кадрах не подтверждено.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M13

- **Кандидаты из разметки:** [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02B 02:25–03:11](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04B 02:27–03:11](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05A 00:35–01:07](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07B 01:47–02:31](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07C 02:55–03:22](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10C 04:08–04:48](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Снимать центры/радиусы плотных групп и движение пары быстрый/медленный у моста/здания.
- **Что опровергнет реализацию в Rudy:** Rudy пропускает юнитов друг через друга, даёт устойчивые наложения либо другой порядок обхода.
- **Чего сейчас не хватает:** Массовый бой даёт сложный, но не изолированный референс; нужны траектории между кадрами.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M14

- **Кандидаты из разметки:** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D02B 02:25–03:11](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D03A 00:45–01:15](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D04B 02:27–03:11](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07B 01:47–02:31](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07C 02:55–03:22](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D08A 00:30–01:08](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D08B 01:29–02:19](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10C 04:08–04:48](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Выделить отдельный melee-удар: вход в радиус, windup, кадр контакта и списание HP.
- **Что опровергнет реализацию в Rudy:** HP меняется раньше контакта или Rudy пропускает/дублирует удар.
- **Чего сейчас не хватает:** Выделить именно melee, не смешивать с выстрелами, башней и AoE.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M15

- **Кандидаты из разметки:** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D02B 02:25–03:11](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D03A 00:45–01:15](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D04B 02:27–03:11](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D08A 00:30–01:08](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D08B 01:29–02:19](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Измерить время от входа в радиус до первого удара/выстрела и интервалы следующих атак.
- **Что опровергнет реализацию в Rudy:** Rudy начинает первый удар слишком рано/поздно или неверно сохраняет load после движения.
- **Чего сейчас не хватает:** Нужны точные кадры постановки и единственная видимая цель; сложные бои дают только кандидатов.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M16

- **Кандидаты из разметки:** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Отдельно фиксировать появление снаряда, его полёт и момент снятия HP у цели.
- **Что опровергнет реализацию в Rudy:** Урон в Rudy происходит в момент выстрела, неверен flight time или impact/target.
- **Чего сейчас не хватает:** На видео идентифицировать конкретного стрелка и projectile; контактный урон исключить.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M17

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужен снаряд уже в полёте и заметно сместившаяся затем цель; проверить homing/fixed-point.
- **Что опровергнет реализацию в Rudy:** Rudy попал по первоначальной точке вместо движущейся цели или наоборот.
- **Чего сейчас не хватает:** Обычная стрельба без пост-релизного смещения цели не подтверждает M17.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M18

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужен выпущенный снаряд, смерть стрелка до попадания и затем damage по цели.
- **Что опровергнет реализацию в Rudy:** Снаряд исчезает из Rudy после смерти стрелка вопреки игре.
- **Чего сейчас не хватает:** В выбранных видео такой порядок событий ещё не найден.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M19

- **Кандидаты из разметки:** [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02B 02:25–03:11](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D05A 00:35–01:07](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10C 04:08–04:48](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Отметить точку и кадр взрыва, измерить расстояния нескольких противников до центра и набор пострадавших.
- **Что опровергнет реализацию в Rudy:** В Rudy урон получают юниты за радиусом либо отсутствуют жертвы внутри действительного радиуса.
- **Чего сейчас не хватает:** Тип заклинания, Evo-модификации, уровень и момент импакта пока требуют покадровой проверки.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M20

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужна подтверждённая Valkyrie и два и более противника в радиусе круговой melee-атаки.
- **Что опровергнет реализацию в Rudy:** Rudy поражает иной victim set либо наносит урон не на том кадре.
- **Чего сейчас не хватает:** Наличие группового боя само по себе не доказывает именно melee-splash Valkyrie.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M21

- **Кандидаты из разметки:** [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Подтвердить тип эффекта контроля и сравнить остановку движения/атаки, длительность и возобновление.
- **Что опровергнет реализацию в Rudy:** Rudy продолжает атаку во время реального stun, прерывает не то состояние или неверно выдерживает паузу.
- **Чего сейчас не хватает:** D06A содержит визуальный эффект, но stun не установлен: это слабый кандидат, не эталон.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M22

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07B 01:47–02:31](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view).
- **Что должно быть видно для подтверждения:** После подтверждённого stun найти смену цели при ещё живой предыдущей цели.
- **Что опровергнет реализацию в Rudy:** После stun Rudy неправильно удерживает или пересчитывает target.
- **Чего сейчас не хватает:** Нет наблюдаемой последовательности «lock → stun → новая цель».
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M23

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Искать stun, применённый к зарядке Sparky или ramp Inferno; сравнить reset.
- **Что опровергнет реализацию в Rudy:** Rudy сохраняет заряд/ступень, которые игра сбросила, или наоборот.
- **Чего сейчас не хватает:** В текущем каталоге нет нужной карты вместе с моментом stun/reset.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M24

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Нужен непрерывный луч Inferno Tower по прочному юниту и события урона по ступеням.
- **Что опровергнет реализацию в Rudy:** Rudy повышает damage в иные моменты или неправильно сбрасывает ramp.
- **Чего сейчас не хватает:** Оборонительное здание в кадре ещё не доказано как Inferno; фаза ramp не выделена.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M25

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Нужен луч Inferno, уже захвативший Hog перед его AIRBORNE; измерить сохранение lock/ramp.
- **Что опровергнет реализацию в Rudy:** Rudy разрывает/сохраняет захват не так, как игра в момент прыжка.
- **Чего сейчас не хватает:** Требуемого сочетания нет среди установленных сцен.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M26

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужен Electro Wizard и 1/2/3 доступных противника; отметить оба bolt-target в одной атаке.
- **Что опровергнет реализацию в Rudy:** Rudy неверно разделяет удары, выбирает больше двух или не того второго адресата.
- **Чего сейчас не хватает:** Обычные групповые сцены без распознанного E-Wiz не являются M26.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M27

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужен Electro Dragon и цепочка из трёх расположенных на измеримых расстояниях целей.
- **Что опровергнет реализацию в Rudy:** Rudy перепрыгивает на недопустимую цель или нарушает последовательность цепи.
- **Чего сейчас не хватает:** По отобранным кадрам не установлена полная цепочка молний.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M28

- **Кандидаты из разметки:** [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Зафиксировать эффект удара/взрыва и координаты отброшенного юнита до/во время/после displacement.
- **Что опровергнет реализацию в Rudy:** Rudy не отбрасывает юнита либо иначе перепрокладывает путь.
- **Чего сейчас не хватает:** D06C и D10B — лишь визуальные кандидаты: подтверждение knockback и идентичности карты обязательно.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M29

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужен Prince/Battle Ram с достаточно длинным разбегом, явным CHARGE_STARTED и попаданием.
- **Что опровергнет реализацию в Rudy:** Rudy включает заряд слишком рано/поздно либо выдаёт неверную скорость/урон.
- **Чего сейчас не хватает:** Быстрое движение в толпе без распознанной charge-анимации не подходит.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M30

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Нужен заряженный Prince/Battle Ram, которого оглушают до удара, и повторный набор charge.
- **Что опровергнет реализацию в Rudy:** Rudy не сбрасывает charge или сбрасывает его в другом тике.
- **Чего сейчас не хватает:** Не обнаружена такая последовательность.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M31

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D07B 01:47–02:31](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view).
- **Что должно быть видно для подтверждения:** Нужна Bandit: windup → dash → impact с начальной и конечной позицией.
- **Что опровергнет реализацию в Rudy:** Rudy отличается фазой, длительностью или окном уязвимости рывка.
- **Чего сейчас не хватает:** Нет установленного dash-эпизода.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M32

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view).
- **Что должно быть видно для подтверждения:** Нужно здание, прожившее без вражеских атак до естественного исчезновения, с видимым HP.
- **Что опровергнет реализацию в Rudy:** Rudy рассчитывает иное HP(t) или tick естественной смерти.
- **Чего сейчас не хватает:** Имеющиеся здания участвуют в защите; чистая lifetime/decay запись не выделена.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M33

- **Кандидаты из разметки:** [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view).
- **Что должно быть видно для подтверждения:** Выделить убийство Balloon/Golem/Tombstone и последовательность взрыв/спавн/появление потомков.
- **Что опровергнет реализацию в Rudy:** Rudy пропускает эффект, вызывает его преждевременно или создаёт неверное число потомков.
- **Чего сейчас не хватает:** D09B — очень слабый кандидат: не подтверждены карта, тип эффекта и причина исчезновения.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M34

- **Кандидаты из разметки:** [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04B 02:27–03:11](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05A 00:35–01:07](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07C 02:55–03:22](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10C 04:08–04:48](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** По кадрам непосредственно после постановки зафиксировать число и стартовые центры группы.
- **Что опровергнет реализацию в Rudy:** Rudy создаёт неверное число существ, в другой формации или зеркалировании.
- **Чего сейчас не хватает:** Увиденная группа могла уже двигаться; обязательно найти кадр первого появления.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M35

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view).
- **Что должно быть видно для подтверждения:** Нужна подтверждённая Magic Archer: прямой луч, юнит на линии и башня позади.
- **Что опровергнет реализацию в Rudy:** Rudy пропускает второго пострадавшего либо поражает объект вне линии.
- **Чего сейчас не хватает:** Ни один эпизод пока не показывает распознанную стрелу с линейным пробитием.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M36

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужен подтверждённый Hunter на известном расстоянии, видимый выстрел дробью и HP цели.
- **Что опровергнет реализацию в Rudy:** Rudy неверно рассчитывает число попавших дробинок и суммарный урон.
- **Чего сейчас не хватает:** Дальний бой не доказывает Scatter без распознавания Hunter.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M37

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view).
- **Что должно быть видно для подтверждения:** Нужна Firecracker/Sparky с x/y непосредственно до и после выстрела, исключая вражеский knockback.
- **Что опровергнет реализацию в Rudy:** Rudy не смещает самого стрелка или неверно изменяет последующие range/target.
- **Чего сейчас не хватает:** По визуальным срезам самоотдача стрелка не подтверждена.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

#### M38

- **Кандидаты из разметки:** [D01A 00:52–01:34](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D01B 02:55–03:54](https://drive.google.com/file/d/1TkU2iq2NXiYZFb58ZlveMtFPb6aIYleu/view); [D02A 00:44–01:35](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D02B 02:25–03:11](https://drive.google.com/file/d/1sXGnsMlYdYdz4VqRyUeVC55Ztq1IV82p/view); [D03A 00:45–01:15](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D03C 02:43–03:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D04B 02:27–03:11](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D05C 03:17–04:03](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06A 00:40–01:19](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D06C 03:04–04:18](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D07A 00:39–01:18](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07B 01:47–02:31](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D07C 02:55–03:22](https://drive.google.com/file/d/1s4CJ4xY8NKCfToJtTOAEki0vamlU49BB/view); [D08A 00:30–01:08](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D08B 01:29–02:19](https://drive.google.com/file/d/1Cy-uUzDOXpePRALHJzRgNeqBWkIgEjlT/view); [D09A 00:33–01:18](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D09B 02:09–02:59](https://drive.google.com/file/d/1KjPey598lFMpFAePFULRRY73Ou5h6gbY/view); [D10A 00:38–01:23](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view); [D10C 04:08–04:48](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Для башни восстановить очередность целей, момент first lock, выстрелы и перескок после смерти.
- **Что опровергнет реализацию в Rudy:** Rudy стреляет в иного юнита, нарушает lock или преждевременно активирует King Tower.
- **Чего сейчас не хватает:** В сценах с несколькими врагами разбирать по кадрам; изменение HP само по себе недостаточно.
- **Статус:** `CANDIDATE`; `VERIFIED` **не присвоен**.

#### M39

- **Прямых подтверждённых эпизодов в первичном каталоге нет.**
- **Смежные сцены для дополнительного поиска (не доказательство):** [D03B 01:44–02:25](https://drive.google.com/file/d/1QP7v1xzbeIDAV2XD2Y7tHw4O8kRdLkwL/view); [D04A 00:50–01:31](https://drive.google.com/file/d/1Wkot-lWMORihFnGmPVll-C0Kc_CTTGqG/view); [D05B 02:17–02:41](https://drive.google.com/file/d/1mMcM9Wj9avIZtjHztwvPKA0wIveVYP-h/view); [D06B 01:47–02:36](https://drive.google.com/file/d/1rRkzCrq_Gqe5JZ928pVC07fQNq9_dueq/view); [D10B 02:26–03:26](https://drive.google.com/file/d/1jfPQD8IT6D447q-NK2V-7WfMue7yPfzc/view).
- **Что должно быть видно для подтверждения:** Нужна Cannon/Hog постановка в соседних тиках около границы aggro и факт PULL/NO_PULL.
- **Что опровергнет реализацию в Rudy:** Rudy считает здание доступным для захвата раньше/позже реального момента активации.
- **Чего сейчас не хватает:** Случайные постановки из матчей не являются контролируемым временным sweep ±50 мс.
- **Статус:** `NO_DIRECT_REFERENCE`; `VERIFIED` **не присвоен**.

### 12.3. Очерёдность превращения кандидатов в physical gates

1. **В первую очередь:** D08B → M14/M15/M38 (атака Princess/King Tower); D06B и D04A → M01/M02/M38 (оборона зданием и движение); D02A и D09A → M16 (выстрел/попадание). На этих клипах легче проверить синхронизацию и первую ошибку Rudy.
2. **Во вторую:** D05A, D05C, D06C, D10B, D10C → M13/M19/M28/M34 (группы/AoE/возможное отбрасывание) только после распознавания карт и фильтра специальных эффектов.
3. **Затем:** D01B, D03C, D07B, D07C → M09/M38 (смерть цели, удержание и переключение); требуется непрерывная покадровая история `target_uid`.
4. **Отдельные управляемые тесты остаются обязательны:** M03–M08, M10–M12, M17–M18, M20–M27, M29–M32, M35–M37, M39, если при полном пересмотре не найдутся необходимые уникальные условия. Не заменять серию timing/cell sweeps единичным удачным кадром.
5. Для каждой принятой сцены подготовить `physical_tests/references/<id>.json`, источник кадров, `placements[]`, `observations[]`, уровень/вариант карты, `CLEAN|AFFECTED|UNKNOWN`, и сравнить trace Rudy с реально аннотированными наблюдениями. Не высчитывать authoritative Rust trace задним числом в Python.

### 12.4. Что *не* означает покрытие

- Увиденная стрельба не является тестом M17 (изменённая цель после release) или M18 (смерть стрелка до impact).
- Группа на экране не доказывает M20 (Valkyrie splash), M26 (два луча E-Wiz), M27 (цепная молния), M34 (начальная формация) или M36 (дробь Hunter).
- Здание на экране не доказывает M10/M39: нужны подтверждённые Hog/Cannon и sweep положения или timing с фиксацией PULL/NO_PULL; не доказывает M32 без полного естественного lifetime.
- Визуальный эффект может быть Evo/hero, stun, splash или knockback; пока тип не распознан, не присваивать `clean` и не выводить урон или тайминги.
- `NO_DIRECT_REFERENCE` означает нехватку **подтверждённых** кадров в данном индексе, а не отсутствие реализации в Rust и не отсутствие события во всех 10 MP4.

<!-- CR_DEMO_COVERAGE_20261018_END -->
