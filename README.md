# CR Coach Bundle

## Воспроизведение по постановкам

```shell
python setup_simulator.py
python simulate.py examples/hog_cannon_primary.json --out outputs/primary
```

Откройте `outputs/primary/replay.html`. Вход — JSON/CSV: время, сторона, карта, клетка.
109 обычных карт уровня 11, журнал событий и продолжение из checkpoint.
Совпадение с реальной игрой пока не подтверждено.

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
