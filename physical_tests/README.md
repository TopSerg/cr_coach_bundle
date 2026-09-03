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

Никакие CV-модели, PyTorch или видео для этих тестов не нужны.

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

## Запуск только mechanics tests

```powershell
python physical_tests/test_04_hog_vs_tower.py
python physical_tests/test_05_hog_vs_cannon.py
```

В консоли будет короткое резюме, а подробный trace окажется в `outputs/physical_tests/`.

## Запуск всего набора

```powershell
powershell -ExecutionPolicy Bypass -File physical_tests/run_all.ps1
```

Ожидаемый итог:

```text
ALL PASS (5/5)
```

## Что это доказывает

Тесты 01–03 доказывают корректность нашего glue-layer.

Тесты 04–05 уже проверяют внутреннее поведение самого simulator: deployment, movement, targeting, tower damage и building pull.

Они всё ещё **не доказывают соответствие настоящему Clash Royale**. Следующий уровень — запустить ровно те же сценарии в реальном Friendly Battle, записать видео и сравнить полученные `hog_vs_*.json` с наблюдениями из видео.
