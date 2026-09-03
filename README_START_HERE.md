# CR Coach — bootstrap bundle

Цель: перейти от обсуждения к первому differential test реального Clash Royale против headless simulator.

## Основная архитектура

1. `Keschler/cr-bot` — reference simulator, video/CV pipeline, public-state boundary, fidelity/physical-lab infrastructure.
2. `cochon123/clash-royale-ai` — replay ingestion: `card / tick / x / y`, battle metadata, exact/ probabilistic hand reconstruction, BC/value baselines.
3. `wty-yy/KataCR` — основной CV dependency для battlefield detection.
4. `nguiaSoren/clash-royale-suite` (`cr-rudy-sim`) — будущий fast backend для большого числа cloned counterfactual rollouts.
5. `voonhous/crforge` — независимый reference по физике/targeting/pathfinding/secret stats.
6. `max-miller1204/Clash-Royale-Pod` — независимый video-analysis cross-check.
7. `RoyaleAPI/cr-api-data` и `smlbiobot/cr-csv` — статические и reverse-engineered game data.
8. Старые private-server реализации — только для протокола/форматов/археологии.

## Что делать первым

### 1. Подтянуть upstream
Linux/macOS:

```bash
bash scripts/fetch_upstreams.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch_upstreams.ps1
```

### 2. Не скачивать огромные датасеты сразу
Сначала достаточно `cr-bot`, `clash-royale-ai`, `KataCR` и `cr-api-data`.
Тяжёлые модели/датасеты вынесены в `scripts/fetch_heavy_assets.sh`.

### 3. Первый milestone

**Controlled Hog vs Cannon**:

- Friendly Battle, Level 11.
- Фиксированный deck/order, если режим позволяет.
- Известные логические действия и клетки.
- Screen recording реальной игры.
- Те же действия подаются в reference simulator.
- CV используется только для наблюдений реального мира, а не как источник действий.
- Выход: `divergence.json` с первым meaningful divergence.

### 4. После micro-tests

Hog 2.6 mirror → replay corpus → `(S_t, A_t, result)` → Policy → Value → counterfactual evaluation.

## Важное ограничение этого архива

Среда, в которой этот bundle был собран, не имеет прямого outbound/DNS доступа для `git clone`, поэтому полные snapshots upstream-репозиториев физически не удалось вложить в ZIP. Все репозитории были проверены публично 2026-09-03, а архив содержит воспроизводимые скрипты загрузки, точные URL, карту нужных исходников и starter glue-code.

См. `docs/FETCH_STATUS.md`.
