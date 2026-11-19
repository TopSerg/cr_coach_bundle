# Лаборатория двух Android-эмуляторов → Rudy

## Что работает, а что нет

Это лабораторный **MVP**, а не программа, автоматически восстанавливающая все скрытые механики Clash Royale. Обычный ADB предоставляет экран, команды ввода и системные журналы; он **не предоставляет** `target_uid`, `windup`, `shield_hp`, траектории снарядов и прочее authoritative состояние Clash Royale. Никакого доступа к памяти процесса, перехвата серверного протокола или модификации клиента здесь нет.

Сейчас поддерживаются:

- два указанных ADB serial (никаких `adb -d` и случайного выбора устройства);
- `screencap -p` с измеренным на хосте интервалом начала/окончания получения кадра; отдельно два `screenrecord` для визуальной проверки;
- контролируемый `play` (выбор слота и постановка) с `send_ns` и `ack_ns`; это **не доказательство**, что игра приняла действие;
- экспорт `replay.json` в существующий формат `simulate.py --engine rudy` (20 TPS, world cells);
- OCR HP башен по вручную измеренным прямоугольникам, фильтрация по confidence и повторению; при желании — кандидаты на координаты юнитов по собственным PNG-шаблонам, которые не признаются VERIFIED;
- генерация неполного физического эталона, сопоставление по допустимому временному интервалу с `snapshots.jsonl`, отчёт `FIRST_DIVERGENCE / PASS_OBSERVED / INCONCLUSIVE`;
- осторожное предложение калибровки скорости **только** по трём независимым вручную проверенным траекториям и создание **локальной** отдельной Git-ветки с поправкой `tools/rudy_windows/patch_rudy_troop_speed.py` после явного подтверждения.

Только `FIRST_DIVERGENCE` с достаточным подтверждением — повод поставить новый физический эксперимент. Несовпадение HP не позволяет автоматически выбрать между уроном, временем появления, частотой атак, ошибкой координат и ошибкой OCR. `PASS_OBSERVED` означает лишь совпадение использованных измерений, не статус `VERIFIED` для M01–M39.

## 1. Подготовка Windows

