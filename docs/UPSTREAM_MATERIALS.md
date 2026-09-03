# Upstream materials map

## Tier 0 — нужны для первого теста

### Keschler/cr-bot
Repo: https://github.com/Keschler/cr-bot

Используем как reference implementation и test lab.

Приоритетные участки:

- `simulator/state.py` — authoritative `BattleState`.
- `simulator/engine/core.py` — `BattleEngine` composition.
- `simulator/engine/_base.py`
- `simulator/engine/deployment.py`
- `simulator/engine/targeting.py`
- `simulator/engine/movement.py`
- `simulator/engine/collision.py`
- `simulator/engine/combat.py`
- `simulator/engine/deaths.py`
- `simulator/engine/match.py`
- `simulator/engine/scheduler.py`
- `simulator/engine/abilities.py`
- `simulator/actions.py`
- `simulator/events.py`
- `simulator/ruleset.py`
- `simulator/rulesets/` — versioned card/mechanic definitions.
- `simulator/observation.py` — authoritative → public observation.
- `simulator/observation_v2_adapter.py`
- `simulator/env.py`
- `simulator/fidelity.py`
- `simulator/validation.py`
- `simulator/physical_lab/replay.py`
- `simulator/physical_lab/campaign.py`
- `simulator/physical_lab/`
- `src/cr_bot/features/action_space.py` — 18×32 grid and screen/cell mapping.
- `src/cr_bot/replay/cache.py`
- `src/cr_bot/vision/`
- `src/cr_bot/trackers/`

Проверенный факт: код разделяет authoritative simulator state и public observation; physical lab ориентирован на first-divergence comparison.

### cochon123/clash-royale-ai
Repo: https://github.com/cochon123/clash-royale-ai

Приоритетные файлы:

- `src/cr_replay_pipeline/parser.py` — replay payload → card/ability events.
- `src/cr_replay_pipeline/models.py`
- `src/cr_replay_pipeline/hand_tracker.py` — перебор 8! стартовых очередей и hand posterior.
- `src/cr_replay_pipeline/policy_dataset.py`
- `src/cr_replay_pipeline/winner_dataset.py`
- `src/cr_replay_pipeline/metadata.py`
- `src/cr_replay_pipeline/cleaner.py`

Replay raw ticks сохраняются, секунды вычисляются как `ticks / 20`.

### wty-yy/KataCR
Repo: https://github.com/wty-yy/KataCR

Используем как CV dependency/reference. `cr-bot` уже содержит patched KataCR как submodule path `vendor/external/KataCR`.

## Tier 1 — fidelity и fast simulation

### nguiaSoren/clash-royale-suite
Repo: https://github.com/nguiaSoren/clash-royale-suite

Нужная часть: `cr-rudy-sim/`.

Ключевые файлы:

- `cr-rudy-sim/simulator/engine/src/lib.rs`
- `game_state.rs`
- `entities.rs`
- `engine.rs`
- `combat.rs`
- `data_types.rs`
- `evo_system.rs`
- `hero_system.rs`
- `champion_system.rs`
- `cr-rudy-sim/simulator/python/match_runner.py`
- `replay_recorder.py`

Особенно важное: `GameState` клонируемый; движок использует integer state и 20 TPS. Это кандидат для массовых counterfactual rollouts после parity с reference engine.

### voonhous/crforge
Repo: https://github.com/voonhous/crforge

Не импортируем в production сначала. Используем как вторую независимую реализацию и документацию.

Читать в первую очередь:

- `docs/architecture.md`
- `docs/arena-and-match.md`
- `docs/combat.md`
- `docs/secret_stats.md`
- `docs/schema.md`

## Tier 2 — независимые cross-checks

### max-miller1204/Clash-Royale-Pod
Repo: https://github.com/max-miller1204/Clash-Royale-Pod

Нужен для независимого video analyzer / EV pipeline. Проект использует YOLO/OpenCV/OCR и имеет video-oriented анализ, но часть trained weights может требовать отдельного получения.

### RoyaleAPI/cr-api-data
Repo: https://github.com/RoyaleAPI/cr-api-data
Hosted data: https://royaleapi.github.io/cr-api-data/

Минимальный endpoint:
- `https://royaleapi.github.io/cr-api-data/json/cards.json`

Дополнительно после clone изучить stats JSON в docs/build output.

### smlbiobot/cr-csv
Repo: https://github.com/smlbiobot/cr-csv

Исторические Clash Royale CSV. Нужны как дополнительный источник raw/internal parameters и naming.

## Tier 3 — археология/private-server references

- https://github.com/Greedycell/AstralRoyaleLegacy
- https://github.com/retroroyale/ClashRoyale

Использовать для battle protocol, message formats, coordinate/protocol archaeology. Не считать современной combat truth.

## Дополнительные simulator/bot references

- https://github.com/Jason-XII/clash-royale-simulator
- https://github.com/samdickson22/clash-simulator
- https://github.com/krazyness/CRBot-public

Они не входят в mainline архитектуру, но полезны для сравнения простых реализаций и RL interfaces.
