# Physical adapter and mechanics tests

Это отдельные **ручные integration tests** нашего `ReplayEvent -> CrBotEngineAdapter -> cr-bot` пути и первых игровых механик.

Они запускают настоящий pinned `cr-bot` simulator, а не fake backend из unit tests.

## Быстрый запуск на Windows

Из корня репозитория:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File physical_tests/run_all.ps1
```

`run_all.ps1` при первом запуске автоматически создаёт lightweight checkout в `.physical_deps/cr-bot`. Материализуется только `simulator/` на зафиксированном commit `40ca2b16bc276fc982a3aa80c7415b24439cbd3c`.

Никакие CV-модели, PyTorch или видео для тестов 01–05 не нужны.

## Что проверяется

### 01 — `test_01_single_hog.py`
Проверяет сам путь `ReplayEvent -> adapter -> BattleEngine.step -> BattleState`.

### 02 — `test_02_same_tick_dual_hog.py`
Проверяет, что два действия на одном replay tick попадают в один physics tick.

### 03 — `test_03_hand_mismatch_stops.py`
Проверяет fail-closed поведение на невозможной карте в руке.

### 04 — `test_04_hog_vs_tower.py`

Это первый полноценный mechanics test. Hog ставится в canonical physical-lab cell `(3,20)`, после чего противник ничего не делает.

Проверяем, что Hog:

- проходит deployment;
- реально движется по арене;
- приобретает enemy tower как target;
- доходит до атаки;
- уменьшает HP башни.

Тест записывает каждые 250 ms:

```text
tick / time
hog x/y
hog HP
deploy timer
target UID
attack count
enemy tower HP
```

Плюс отдельно пишет target changes и момент первого урона башне.

Результат:

```text
outputs/physical_tests/hog_vs_tower.json
```

### 05 — `test_05_hog_vs_cannon.py`

Повторяет canonical `hog_cannon_probe` из upstream `cr-bot` physical lab:

```text
A: Hog @ cell (3,20), t=0
B: Cannon @ cell (8,13), когда Hog пересекает y=17000 mtile
```

Проверяем, что:

- Cannon реально появляется;
- Hog меняет target на Cannon;
- Hog отклоняется по X к центральной Cannon;
- Cannon получает урон от Hog.

Сохраняются trajectory/HP/targets обоих объектов каждые 250 ms и ключевые события взаимодействия.

Результат:

```text
outputs/physical_tests/hog_vs_cannon.json
```

### 06 — `test_06_hog_vs_cannon_demo_primary.py`

Первый **demo-grounded fidelity test**. Эталон взят из PRIMARY-клипа `d03_hog_cannon_02_PRIMARY_0089.5-0103.0.mp4` из Hog/Cannon debug pack.

Покадровая ручная разметка сохранена отдельно:

```text
physical_tests/references/d03_hog_cannon_02_primary.json
```

Относительно момента постановки Hog в демке получено:

```text
Cannon play        2.45 s
Hog hit #1         4.30 s
Hog hit #2         5.90 s
Hog hit #3         7.50 s
Cannon death       7.50 s
Hog death          8.70 s
```

Первые координаты, вручную перенесённые с видимой сетки 18×32:

```text
Hog    cell (9,18)
Cannon cell (9,10)
```

Тест повторяет этот timing в симуляторе, снимает `attack_count`, target, HP и смерти обоих объектов, после чего сравнивает времена с демкой и печатает `FIRST DIVERGENCE`. Допуск на первом проходе — ±0.10 s (два simulator ticks).

Результат:

```text
outputs/physical_tests/hog_vs_cannon_demo_primary.json
```

Этот тест намеренно **не включён в `run_all`**, пока мы калибруем геометрию и fidelity: его падение сейчас является полезным результатом, а не поломкой glue-layer.

Запуск:

```powershell
python physical_tests/test_06_hog_vs_cannon_demo_primary.py
```

## Запуск только mechanics tests

```powershell
python physical_tests/test_04_hog_vs_tower.py
python physical_tests/test_05_hog_vs_cannon.py
```

В консоли будет короткое резюме, а подробный trace окажется в `outputs/physical_tests/`.

## Запуск всего стабильного набора

```powershell
powershell -ExecutionPolicy Bypass -File physical_tests/run_all.ps1
```

Ожидаемый итог:

```text
ALL PASS (5/5)
```

## Что это доказывает

Тесты 01–03 доказывают корректность нашего glue-layer.

Тесты 04–05 проверяют внутреннее поведение самого simulator: deployment, movement, targeting, tower damage и building pull.

Тест 06 — уже следующий уровень: он сравнивает simulator с реальным Clash Royale по конкретной Hog↔Cannon демке и должен показывать первый момент расхождения по timing. До калибровки он может и должен падать, если симуляция выходит за допуск.
