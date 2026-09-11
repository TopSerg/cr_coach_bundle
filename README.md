# CR Coach Bundle

## Воспроизведение по постановкам

```powershell
powershell -ExecutionPolicy Bypass -File tools\rudy_windows\install_core_bundle.ps1 -Bundle .\hog-cannon-princess-core-win64-py3.12.zip
py simulate.py examples\hog_cannon_secondary.json --out outputs\secondary
```

Откройте `outputs/secondary/replay.html`. Вход — JSON/CSV: время, сторона, карта,
клетка. По умолчанию используется пропатченный Rudy: его ядро Хог + Пушка +
Princess Tower проходит строгие проверки по двум независимым видео и отдельному
эпизоду Хога против башни. Это ещё не означает точность всех карт Clash Royale.

Для портативного исследовательского backend без Rust используйте
`python setup_simulator.py`, затем добавьте `--engine crbot`. Он исполняет 109
обычных карт уровня 11 и поддерживает checkpoint, но не прошёл видеокалибровку.

[Инструкция](docs/REPLAY_SIMULATOR_RU.md) · [Аудит точности](docs/SIMULATOR_AUDIT_RU.md)

Набор исходников, документации и glue-кода для экспериментов с симуляцией и анализом боёв Clash Royale.

Подробное описание архитектуры и первого milestone находится в [README_START_HERE.md](README_START_HERE.md).

## Клонирование

Upstream-проекты подключены как Git submodules. Для нового клона используйте:

```bash
git clone --recurse-submodules https://github.com/TopSerg/cr_coach_bundle.git
cd cr_coach_bundle
```

Если репозиторий уже был клонирован без submodules:

```bash
git submodule update --init --recursive
```

## Обновление

Основной репозиторий фиксирует точные версии всех upstream-проектов. Чтобы восстановить именно зафиксированные версии:

```bash
git pull --ff-only
git submodule sync --recursive
git submodule update --init --recursive
```

Чтобы проверить доступность новых upstream-коммитов, используйте скрипт из корня проекта:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch_upstreams.ps1
```

После обновления submodules их новые commit IDs необходимо отдельно закоммитить в основном репозитории.

## Локальные данные

Модели, датасеты, бинарные файлы, виртуальные окружения, кэши и секреты исключены через `.gitignore`. Инструкции по тяжёлым зависимостям находятся в [docs/HEAVY_ASSETS.md](docs/HEAVY_ASSETS.md).
