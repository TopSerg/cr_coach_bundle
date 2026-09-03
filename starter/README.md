# Starter glue code

Это не simulator. Это тонкий слой, который мы должны сохранить своим независимо от выбранного upstream backend.

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

## Первый adapter для cr-bot

После загрузки `upstream/cr-bot` создать `CrBotEngineAdapter`, который реализует `cr_coach.engine.protocol.EngineAdapter` поверх `simulator.engine.BattleEngine`.

Не продолжать replay после illegal card, hand mismatch, insufficient elixir или illegal placement: это уже divergence.

## До первого full match

1. coordinate calibration;
2. Hog isolated movement;
3. Cannon lifetime;
4. Hog/Cannon pull;
5. Musketeer/Ice Golem projectile timing;
6. только затем Hog 2.6 mirror.
