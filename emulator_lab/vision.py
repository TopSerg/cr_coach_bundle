"""Optional, conservative CV: ROI tower OCR and user-supplied unit templates.

No game internals, no automatic target inference. Template scores are NOT
calibrated probabilities; these are candidates requiring independent review.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .session import read_json, SIDES


def screen_to_world(rect: list[int], side: str, px: float, py: float) -> tuple[int, int]:
    left, top, right, bottom = rect
    if not left <= px <= right or not top <= py <= bottom:
        raise ValueError("entity center outside calibrated arena")
    x = (px - left) / (right - left) * 18000
    y = (py - top) / (bottom - top) * 32000
    if side == "opponent":
        x, y = 18000 - x, 32000 - y
    return round(x), round(y)


def tower_hp_from_crop(crop: Any, pytesseract: Any, cv2: Any) -> tuple[int, float] | None:
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    big = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(big, config="--psm 7 -c tessedit_char_whitelist=0123456789", output_type=pytesseract.Output.DICT)
    tokens = [(str(s).strip(), float(conf)) for s, conf in zip(data.get("text", []), data.get("conf", [])) if str(s).strip().isdigit() and float(conf) >= 0]
    if len(tokens) != 1:
        return None
    text, confidence = tokens[0]
    hp = int(text)
    if hp < 0 or hp > 10000:
        return None
    return hp, max(0.0, min(1.0, confidence / 100.0))


def extract_one(frame_path: Path, frame_meta: dict, config: dict, *, use_templates: bool = False, ocr_binary: str | None = None) -> list[dict]:
    try:
        import cv2
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("pip install opencv-python pytesseract; install Tesseract OCR separately") from exc
    if ocr_binary:
        pytesseract.pytesseract.tesseract_cmd = ocr_binary
    side = frame_meta["side"]
    if side not in SIDES:
        raise ValueError("invalid frame side")
    image = cv2.imread(str(frame_path))
    if image is None:
        raise ValueError(f"cannot read {frame_path}")
    dev = config["devices"][side]
    timestamp = frame_meta["timestamp_ns"]
    uncertainty_ns = frame_meta["time_uncertainty_ns"]
    rows = []
    for roi in dev.get("tower_hp_rois", []):
        left, top, right, bottom = roi["rect"]
        if not (0 <= left < right <= image.shape[1] and 0 <= top < bottom <= image.shape[0]):
            raise ValueError(f"invalid ROI rectangle for {side}")
        result = tower_hp_from_crop(image[top:bottom, left:right], pytesseract, cv2)
        if result is None:
            continue
        hp, confidence = result
        rows.append({"kind": "tower_hp", "side": side, "owner": roi["owner"], "role": roi["role"],
                     "hp": hp, "confidence": confidence, "timestamp_ns": timestamp,
                     "time_uncertainty_ns": uncertainty_ns, "frame": frame_meta["image"], "source": "ocr"})
    if use_templates:
        import numpy as np
        arena = dev["arena_rect_px"]
        for template in dev.get("unit_templates", []):
            template_path = Path(template["path"])
            if not template_path.is_absolute():
                template_path = frame_path.parents[2] / template_path
            tpl = cv2.imread(str(template_path))
            if tpl is None:
                raise ValueError(f"missing template: {template_path}")
            l, t, r, b = arena
            area = image[t:b, l:r]
            if tpl.shape[0] > area.shape[0] or tpl.shape[1] > area.shape[1]:
                raise ValueError("template larger than arena")
            scores = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
            threshold = float(template.get("threshold", 0.92))
            if not 0.8 <= threshold <= 1:
                raise ValueError("template threshold must be 0.8..1")
            candidates = np.argwhere(scores >= threshold)
            candidates = sorted(candidates, key=lambda p: -float(scores[p[0], p[1]]))
            used = []
            for py, px in candidates:
                center_x = l + int(px) + tpl.shape[1] / 2
                center_y = t + int(py) + tpl.shape[0] / 2
                if any(abs(center_x - ox) < tpl.shape[1] / 2 and abs(center_y - oy) < tpl.shape[0] / 2 for ox, oy in used):
                    continue
                used.append((center_x, center_y))
                x, y = screen_to_world(arena, side, center_x, center_y)
                rows.append({"kind": "position_candidate", "card_id": template["card_id"], "owner": template["owner"],
                             "x_mtile": x, "y_mtile": y, "confidence": float(scores[py, px]),
                             "timestamp_ns": timestamp, "time_uncertainty_ns": uncertainty_ns,
                             "side": side, "source": "uncalibrated_template_candidate", "frame": frame_meta["image"]})
                if len(used) >= int(template.get("max_candidates", 4)):
                    break
    return rows


def observe_frames(directory: Path, out: Path, *, templates: bool = False, ocr_binary: str | None = None) -> int:
    config = read_json(directory / "config.json")
    frame_files = sorted((directory / "frames").glob("*/*.json"))
    if not frame_files:
        raise ValueError("no captured frames; run capture first")
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", encoding="utf-8") as handle:
        for file in frame_files:
            meta = read_json(file)
            frame_path = (directory / meta["image"]).resolve()
            if not frame_path.is_relative_to(directory.resolve()):
                raise ValueError("frame outside session directory")
            for row in extract_one(frame_path, meta, config, use_templates=templates, ocr_binary=ocr_binary):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
    return count
