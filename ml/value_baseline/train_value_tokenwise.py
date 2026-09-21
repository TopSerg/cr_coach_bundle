from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from huggingface_hub import HfApi, snapshot_download
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

DATASET_REPO = "Cochon123/clash-royale-replays"


def download_replays(root: Path, max_files: int) -> dict[str, int]:
    root.mkdir(parents=True, exist_ok=True)
    files = sorted(
        p for p in HfApi().list_repo_files(DATASET_REPO, repo_type="dataset")
        if p.startswith("raw/") and p.endswith(".json")
    )
    chosen = files if max_files <= 0 else files[:max_files]
    snapshot_download(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        local_dir=str(root),
        allow_patterns=[*chosen, "card_costs.json"],
        max_workers=min(8, max(2, os.cpu_count() or 2)),
    )
    downloaded = sum(1 for _ in (root / "raw").rglob("*.json"))
    return {"available": len(files), "requested": len(chosen), "downloaded": downloaded}


def auc(labels: np.ndarray, probs: np.ndarray) -> float:
    labels = labels.astype(np.int64)
    if not len(labels) or labels.min() == labels.max():
        return 0.5
    order = np.argsort(probs)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(probs) + 1)
    pos = labels == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def deck_ids(deck, vocab):
    ids = [vocab.encode(card) for card in deck]
    while len(ids) < 8:
        ids.append(vocab.pad_id)
    return torch.tensor(ids[:8], dtype=torch.long)


class TokenwiseBattleDataset(Dataset):
    """
    One dataset item = one battle.
    Each token represents the state immediately after one event.
    Loss is applied only on card_play tokens. _encode_prefix is used only while
    materializing the dataset so each token is constructed without future leakage.
    Training then needs one Transformer pass per battle instead of one pass per prefix.
    """
    def __init__(
        self, battles, vocab, costs, encode_prefix, augment_swap=False,
        min_events=8, max_seq_length=180, seed=42,
    ):
        self.items = []
        rng = np.random.default_rng(seed)
        for battle in battles:
            self._append_battle(
                battle, vocab, costs, encode_prefix, False, min_events, max_seq_length
            )
            if augment_swap and float(rng.random()) < 0.7:
                self._append_battle(
                    battle, vocab, costs, encode_prefix, True, min_events, max_seq_length
                )

    def _append_battle(
        self, battle, vocab, costs, encode_prefix, swap,
        min_events, max_seq_length,
    ):
        continuous = []
        cards = []
        globals_seq = []
        supervise = []
        progress = []
        meta = []

        n_events = min(len(battle.events), max_seq_length)
        total_card_plays = sum(
            1 for e in battle.events[:n_events] if e.get("event_type") == "card_play"
        )
        seen_card_plays = 0

        for idx, event in enumerate(battle.events[:n_events], start=1):
            if event.get("event_type") == "card_play":
                seen_card_plays += 1
            if idx < min_events:
                continue

            encoded = encode_prefix(battle, idx, vocab, costs, swap_sides=swap)
            if encoded is None:
                continue
            cont, card_seq, _, _, global_feat, label = encoded

            continuous.append(cont[-1])
            cards.append(card_seq[-1])
            globals_seq.append(global_feat)
            supervise.append(event.get("event_type") == "card_play")
            progress.append(seen_card_plays / max(total_card_plays, 1))
            meta.append({
                "event_index": idx,
                "seconds": float(event["seconds"]),
                "event_type": event["event_type"],
                "card": event["card"],
                "side": (
                    ("team" if event["side"] == "opponent" else "opponent")
                    if swap else event["side"]
                ),
                "x": int(event["x"]),
                "y": int(event["y"]),
            })

        if not continuous or not any(supervise):
            return

        label = battle.team_wins if not swap else 1 - battle.team_wins
        team_deck = battle.team_deck if not swap else battle.opponent_deck
        opp_deck = battle.opponent_deck if not swap else battle.team_deck
        self.items.append({
            "continuous": torch.stack(continuous),
            "cards": torch.stack(cards),
            "globals": torch.stack(globals_seq),
            "team_deck": deck_ids(team_deck, vocab),
            "opp_deck": deck_ids(opp_deck, vocab),
            "supervise": torch.tensor(supervise, dtype=torch.bool),
            "progress": torch.tensor(progress, dtype=torch.float32),
            "label": int(label),
            "battle_id": battle.battle_id,
            "meta": meta,
            "swapped": bool(swap),
        })

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


