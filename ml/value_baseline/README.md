# Replay-only Value baseline

This is the first ML baseline for CR Coach. It learns

`ordered replay history (card, side, time, x, y + deck metadata) -> P(team wins)`

without running the Clash Royale simulator.

The raw replay parser and feature encoder are reused from the pinned
`cochon123/clash-royale-ai` checkout. CR Coach owns the actual Value Transformer
and the training/evaluation wrapper in `train_value.py`.

## Why prefixes matter

A full-game winner classifier is not enough for coaching. The default training
set samples each battle at 25%, 50%, 75%, 90%, and 100% of its observed action
sequence. The report evaluates the same five points separately.

## GitHub Actions smoke run

Workflow: `.github/workflows/value-baseline-train.yml`

The push/PR smoke configuration downloads a deterministic subset of 800 raw
RoyaleAPI replays from `Cochon123/clash-royale-replays`, trains for 3 CPU epochs,
and uploads `value_transformer.pt`, `report.json`, `vocab.json`, and `SUMMARY.md`.

The smoke run validates the full pipeline; it is not intended to be the final model.

## Full / local run

In GitHub Actions choose `full`, or locally run:

```bash
python ml/value_baseline/train_value.py \
  --max-files 0 \
  --epochs 20 \
  --d-model 160 \
  --layers 4 \
  --batch-size 128 \
  --device cuda
```

`--max-files 0` means the full raw corpus. A future self-hosted runner uses the
same training script; only the runner/device settings change.

## Important limitation

The output is an observational Value estimate from replay history. A drop in
`P(win)` after a play is a useful coaching signal, but is not yet a causal
counterfactual score. The simulator/world-model remains the later component for
answering what would have happened after a different action.
