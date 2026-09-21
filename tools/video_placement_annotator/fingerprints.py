from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import json
import math

import cv2
import numpy as np


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def normalize_card_key(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(" ", "-")


def _central_art(image: np.ndarray) -> np.ndarray:
    if image is None or image.size == 0:
        raise ValueError("empty card image")
    h, w = image.shape[:2]
    # Exclude most of the frame, level badge and elixir badge. The artwork is
    # the part that survives resizing, replay overlays and insufficient-elixir
    # desaturation best.
    x1, x2 = int(w * 0.12), int(w * 0.88)
    y1, y2 = int(h * 0.08), int(h * 0.82)
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("card crop became empty")
    return cv2.resize(crop, (72, 72), interpolation=cv2.INTER_AREA)


def _phash64(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)
    low = dct[:8, :8].copy()
    # The DC term is mostly global brightness; make it neutral so greying/
    # dimming a hand card does not change identity.
    values = low.reshape(-1)
    median = float(np.median(values[1:]))
    values[0] = median
    bits = values > median
    result = 0
    for bit in bits:
        result = (result << 1) | int(bool(bit))
    return result


def _feature_hist(art: np.ndarray) -> tuple[float, ...]:
    gray = cv2.cvtColor(art, cv2.COLOR_BGR2GRAY)
    luma = cv2.calcHist([gray], [0], None, [16], [0, 256]).reshape(-1)
    hsv = cv2.cvtColor(art, cv2.COLOR_BGR2HSV)
    # Hue is useful for normal cards but is intentionally low-weighted later,
    # because insufficient-elixir cards can be almost grayscale.
    hue_mask = (hsv[:, :, 1] > 40).astype(np.uint8) * 255
    hue = cv2.calcHist([hsv], [0], hue_mask, [16], [0, 180]).reshape(-1)
    vec = np.concatenate([luma, hue]).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return tuple(float(x) for x in vec)


@dataclass(frozen=True)
class CardFingerprint:
    phash: int
    edge_phash: int
    hist: tuple[float, ...]

    def to_json(self) -> dict:
        return {
            "phash": f"{self.phash:016x}",
            "edge_phash": f"{self.edge_phash:016x}",
            "hist": [round(x, 7) for x in self.hist],
        }

    @classmethod
    def from_json(cls, raw: Mapping) -> "CardFingerprint":
        return cls(
            phash=int(str(raw["phash"]), 16),
            edge_phash=int(str(raw["edge_phash"]), 16),
            hist=tuple(float(x) for x in raw["hist"]),
        )


def fingerprint_image(image: np.ndarray) -> CardFingerprint:
    art = _central_art(image)
    gray = cv2.cvtColor(art, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    edge = cv2.Canny(gray, 55, 145)
    return CardFingerprint(
        phash=_phash64(gray),
        edge_phash=_phash64(edge),
        hist=_feature_hist(art),
    )


def hamming64(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    aa = np.asarray(a, dtype=np.float32)
    bb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(aa) * np.linalg.norm(bb))
    if denom <= 1e-12:
        return 0.0
    return float(np.clip(np.dot(aa, bb) / denom, 0.0, 1.0))


@dataclass(frozen=True)
class CardFingerprintRecord:
    card: str
    elixir: int | None
    fingerprint: CardFingerprint
    source: str | None = None

    def to_json(self) -> dict:
        out = {
            "card": self.card,
            "elixir": self.elixir,
            **self.fingerprint.to_json(),
        }
        if self.source:
            out["source"] = self.source
        return out

    @classmethod
    def from_json(cls, raw: Mapping) -> "CardFingerprintRecord":
        return cls(
            card=normalize_card_key(str(raw["card"])),
            elixir=None if raw.get("elixir") is None else int(raw["elixir"]),
            fingerprint=CardFingerprint.from_json(raw),
            source=raw.get("source"),
        )


@dataclass(frozen=True)
class MatchCandidate:
    card: str
    score: float
    phash_similarity: float
    edge_similarity: float
    hist_similarity: float
    elixir_match: bool | None


def compare_fingerprints(
    query: CardFingerprint,
    ref: CardFingerprint,
    *,
    observed_elixir: int | None = None,
    expected_elixir: int | None = None,
) -> tuple[float, float, float, float, bool | None]:
    p = 1.0 - hamming64(query.phash, ref.phash) / 64.0
    e = 1.0 - hamming64(query.edge_phash, ref.edge_phash) / 64.0
    h = _cosine(query.hist, ref.hist)

    # pHash carries identity. Edges add robustness when hue is lost. Histogram
    # is a weak tie-breaker. Elixir is a very strong discrete tie-breaker when
    # the HUD digit detector supplies it.
    base = 0.62 * p + 0.25 * e + 0.13 * h
    elixir_match: bool | None = None
    if observed_elixir is not None and expected_elixir is not None:
        elixir_match = observed_elixir == expected_elixir
        if elixir_match:
            score = 0.92 * base + 0.08
        else:
            # Keep a non-zero score because digit OCR can be wrong, but make a
            # correct-cost near-neighbour dominate a visually similar card.
            score = 0.92 * base - 0.10
    else:
        score = base
    return float(np.clip(score, 0.0, 1.0)), p, e, h, elixir_match


class FingerprintDatabase:
    SCHEMA = "cr_coach.card_fingerprints.v1"

    def __init__(self, records: Iterable[CardFingerprintRecord], *, meta: Mapping | None = None):
        self.records = {r.card: r for r in records}
        self.meta = dict(meta or {})
        if not self.records:
            raise ValueError("fingerprint database is empty")

    @classmethod
    def load(cls, path: str | Path) -> "FingerprintDatabase":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema") != cls.SCHEMA:
            raise ValueError(f"unsupported fingerprint schema: {raw.get('schema')!r}")
        return cls(
            (CardFingerprintRecord.from_json(x) for x in raw["cards"]),
            meta=raw.get("meta", {}),
        )

    def save(self, path: str | Path) -> None:
        payload = {
            "schema": self.SCHEMA,
            "meta": self.meta,
            "cards": [self.records[k].to_json() for k in sorted(self.records)],
        }
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def rank(
        self,
        image: np.ndarray,
        *,
        allowed: Iterable[str] | None = None,
        observed_elixir: int | None = None,
        limit: int = 5,
    ) -> list[MatchCandidate]:
        query = fingerprint_image(image)
        allowed_keys = {normalize_card_key(x) for x in allowed} if allowed else None
        ranked = []
        for card, rec in self.records.items():
            if allowed_keys is not None and card not in allowed_keys:
                continue
            score, p, e, h, em = compare_fingerprints(
                query,
                rec.fingerprint,
                observed_elixir=observed_elixir,
                expected_elixir=rec.elixir,
            )
            ranked.append(MatchCandidate(card, score, p, e, h, em))
        if not ranked:
            raise ValueError("no fingerprint candidates after allowed-card filter")
        ranked.sort(key=lambda x: (x.score, x.phash_similarity, x.edge_similarity), reverse=True)
        return ranked[: max(1, int(limit))]

    def nearest_pairs(self, limit: int = 20) -> list[tuple[str, str, float]]:
        keys = sorted(self.records)
        pairs = []
        for i, a in enumerate(keys):
            ra = self.records[a]
            for b in keys[i + 1 :]:
                rb = self.records[b]
                score, *_ = compare_fingerprints(
                    ra.fingerprint,
                    rb.fingerprint,
                    observed_elixir=ra.elixir,
                    expected_elixir=rb.elixir,
                )
                pairs.append((a, b, score))
        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs[: max(1, int(limit))]


class CardFingerprintMatcher:
    """Runtime matcher: loads only compact fingerprints, not card PNGs."""

    def __init__(
        self,
        database: str | Path | FingerprintDatabase,
        allowed: Iterable[str] | None = None,
    ):
        self.db = database if isinstance(database, FingerprintDatabase) else FingerprintDatabase.load(database)
        self.allowed = tuple(normalize_card_key(x) for x in allowed) if allowed else None

    def match(
        self,
        crop: np.ndarray,
        observed_elixir: int | None = None,
    ) -> tuple[str, float, float]:
        ranked = self.db.rank(
            crop,
            allowed=self.allowed,
            observed_elixir=observed_elixir,
            limit=2,
        )
        best = ranked[0]
        second = ranked[1].score if len(ranked) > 1 else 0.0
        margin = max(0.0, best.score - second)
        # Confidence is conservative unless both absolute similarity and the
        # separation from the runner-up are healthy.
        margin_conf = min(1.0, margin / 0.14)
        confidence = float(np.clip(0.78 * best.score + 0.22 * margin_conf, 0.0, 1.0))
        return best.card, confidence, margin


def load_elixir_map(stats_json: str | Path | None) -> dict[str, int]:
    if stats_json is None:
        return {}
    raw = json.loads(Path(stats_json).read_text(encoding="utf-8"))
    cards = raw.get("cards", raw)
    out: dict[str, int] = {}
    for key, value in cards.items():
        if not isinstance(value, Mapping):
            continue
        cost = value.get("elixir")
        if cost is None:
            continue
        out[normalize_card_key(str(key))] = int(cost)
        display = value.get("display")
        if display:
            out.setdefault(normalize_card_key(str(display)), int(cost))
    return out


def build_database(
    images_dir: str | Path,
    *,
    stats_json: str | Path | None = None,
    allowed: Iterable[str] | None = None,
    source_label: str | None = None,
) -> FingerprintDatabase:
    allowed_keys = {normalize_card_key(x) for x in allowed} if allowed else None
    elixir = load_elixir_map(stats_json)
    records = []
    for path in sorted(Path(images_dir).iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        card = normalize_card_key(path.stem)
        if allowed_keys is not None and card not in allowed_keys:
            continue
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        records.append(
            CardFingerprintRecord(
                card=card,
                elixir=elixir.get(card),
                fingerprint=fingerprint_image(image),
                source=source_label or path.name,
            )
        )
    return FingerprintDatabase(
        records,
        meta={
            "source": source_label or str(images_dir),
            "count": len(records),
            "features": {
                "phash_bits": 64,
                "edge_phash_bits": 64,
                "hist_bins": 32,
                "weights": {"phash": 0.62, "edge_phash": 0.25, "hist": 0.13},
            },
        },
    )
