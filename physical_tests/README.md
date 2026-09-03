# Physical adapter tests

Это отдельные **ручные integration tests** нашего `ReplayEvent -> CrBotEngineAdapter -> upstream/cr-bot` пути.

Они запускают настоящий pinned `upstream/cr-bot`, а не fake backend из unit tests.

## Быстрый запуск на Windows

Из корня репозитория:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File physical_tests/run_all.ps1
```

`run_all.ps1` сам инициализирует `upstream/cr-bot`, если submodule ещё не загружен.

Либо вручную:

```powershell
git submodule update --init upstream/cr-bot
python physical_tests/run_all.py
```

Никакие CV-модели, PyTorch или видео для этих тестов не нужны.

## Что проверяется

### 01 — `test_01_single_hog.py`

Проверяет полный положительный путь:

```text
ReplayEvent(Hog, tick=0, x=3500, y=20500)
    -> ReplayGridAdapter -> cell (3, 20)
    -> CrBotEngineAdapter
    -> PlayCardAction
    -> BattleEngine.step()
    -> authoritative BattleState
```

PASS означает:

- действие реально прошло через `cr-bot`;
- simulator продвинулся с tick 0 до tick 1;
- появился `hog-rider` владельца 0;
- Hog заспавнился в `(3500, 20500)`;
- карта ушла из текущей руки.

### 02 — `test_02_same_tick_dual_hog.py`

Оба игрока ставят Hog на **одном и том же replay tick 0**.

PASS означает, что адаптер не сделал два последовательных physics ticks, а правильно собрал оба действия и передал их вместе в один `BattleEngine.step()`.

Проверяется:

- два Hog в state;
- owners `[0, 1]`;
- у обоих `spawn_tick == 0`;
- final simulator tick всё ещё `1`.

Это важная проверка синхронизации реального replay event stream.

### 03 — `test_03_hand_mismatch_stops.py`

Намеренно пытается сыграть `fireball` на tick 0, хотя deterministic Hog 2.6 opening hand содержит:

```text
hog-rider
cannon
musketeer
skeletons
```

Правильный результат — **ошибка** `card_not_in_hand`.

Тест считается PASS, если реконструкция остановилась на tick 0. Это доказывает, что мы не продолжаем replay после уже обнаруженного расхождения.

## Ожидаемый итог

В конце должно быть:

```text
ALL PASS (3/3)
```

Если какой-то тест падает, запускайте его отдельно:

```powershell
python physical_tests/test_01_single_hog.py
python physical_tests/test_02_same_tick_dual_hog.py
python physical_tests/test_03_hand_mismatch_stops.py
```

Каждый положительный тест печатает часть настоящего authoritative simulator state, поэтому можно глазами проверить hand, elixir, координаты и сущности.

## Что эти тесты пока НЕ доказывают

Они доказывают корректность нашего glue-layer, но **не доказывают соответствие симулятора настоящему Clash Royale**.

Следующий физический уровень проверки — controlled real-game experiment:

```text
реальный Hog placement + screen recording
                vs
тот же placement через этот adapter в cr-bot
```

и сравнение trajectory / target / hit timing / tower HP.
