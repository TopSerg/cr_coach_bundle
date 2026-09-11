# Симулятор по списку постановок

Один формат JSON/CSV работает с двумя backend. По умолчанию выбран Rudy — на
нём проходит видеопроверенный milestone Хог + Пушка + Princess Tower. cr-bot
оставлен как портативный исследовательский backend для широкого набора карт.

| Backend | Запуск | Подтверждено | Ограничения |
|---|---|---|---|
| `rudy` | `python simulate.py input.json --out outputs/run` | Solo Hog и два чистых Хог–Пушка эпизода с допуском 0,10 с | Готовая сборка Windows x64/Python 3.12; нет checkpoint; остальные карты не верифицированы |
| `crbot` | `python simulate.py input.json --engine crbot --out outputs/run` | Детерминизм, 109 исполняемых карт, checkpoint | Нет подтверждённой точности относительно видео |

## Установка Rudy на Windows

Скачайте artifact `hog-cannon-princess-core-win64-py3.12.zip` из успешного
workflow `Build Hog Cannon Core Windows Bundle`, затем выполните из корня
репозитория:

```powershell
powershell -ExecutionPolicy Bypass -File tools\rudy_windows\install_core_bundle.ps1 `
  -Bundle .\hog-cannon-princess-core-win64-py3.12.zip
py simulate.py examples\hog_cannon_secondary.json --out outputs\secondary
```

Скрипт устанавливает wheel и размещает Tournament-11 overlay в `.rudy/data`.
Откройте `outputs/secondary/replay.html`: это автономный просмотр с паузой,
перемоткой, скоростью, координатами, HP, снарядами и текущими целями.

## Портативный cr-bot

Python 3.11+ и Git; Rust, maturin, CV-модель и GPU не требуются:

```shell
python setup_simulator.py
python simulate.py examples/hog_cannon_primary.json --engine crbot --out outputs/primary
```

Setup получает закреплённый backend в `.physical_deps/cr-bot` либо использует
submodule. Допустим `CRBOT_PATH` на checkout той же версии. Изменённый backend
отклоняется, чтобы отчёт не содержал ложный commit ID.

## Входной файл

Минимальный JSON:

```json
{
  "duration_s": 13,
  "events": [
    {"time": 0, "side": "team", "card": "hog-rider", "x": 14, "y": 17},
    {"time": 2.90, "side": "opponent", "card": "cannon", "x": 10, "y": 10}
  ]
}
```

CSV использует заголовок `time,side,card,x,y`. Примеры запуска:

```shell
python simulate.py my_battle.json --out outputs/my_battle
python simulate.py examples/placements.csv --duration 30 --out outputs/csv
python simulate.py --cards
python simulate.py --engine crbot --cards
```

- `time` — секунды от начала моделируемого фрагмента, а не таймкод видео или
  обратный таймер. Альтернатива — целочисленный `tick`.
- Физика работает с частотой 20 Гц; время должно делиться на 0,05 с без
  скрытого округления.
- `x`: 0…17 слева направо, `y`: 0…31 сверху вниз; координата означает центр
  клетки в общей мировой системе.
- `coordinate_system: "player_cells"` поворачивает обе оси для opponent:
  `(17-x, 31-y)`.
- `coordinate_system: "world_mtile"` принимает центры клеток в milli-tile,
  например `(14500, 17500)`.
- Действия разных сторон допустимы в один тик. Два действия одной стороны в
  один тик отклоняются.
- `duration_s` — абсолютный горизонт. Он автоматически включает один physics
  tick после последней постановки.
- `--sample-ticks 2` меняет только частоту записи снимков, не физику.
- Поддерживается только уровень 11 и закреплённый баланс.

## Режимы

| Режим | Что задаётся | Что проверяется |
|---|---|---|
| `placements` | Уже принятые игрой постановки | Время, карта, сторона, клетка и дальнейшая физика; рука и эликсир неизвестны |
| `match` | Постановки плюс две колоды/очереди | Дополнительно рука, цикл, эликсир и отказ незаконного действия |

В `match` укажите `team_deck` и `opponent_deck` — по восемь уникальных ID.
Первые четыре карты образуют начальную руку. `team_initial_queue` и
`opponent_initial_queue` могут задать иную перестановку тех же колод.

## Результаты

| Файл | Назначение |
|---|---|
| `replay.html` | Автономный интерактивный просмотр |
| `snapshots.jsonl` | Авторитетные состояния по одному JSON на строку |
| `events.jsonl` | Постановки, цели, атаки, урон и смерти |
| `report.json` | Статус, backend, версии, hash и область подтверждённой точности |
| `checkpoint.json` | Возобновляемое состояние cr-bot; для Rudy содержит `resumable=false` |

Снимок `tick=N` — состояние до действий N. Событие `tick=N` становится видно в
`state_tick=N+1`. `horizon_reached` означает достижение заданного времени,
`terminal` — естественное окончание боя, `failed` — отклонённое действие или
ошибку runtime. В последнем случае CLI возвращает код 2.

Поле `fidelity` задаёт область утверждения. У Rudy значение
`validated_hog_cannon_princess_core` относится только к проверенному ядру, а не
ко всем картам. У cr-bot остаётся `unverified_against_real_game`.

## Продолжение (только cr-bot)

```json
{
  "mode": "placements",
  "initial_state": "outputs/primary/checkpoint.json",
  "duration_s": 30,
  "events": [
    {"time": 14, "side": "team", "card": "valkyrie", "x": 4, "y": 19}
  ]
}
```

Времена и горизонт остаются абсолютными. Продолжение сохраняйте в другую
папку. Проверяются backend, ruleset, physics profile и hash состояния.

## Проверки

```shell
python -m pytest starter/tests tools/cr_hog_fidelity_test/tests -q
```

Строгая Rudy-проверка всех откалиброванных эпизодов запускается workflow
`.github/workflows/rudy-primary-pathing.yml`. На Windows с установленным wheel:

```powershell
powershell -ExecutionPolicy Bypass -File tools\cr_hog_fidelity_test\run_regressions_local.ps1
```

`compare_demo.py` остаётся диагностикой cr-bot и намеренно не выдаёт её за
Rudy-проверку.
