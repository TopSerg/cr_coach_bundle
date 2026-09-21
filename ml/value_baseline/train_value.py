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
from torch.utils.data import DataLoader

DATASET_REPO = "Cochon123/clash-royale-replays"
DEFAULT_PREFIXES = [0.25, 0.50, 0.75, 0.90, 1.00]


def parse_ratios(text: str) -> list[float]:
    values = [float(v.strip()) for v in text.split(",") if v.strip()]
    if not values or any(v <= 0 or v > 1 for v in values):
        raise argparse.ArgumentTypeError("prefix ratios must be in (0, 1]")
    return values


def download_replays(root: Path, max_files: int) -> dict[str, int]:
    root.mkdir(parents=True, exist_ok=True)
    files = sorted(
        p for p in HfApi().list_repo_files(DATASET_REPO, repo_type="dataset")
        if p.startswith("raw/") and p.endswith(".json")
    )
    if not files:
        raise RuntimeError(f"No raw replay JSON found in {DATASET_REPO}")
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


class ValueTransformer(nn.Module):
    def __init__(self, vocab_size: int, continuous_dim: int, global_dim: int,
                 d_model: int, layers: int, heads: int, dropout: float) -> None:
        super().__init__()
        if d_model % heads:
            raise ValueError("d_model must be divisible by heads")
        card_dim = 48
        self.cards = nn.Embedding(vocab_size, card_dim, padding_idx=0)
        self.event_in = nn.Sequential(
            nn.Linear(card_dim + continuous_dim, d_model), nn.LayerNorm(d_model), nn.GELU()
        )
        self.pos = nn.Embedding(256, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=heads, dim_feedforward=4 * d_model,
            dropout=dropout, activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.event_norm = nn.LayerNorm(d_model)
        self.deck = nn.Sequential(
            nn.Linear(card_dim * 4, d_model), nn.LayerNorm(d_model), nn.GELU(), nn.Dropout(dropout)
        )
        self.global_net = nn.Sequential(
            nn.Linear(global_dim, d_model), nn.LayerNorm(d_model), nn.GELU(), nn.Dropout(dropout)
        )
        self.head = nn.Sequential(
            nn.Linear(3 * d_model, d_model), nn.LayerNorm(d_model), nn.GELU(),
            nn.Dropout(dropout), nn.Linear(d_model, 2)
        )

    def deck_pool(self, ids: torch.Tensor) -> torch.Tensor:
        emb = self.cards(ids)
        mask = (ids != 0).unsqueeze(-1).float()
        return (emb * mask).sum(1) / mask.sum(1).clamp_min(1.0)

    def forward(self, continuous, card_ids, team_deck, opponent_deck, globals_, lengths):
        seq_len = continuous.shape[1]
        card_emb = self.cards(card_ids)
        events = self.event_in(torch.cat([card_emb, continuous], dim=-1))
        positions = torch.arange(seq_len, device=events.device).unsqueeze(0)
        events = events + self.pos(positions)
        valid = positions < lengths.unsqueeze(1)
        encoded = self.event_norm(self.encoder(events, src_key_padding_mask=~valid))
        last = (lengths - 1).view(-1, 1, 1).expand(-1, 1, encoded.shape[-1])
        event_ctx = encoded.gather(1, last).squeeze(1)
        team, opp = self.deck_pool(team_deck), self.deck_pool(opponent_deck)
        deck_ctx = self.deck(torch.cat([team, opp, team - opp, team * opp], dim=-1))
        return self.head(torch.cat([event_ctx, deck_ctx, self.global_net(globals_)], dim=-1))


def to_device(batch, device):
    return tuple(x.to(device) if torch.is_tensor(x) else x for x in batch)


@torch.no_grad()
def evaluate(model, loader, device) -> dict[str, float]:
    model.eval()
    losses, labels, probs = [], [], []
    for batch in loader:
        cont, cards, team, opp, glob, y, lengths = to_device(batch, device)
        logits = model(cont, cards, team, opp, glob, lengths)
        losses.append(float(F.cross_entropy(logits, y).item()))
        labels.extend(y.cpu().tolist())
        probs.extend(logits.softmax(-1)[:, 1].cpu().tolist())
    y = np.asarray(labels, dtype=np.int64)
    p = np.asarray(probs, dtype=np.float64)
    pred = (p >= 0.5).astype(np.int64)
    return {
        "loss": float(np.mean(losses)) if losses else math.nan,
        "accuracy": float((pred == y).mean()) if len(y) else 0.0,
        "auc": auc(y, p),
        "n": int(len(y)),
    }


def run(args) -> None:
    src = Path(args.cochon_src).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Pinned cochon source not found: {src}")
    sys.path.insert(0, str(src))
    from cr_replay_pipeline.winner_dataset import (
        CONTINUOUS_DIM, GLOBAL_DIM, WinnerSequenceDataset, build_vocab,
        collate_winner_batch, collect_battles, create_dataloaders,
        load_card_costs, split_battles, summarize_split,
    )

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(max(1, min(args.cpu_threads, os.cpu_count() or 1)))
    data_dir, out = Path(args.dataset_dir), Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    download = download_replays(data_dir, args.max_files)
    battles = collect_battles(data_dir / "raw", min_card_plays=args.min_card_plays)
    if len(battles) < 50:
        raise RuntimeError(f"Need >=50 usable decisive battles; found {len(battles)}")

    train_b, val_b, test_b = split_battles(battles, seed=args.seed)
    vocab = build_vocab(train_b)
    costs = load_card_costs(data_dir / "card_costs.json")
    train_dl, val_dl, test_dl = create_dataloaders(
        train_b, val_b, test_b, vocab, costs,
        batch_size=args.batch_size, sample_ratios=args.prefix_ratios,
    )
    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = ValueTransformer(vocab.vocab_size, CONTINUOUS_DIM, GLOBAL_DIM,
                             args.d_model, args.layers, args.heads, args.dropout).to(device)
    opt = AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.02)
    sched = CosineAnnealingLR(opt, T_max=max(1, args.epochs), eta_min=args.learning_rate * 0.1)

    best_auc, best_state, history = -1.0, None, []
    started = time.time()
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in train_dl:
            cont, cards, team, opp, glob, y, lengths = to_device(batch, device)
            opt.zero_grad(set_to_none=True)
            logits = model(cont, cards, team, opp, glob, lengths)
            loss = F.cross_entropy(logits, y, label_smoothing=0.02)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            losses.append(float(loss.item()))
        sched.step()
        val = evaluate(model, val_dl, device)
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)),
               **{f"val_{k}": v for k, v in val.items()}}
        history.append(row)
        print(json.dumps(row), flush=True)
        if val["auc"] > best_auc:
            best_auc, best_state = val["auc"], copy.deepcopy(model.state_dict())

    assert best_state is not None
    model.load_state_dict(best_state)
    test = evaluate(model, test_dl, device)
    by_prefix = {}
    for ratio in DEFAULT_PREFIXES:
        ds = WinnerSequenceDataset(test_b, vocab, costs, sample_ratios=[ratio], augment_swap=False)
        dl = DataLoader(ds, batch_size=args.batch_size, shuffle=False,
                        collate_fn=collate_winner_batch)
        by_prefix[str(ratio)] = evaluate(model, dl, device)

    config = {
        "dataset_repo": DATASET_REPO, "prefix_ratios": args.prefix_ratios,
        "d_model": args.d_model, "layers": args.layers, "heads": args.heads,
        "dropout": args.dropout, "min_card_plays": args.min_card_plays, "seed": args.seed,
    }
    report = {
        "device": str(device), "seconds": round(time.time() - started, 2), "download": download,
        "battles_total": len(battles),
        "splits": [summarize_split("train", train_b), summarize_split("val", val_b),
                   summarize_split("test", test_b)],
        "sequences": {"train": len(train_dl.dataset), "val": len(val_dl.dataset),
                      "test": len(test_dl.dataset)},
        "vocab_size": vocab.vocab_size, "best_val_auc": best_auc,
        "test": test, "test_by_prefix_ratio": by_prefix, "history": history, "config": config,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "vocab.json").write_text(json.dumps(vocab.to_dict(), indent=2), encoding="utf-8")
    torch.save({
        "model_state_dict": model.state_dict(), "vocab": vocab.to_dict(),
        "config": config, "metrics": report["test"]
    }, out / "value_transformer.pt")

    lines = [
        "# CR Coach Value baseline", "", f"- usable battles: {len(battles)}",
        f"- device: {device}", f"- best validation AUC: {best_auc:.4f}",
        f"- test AUC: {test['auc']:.4f}", f"- test accuracy: {test['accuracy']:.4f}",
        "", "## Test by observed replay fraction", "",
        "| Prefix | AUC | Accuracy | N |", "|---:|---:|---:|---:|",
    ]
    for ratio, metrics in by_prefix.items():
        lines.append(
            f"| {float(ratio):.0%} | {metrics['auc']:.4f} | "
            f"{metrics['accuracy']:.4f} | {metrics['n']} |"
        )
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"best_val_auc": best_auc, "test": test, "by_prefix": by_prefix}, indent=2))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Train CR Coach replay-only Value Transformer")
    p.add_argument("--cochon-src", default=os.environ.get(
        "COCHON_SRC", ".deps/clash-royale-ai/src"))
    p.add_argument("--dataset-dir", default=".ml-data/clash-royale-replays")
    p.add_argument("--output-dir", default="outputs/value_baseline")
    p.add_argument("--max-files", type=int, default=800, help="0 = full raw corpus")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--d-model", type=int, default=96)
    p.add_argument("--layers", type=int, default=2)
    p.add_argument("--heads", type=int, default=4)
    p.add_argument("--dropout", type=float, default=0.15)
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--min-card-plays", type=int, default=8)
    p.add_argument("--prefix-ratios", type=parse_ratios, default=DEFAULT_PREFIXES)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device")
    p.add_argument("--cpu-threads", type=int, default=4)
    return p


if __name__ == "__main__":
    run(parser().parse_args())
