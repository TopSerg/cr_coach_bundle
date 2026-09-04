#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def find_record(records, key: str):
    for rec in records:
        if rec.get("key") == key:
            return rec
    raise KeyError(f"Card key {key!r} not found")


def apply_field(record: dict, field: str, value):
    if field.endswith("]") and "[" in field:
        base, idx_text = field[:-1].split("[", 1)
        idx = int(idx_text)
        arr = record.get(base)
        if not isinstance(arr, list):
            raise TypeError(f"{base} is not an array on {record.get('key')}")
        if idx >= len(arr):
            arr.extend([None] * (idx + 1 - len(arr)))
        arr[idx] = value
    else:
        record[field] = value


def patch_one(out_data: Path, spec: dict):
    rel = Path(spec["file"])
    path = out_data / rel
    records = load_json(path)
    rec = find_record(records, spec["key"])

    before = {}
    after = {}
    for field, value in spec["fields"].items():
        if field.endswith("]") and "[" in field:
            base, idx_text = field[:-1].split("[", 1)
            idx = int(idx_text)
            arr = rec.get(base, [])
            before[field] = arr[idx] if isinstance(arr, list) and idx < len(arr) else None
        else:
            before[field] = rec.get(field)
        apply_field(rec, field, value)
        after[field] = value

    save_json(path, records)
    return {"key": spec["key"], "file": str(rel), "before": before, "after": after}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-data-dir", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    source = Path(args.source_data_dir).resolve()
    profile_path = Path(args.profile).resolve()
    out = Path(args.out_dir).resolve()

    if not source.exists():
        raise SystemExit(f"Source Rudy data dir not found: {source}")

    profile = load_json(profile_path)

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(source, out)

    changes = []
    for card_key in ("hog-rider", "cannon"):
        changes.append(patch_one(out, profile[card_key]))

    manifest = {
        "profile": profile["profile"],
        "level": profile["level"],
        "source_data_dir": str(source),
        "generated_data_dir": str(out),
        "changes": changes,
        "tower_princess_expected": profile["tower-princess"]["expected"],
        "tower_princess_note": profile["tower-princess"]["note"],
    }
    save_json(out / "TOURNAMENT11_OVERLAY_MANIFEST.json", manifest)

    print("Tournament-11 Rudy data generated:")
    print(f"  {out}")
    print("Applied overrides:")
    for ch in changes:
        print(f"  {ch['key']}")
        for field, value in ch["after"].items():
            old = ch["before"].get(field)
            print(f"    {field}: {old!r} -> {value!r}")


if __name__ == "__main__":
    main()
