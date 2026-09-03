# Starter glue code

Это не simulator. Это тонкий слой, который мы сохраняем своим независимо от выбранного upstream backend.

Canonical boundary:

```text
Replay source
  -> ReplayBattle / ReplayEvent
  -> coordinate + card + time adapters
  -> EngineAdapter
  -> state trace
  -> real-observation comparison
  -> first divergence
```

## CrBotEngineAdapter

Первый backend реализован в `cr_coach.engine.crbot.CrBotEngineAdapter` поверх pinned submodule `upstream/cr-bot`.

Ключевой timing contract: `cr-bot` считает `BattleState.tick` следующим physics tick. Поэтому replay actions буферизуются на текущем tick и передаются одним пакетом в `BattleEngine.step()` только при переходе на следующий tick. Это сохраняет штатный порядок `elixir/card cycle -> actions -> deploy -> targeting -> movement -> combat` и корректно поддерживает одновременные действия двух игроков.

Адаптер останавливает replay при:

- карте, которой нет в руке;
- повторном действии одного игрока в том же tick;
- `action_rejected` от cr-bot (`insufficient_elixir`, `illegal_placement`, ...);
- несовпадении timebase replay и simulator;
- ability activation, пока upstream cr-bot сам помечает abilities как unsupported.

### Unit tests без upstream

Из каталога `starter`:

```bash
python -m pytest tests
```

Тесты адаптера используют fake engine и не требуют инициализированного submodule.

### Первый настоящий smoke test

Из корня репозитория:

```bash
git submodule update --init upstream/cr-bot
python scripts/smoke_crbot_adapter.py
```

Smoke создаёт deterministic Hog 2.6 battle без shuffle, подаёт один canonical `ReplayEvent` с Hog Rider на tick 0 и проверяет, что после physics tick Hog действительно появился в authoritative state cr-bot.

## До первого full match

1. запустить настоящий adapter smoke;
2. coordinate calibration;
3. Hog isolated movement;
4. Cannon lifetime;
5. Hog/Cannon pull;
6. Musketeer/Ice Golem projectile timing;
7. только затем Hog 2.6 mirror.