Использовать Python 3.11/3.12 и [Android SDK Platform Tools](https://developer.android.com/tools/adb). Подключить два эмулятора с Android Debug Bridge, проверить:

```powershell
adb devices -l
py -m emulator_lab devices
py -m unittest discover -s tests -p test_emulator_lab.py -v
```

Для распознавания изображений установить отдельный Tesseract OCR для Windows, затем:

```powershell
py -m pip install opencv-python pytesseract
```

Python-библиотека `pytesseract` не устанавливает сам движок `tesseract.exe`. При необходимости передать путь через `--tesseract C:\Program Files\Tesseract-OCR\tesseract.exe` (в кавычках).

Существующий Rudy должен быть установлен (`cr_engine` и `.rudy/data`) по инструкции `README.md`.

## 2. Калибровка **каждого** экрана

Скопировать `examples/emulator_lab_config.example.json` в собственный `outputs/lab-config.json`. Записать **фактические** ADB serial, измерить `arena_rect_px` как границы игрового поля 18×32 клетки на скриншоте *без нижнего HUD*, координаты центров четырёх карточных слотов в `hand_slots_px`; для `tower_hp_rois` измерить прямоугольники *только видимого числа HP*, проверить соответствие `owner` (0=team, 1=opponent), `role` (`left`, `right`, `king`) в canonical world — с точки зрения **team**. Соперник видит свою половину снизу: его `x/y` поворачиваются на 180°.

Полезно сделать пару PNG вручную: `adb -s emulator-5554 exec-out screencap -p > team.png` и отдельно для второго устройства (редирект бинарного потока в PowerShell 7; в Windows PowerShell 5.1 лучше пользоваться `py -m emulator_lab capture`). Для калибровки координат нельзя слепо копировать размеры из примера. В конце вручную установить `calibration_confirmed: true`; до этого `init` откажется запускаться.

`unit_templates` — необязательный массив вида `[{"path":"outputs/templates/hog_blue.png", "card_id":"hog-rider", "owner":0, "threshold":0.94, "max_candidates":2}]`; создавайте отдельные шаблоны для цвета/анимации/команды, иначе будут ложные срабатывания. Они выводятся только как `position_candidate`, не как истинное положение сущности.

## 3. Один управляемый микротест

Открыть два окна PowerShell. В первом:

```powershell
py -m emulator_lab init --config outputs/lab-config.json --session outputs/lab-001
py -m emulator_lab start --session outputs/lab-001
py -m emulator_lab capture --session outputs/lab-001 --seconds 35 --interval 0.25
```

Команду `start` отправлять при реальном начале боя. Для точности ±1 тик этого недостаточно: дополнительно выровнять начало по игровому таймеру (отдельная будущая калибровка HUD). Во втором окне во время захвата:

```powershell
py -m emulator_lab play --session outputs/lab-001 --side team --card hog-rider --slot 0 --x 3 --y 19
py -m emulator_lab play --session outputs/lab-001 --side opponent --card cannon --slot 2 --x 10 --y 10
```

`--slot` — текущий индекс карты в руке (0–3), **не индекс в колоде**. Координаты `--x --y` задаются в единой системе 18×32 со стороны `team`. Скрипт записывает *попытки отправки* tap. Проверить, что выбранная карта действительно была в руке, хватало эликсира и игра приняла постановку. Если нет — не использовать тест для физики.

Для дополнительного полного видео можно запустить вместо/параллельно (только один процесс screenrecord на устройство):

```powershell
py -m emulator_lab video --session outputs/lab-001 --seconds 35
```

MP4 сохраняются, **но время первого видео-кадра относительно хостового `start` не известно точно**. Их нельзя использовать как эталон 50 мс без HUD-синхронизации.

## 4. Снять эталон и прогнать Rudy

```powershell
py -m emulator_lab observe --session outputs/lab-001
py -m emulator_lab reference --session outputs/lab-001
py -m emulator_lab export --session outputs/lab-001 --duration 35
py simulate.py outputs/lab-001/replay.json --engine rudy --rudy-data .rudy/data --sample-ticks 1 --out outputs/lab-001/rudy
py -m emulator_lab compare --reference outputs/lab-001/reference.json --snapshots outputs/lab-001/rudy/snapshots.jsonl --out outputs/lab-001/visual_report.json
```

Или последнюю часть одним вызовом `py -m emulator_lab run --session outputs/lab-001 --rudy-data .rudy/data --out outputs/lab-001/replay_result --duration 35`.

Выход: `reference.json`, `replay.json`, `visual_report.json` и обычные Rudy `snapshots.jsonl`, `events.jsonl`, `replay.html`. `reference.json.snapshots` сохраняется совместимым с существующим P-1 unified validator, но для OCR правильнее использовать интервальный `compare`: точное совпадение миллисекунды нельзя гарантировать без синхронизации. Если эталона или покрытия нет, отчёт **INCONCLUSIVE**, а не ложный PASS.

## 5. Безопасная калибровка числового параметра Rudy

Для изолированного движения подготовить три независимых **вручную проверенных** траектории (`examples/emulator_speed_fit.example.json` показывает только формат, числа в нём демонстрационные). Снимать одинаковую категорию скорости, движение без моста/столкновений/смены цели/статусов. Затем:

```powershell
py -m emulator_lab fit-speed --experiments outputs/verified-speed.json --category fast --repo . --out outputs/speed-proposal.json
# изучить предложение, исходные видео и три эксперимента
py -m emulator_lab apply --proposal outputs/speed-proposal.json --repo . --branch calibration/fast-speed-001 --approve
```

`apply` требует **чистое рабочее дерево Git**, строго ограничен одной известной строкой в speed-патче, проверяет SHA исходника, создаёт **новую локальную ветку** и выполняет Python unit tests. Не пушит, не меняет main, не делает merge. Чтобы правка стала эффективной, надо **пересобрать Rudy из pinned Rust upstream с patch scripts**, прогнать P-1, M-gates, Hog/Cannon и другие физические regressions и сделать ревью отдельного PR. Python unit tests при `apply` **не заменяют** эту проверку. Для других подсистем сейчас выдаются гипотезы/диагностика; автоподбор таргетинга, коллизий, projectile и stun требует следующего этапа CV/микротестов.

## Ограничения и контроль качества

1. Оба аккаунта должны использовать один patch и согласованные уровни карт; текущий публичный `simulate.py` рассчитан на level 11.
2. Захват через `adb exec-out screencap` медленнее 20 TPS. Для precise hit/death timing нужны видео с HUD alignment или специальный high-fps capture, а не интерполяция между редкими кадрами.
3. Нельзя считать `target_uid`, `path waypoint` и причины попадания извлечёнными из одной картинки: это выход **Rudy**, а не Android.
4. Любые модели CV и шаблоны нужно проверять на независимых кадрах, а не на тех же, на которых их подгоняли.
5. Сохранить существующие M01–M39 и зелёные Hog/Cannon/Princess-тесты. Новую механику помечать VERIFIED только после physical gate и regression gate.