def collate_tokenwise(batch):
    continuous = pad_sequence(
        [x["continuous"] for x in batch], batch_first=True, padding_value=0.0
    )
    cards = pad_sequence(
        [x["cards"] for x in batch], batch_first=True, padding_value=0
    )
    globals_seq = pad_sequence(
        [x["globals"] for x in batch], batch_first=True, padding_value=0.0
    )
    supervise = pad_sequence(
        [x["supervise"] for x in batch], batch_first=True, padding_value=False
    )
    progress = pad_sequence(
        [x["progress"] for x in batch], batch_first=True, padding_value=0.0
    )
    lengths = torch.tensor([x["continuous"].shape[0] for x in batch], dtype=torch.long)
    labels = torch.tensor([x["label"] for x in batch], dtype=torch.long)
    return (
        continuous,
        cards,
        torch.stack([x["team_deck"] for x in batch]),
        torch.stack([x["opp_deck"] for x in batch]),
        globals_seq,
        supervise,
        progress,
        labels,
        lengths,
    )


class TokenwiseValueTransformer(nn.Module):
    def __init__(
        self, vocab_size, continuous_dim, global_dim,
        d_model=96, layers=2, heads=4, dropout=0.15,
    ):
        super().__init__()
        if d_model % heads:
            raise ValueError("d_model must be divisible by heads")
        card_dim = 48
        self.cards = nn.Embedding(vocab_size, card_dim, padding_idx=0)
        self.event_in = nn.Sequential(
            nn.Linear(card_dim + continuous_dim, d_model),
            nn.LayerNorm(d_model),
            nn.GELU(),
        )
        self.pos = nn.Embedding(256, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=heads,
            dim_feedforward=4 * d_model,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(
            layer, layers, enable_nested_tensor=False
        )
        self.event_norm = nn.LayerNorm(d_model)
        self.deck = nn.Sequential(
            nn.Linear(card_dim * 4, d_model),
            nn.LayerNorm(d_model),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.global_net = nn.Sequential(
            nn.Linear(global_dim, d_model),
            nn.LayerNorm(d_model),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.head = nn.Sequential(
            nn.Linear(3 * d_model, d_model),
            nn.LayerNorm(d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, 2),
        )

    def deck_pool(self, ids):
        emb = self.cards(ids)
        mask = (ids != 0).unsqueeze(-1).float()
        return (emb * mask).sum(1) / mask.sum(1).clamp_min(1.0)

    def forward(self, continuous, card_ids, team_deck, opponent_deck, globals_seq, lengths):
        batch, seq_len = card_ids.shape
        card_emb = self.cards(card_ids)
        x = self.event_in(torch.cat([card_emb, continuous], dim=-1))
        positions = torch.arange(seq_len, device=x.device).unsqueeze(0)
        x = x + self.pos(positions)

        valid = positions < lengths.unsqueeze(1)
        causal = torch.triu(
            torch.ones(seq_len, seq_len, device=x.device, dtype=torch.bool),
            diagonal=1,
        )
        encoded = self.encoder(
            x,
            mask=causal,
            src_key_padding_mask=~valid,
        )
        encoded = self.event_norm(encoded)

        team = self.deck_pool(team_deck)
        opp = self.deck_pool(opponent_deck)
        deck_ctx = self.deck(
            torch.cat([team, opp, team - opp, team * opp], dim=-1)
        ).unsqueeze(1).expand(batch, seq_len, -1)
        global_ctx = self.global_net(globals_seq)
        return self.head(torch.cat([encoded, deck_ctx, global_ctx], dim=-1))


def to_device(batch, device):
    return tuple(x.to(device) if torch.is_tensor(x) else x for x in batch)


def masked_loss(logits, supervise, labels, label_smoothing=0.02):
    targets = labels.unsqueeze(1).expand(-1, logits.shape[1])
    return F.cross_entropy(
        logits[supervise],
        targets[supervise],
        label_smoothing=label_smoothing,
    )


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    loss_sum = 0.0
    loss_n = 0
    labels_all = []
    probs_all = []
    progress_all = []

    for batch in loader:
        cont, cards, team, opp, glob, supervise, progress, labels, lengths = to_device(
            batch, device
        )
        logits = model(cont, cards, team, opp, glob, lengths)
        if supervise.any():
            targets = labels.unsqueeze(1).expand(-1, logits.shape[1])
            selected_logits = logits[supervise]
            selected_targets = targets[supervise]
            loss = F.cross_entropy(selected_logits, selected_targets)
            n = int(selected_targets.numel())
            loss_sum += float(loss.item()) * n
            loss_n += n
            labels_all.extend(selected_targets.cpu().tolist())
            probs_all.extend(selected_logits.softmax(-1)[:, 1].cpu().tolist())
            progress_all.extend(progress[supervise].cpu().tolist())

    y = np.asarray(labels_all, dtype=np.int64)
    p = np.asarray(probs_all, dtype=np.float64)
    prog = np.asarray(progress_all, dtype=np.float64)
    pred = (p >= 0.5).astype(np.int64)

    result = {
        "loss": loss_sum / max(loss_n, 1),
        "accuracy": float((pred == y).mean()) if len(y) else 0.0,
        "auc": auc(y, p),
        "n": int(len(y)),
    }

    anchors = {}
    for ratio in (0.25, 0.50, 0.75, 0.90, 1.00):
        width = 0.06 if ratio < 1.0 else 0.035
        mask = np.abs(prog - ratio) <= width
        if mask.sum() < 10:
            anchors[str(ratio)] = {"auc": 0.5, "accuracy": 0.0, "n": int(mask.sum())}
            continue
        yy, pp = y[mask], p[mask]
        anchors[str(ratio)] = {
            "auc": auc(yy, pp),
            "accuracy": float(((pp >= 0.5).astype(np.int64) == yy).mean()),
            "n": int(mask.sum()),
        }
    return result, anchors


@torch.no_grad()
def prediction_traces(model, dataset, device, limit=5):
    model.eval()
    traces = []
    for item in dataset.items:
        if item["swapped"]:
            continue
        batch = collate_tokenwise([item])
        cont, cards, team, opp, glob, supervise, progress, labels, lengths = to_device(
            batch, device
        )
        logits = model(cont, cards, team, opp, glob, lengths)
        probs = logits.softmax(-1)[0, :, 1].cpu()
        points = []
        for i, (meta, supervised) in enumerate(zip(item["meta"], item["supervise"])):
            if not bool(supervised):
                continue
            points.append({
                **meta,
                "progress": float(item["progress"][i]),
                "p_team_win": float(probs[i]),
            })
        traces.append({
            "battle_id": item["battle_id"],
            "team_wins": item["label"],
            "points": points,
        })
        if len(traces) >= limit:
            break
    return traces


def run(args):
    src = Path(args.cochon_src).resolve()
    sys.path.insert(0, str(src))
    from cr_replay_pipeline.winner_dataset import (
        CONTINUOUS_DIM,
        GLOBAL_DIM,
        _encode_prefix,
        build_vocab,
        collect_battles,
        load_card_costs,
        split_battles,
        summarize_split,
    )

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(max(1, min(args.cpu_threads, os.cpu_count() or 1)))

    data_dir = Path(args.dataset_dir)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    download = download_replays(data_dir, args.max_files)

    battles = collect_battles(data_dir / "raw", min_card_plays=args.min_card_plays)
    if len(battles) < 50:
        raise RuntimeError(f"Need >=50 usable decisive battles; found {len(battles)}")

    train_b, val_b, test_b = split_battles(battles, seed=args.seed)
    vocab = build_vocab(train_b)
    costs = load_card_costs(data_dir / "card_costs.json")

    materialize_started = time.time()
    train_ds = TokenwiseBattleDataset(
        train_b, vocab, costs, _encode_prefix, augment_swap=True,
        min_events=args.min_events, seed=args.seed,
    )
    val_ds = TokenwiseBattleDataset(
        val_b, vocab, costs, _encode_prefix, augment_swap=False,
        min_events=args.min_events, seed=args.seed,
    )
    test_ds = TokenwiseBattleDataset(
        test_b, vocab, costs, _encode_prefix, augment_swap=False,
        min_events=args.min_events, seed=args.seed,
    )
    materialize_seconds = time.time() - materialize_started

    train_dl = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True, collate_fn=collate_tokenwise
    )
    val_dl = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_tokenwise
    )
    test_dl = DataLoader(
        test_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_tokenwise
    )

    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = TokenwiseValueTransformer(
        vocab.vocab_size, CONTINUOUS_DIM, GLOBAL_DIM,
        args.d_model, args.layers, args.heads, args.dropout,
    ).to(device)
    opt = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.02)
    sched = CosineAnnealingLR(
        opt, T_max=max(1, args.epochs), eta_min=args.learning_rate * 0.1
    )

    train_started = time.time()
    best_auc = -1.0
    best_state = None
    history = []

    for epoch in range(1, args.epochs + 1):
        epoch_started = time.time()
        model.train()
        losses = []
        supervised_positions = 0

        for batch in train_dl:
            cont, cards, team, opp, glob, supervise, _, labels, lengths = to_device(
                batch, device
            )
            opt.zero_grad(set_to_none=True)
            logits = model(cont, cards, team, opp, glob, lengths)
            loss = masked_loss(logits, supervise, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            losses.append(float(loss.item()))
            supervised_positions += int(supervise.sum().item())

        sched.step()
        val, _ = evaluate(model, val_dl, device)
        row = {
            "epoch": epoch,
            "epoch_seconds": round(time.time() - epoch_started, 2),
            "train_loss": float(np.mean(losses)),
            "train_supervised_positions": supervised_positions,
            **{f"val_{k}": v for k, v in val.items()},
        }
        history.append(row)
        print(json.dumps(row), flush=True)

        if val["auc"] > best_auc:
            best_auc = val["auc"]
            best_state = copy.deepcopy(model.state_dict())

    assert best_state is not None
    model.load_state_dict(best_state)
    test, by_progress = evaluate(model, test_dl, device)
    traces = prediction_traces(model, test_ds, device, limit=args.trace_matches)

    supervised_train = sum(int(item["supervise"].sum()) for item in train_ds.items)
    report = {
        "device": str(device),
        "download": download,
        "battles_total": len(battles),
        "splits": [
            summarize_split("train", train_b),
            summarize_split("val", val_b),
            summarize_split("test", test_b),
        ],
        "dataset_items": {
            "train": len(train_ds),
            "val": len(val_ds),
            "test": len(test_ds),
        },
        "supervised_train_positions": supervised_train,
        "materialize_seconds": round(materialize_seconds, 2),
        "train_seconds": round(time.time() - train_started, 2),
        "best_val_auc": best_auc,
        "test": test,
        "test_by_progress": by_progress,
        "history": history,
        "config": vars(args),
    }

    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "prediction_traces.json").write_text(
        json.dumps(traces, indent=2), encoding="utf-8"
    )
    (out / "vocab.json").write_text(
        json.dumps(vocab.to_dict(), indent=2), encoding="utf-8"
    )
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "vocab": vocab.to_dict(),
            "config": vars(args),
            "metrics": test,
        },
        out / "value_transformer_tokenwise.pt",
    )

    lines = [
        "# CR Coach token-wise Value pilot",
        "",
        f"- usable battles: {len(battles)}",
        f"- train battle-items: {len(train_ds)}",
        f"- supervised card placements: {supervised_train}",
        f"- dataset materialization: {materialize_seconds:.1f} s",
        f"- training: {report['train_seconds']:.1f} s",
        f"- best validation AUC: {best_auc:.4f}",
        f"- test AUC: {test['auc']:.4f}",
        f"- test accuracy: {test['accuracy']:.4f}",
        "",
        "## Test by match progress",
        "",
        "| Progress | AUC | Accuracy | N |",
        "|---:|---:|---:|---:|",
    ]
    for ratio, metrics in by_progress.items():
        lines.append(
            f"| {float(ratio):.0%} | {metrics['auc']:.4f} | "
            f"{metrics['accuracy']:.4f} | {metrics['n']} |"
        )
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


def parser():
    p = argparse.ArgumentParser(
        description="Train Value once per battle with token-level supervision"
    )
    p.add_argument(
        "--cochon-src",
        default=os.environ.get("COCHON_SRC", ".deps/clash-royale-ai/src"),
    )
    p.add_argument("--dataset-dir", default=".ml-data/clash-royale-replays")
    p.add_argument("--output-dir", default="outputs/value_tokenwise")
    p.add_argument("--max-files", type=int, default=150)
    p.add_argument("--epochs", type=int, default=8)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--d-model", type=int, default=96)
    p.add_argument("--layers", type=int, default=2)
    p.add_argument("--heads", type=int, default=4)
    p.add_argument("--dropout", type=float, default=0.15)
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--min-card-plays", type=int, default=8)
    p.add_argument("--min-events", type=int, default=8)
    p.add_argument("--trace-matches", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device")
    p.add_argument("--cpu-threads", type=int, default=4)
    return p


if __name__ == "__main__":
    run(parser().parse_args())
