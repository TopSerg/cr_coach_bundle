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


def normalize(value: str) -> str:
    return (
        str(value or "")
        .lower()
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
        .replace(".", "")
    )


def record_ids(record: dict) -> set[str]:
    """Identifiers Rudy itself may use/derive for a stats record."""
    values = []
    for field in ("key", "name", "name_en", "sc_key"):
        value = record.get(field)
        if value:
            values.append(normalize(value))
    return set(values)


def find_records(records: list[dict], selector: str):
    """
    Match by normalized key/name/sc_key, not only raw `key`.

    This matters for Rudy's source data: e.g. the playable card key is
    `hog-rider`, while the raw character stats entry is named `HogRider` and
    Rudy derives/aliases the playable key during GameData::load().
    """
    target = normalize(selector)
    matches = []
    for idx, rec in enumerate(records):
        if target in record_ids(rec):
            matches.append((idx, rec))
    if not matches:
        sample = []
        for rec in records:
            ids = record_ids(rec)
            if any(target in x or x in target for x in ids if x):
                sample.append({k: rec.get(k) for k in ("key", "name", "name_en", "sc_key")})
                if len(sample) >= 8:
                    break
        raise KeyError(
            f"Card/unit selector {selector!r} not found by key/name/sc_key. "
            f"Near matches: {sample}"
        )
    return matches


def apply_field(record: dict, field: str, value):
    if field.endswith("]") and "[" in field:
        base, idx_text = field[:-1].split("[", 1)
        idx = int(idx_text)
        arr = record.get(base)
        if not isinstance(arr, list):
            raise TypeError(f"{base} is not an array on {record.get('name') or record.get('key')}")
        if idx >= len(arr):
            arr.extend([None] * (idx + 1 - len(arr)))
        arr[idx] = value
    else:
        record[field] = value


def get_field(record: dict, field: str):
    if field.endswith("]") and "[" in field:
        base, idx_text = field[:-1].split("[", 1)
        idx = int(idx_text)
        arr = record.get(base, [])
        return arr[idx] if isinstance(arr, list) and idx < len(arr) else None
    return record.get(field)


def patch_one(out_data: Path, spec: dict):
    rel = Path(spec["file"])
    path = out_data / rel
    records = load_json(path)
    matches = find_records(records, spec["key"])

    patched = []
    for idx, rec in matches:
        before = {field: get_field(rec, field) for field in spec["fields"]}
        for field, value in spec["fields"].items():
            apply_field(rec, field, value)
        after = {field: get_field(rec, field) for field in spec["fields"]}
        patched.append(
            {
                "index": idx,
                "identifiers": {
                    k: rec.get(k) for k in ("key", "name", "name_en", "sc_key")
                },
                "before": before,
                "after": after,
            }
        )

    save_json(path, records)
    return {
        "selector": spec["key"],
        "file": str(rel),
        "match_count": len(patched),
        "records": patched,
    }


def expected_level11(spec: dict):
    fields = spec["fields"]
    return {
        "hp": fields.get("hitpoints_per_level[10]"),
        "damage": fields.get("damage_per_level[10]"),
    }


def spawn_probe(data, card_key: str, x: int, y: int):
    import cr_engine

    fillers = [
        "knight", "archers", "fireball", "giant",
        "valkyrie", "musketeer", "zap",
    ]
    deck = [card_key] + fillers
    opponent = [
        "knight", "archers", "fireball", "giant",
        "valkyrie", "musketeer", "skeleton-army", "zap",
    ]
    match = cr_engine.new_match(data, deck, opponent)
    hand = match.get_observation(1)["my_hand"]
    idx = hand.index(card_key)
    match.play_card(1, idx, x, y, 11)
    entities = [e for e in match.get_entities() if e.get("team") == 1]
    if not entities:
        raise RuntimeError(f"Runtime probe spawned no entity for {card_key}")
    e = entities[0]
    return {
        "card": e.get("card_key", e.get("card")),
        "hp": e.get("hp"),
        "max_hp": e.get("max_hp"),
        "damage": e.get("damage"),
        "x": e.get("x"),
        "y": e.get("y"),
    }


def verify_runtime(out_data: Path, profile: dict):
    """Fail before the fidelity test if the generated JSON is not what Rudy actually uses."""
    try:
        import cr_engine
    except ImportError as exc:
        raise RuntimeError(
            "cr_engine is required for runtime verification. Run this script with .venv-rudy Python."
        ) from exc

    data = cr_engine.load_data(str(out_data))
    probes = {
        "hog-rider": spawn_probe(data, "hog-rider", -3300, -7200),
        "cannon": spawn_probe(data, "cannon", -1200, -6000),
    }

    failures = []
    for key, probe in probes.items():
        expected = expected_level11(profile[key])
        if probe["max_hp"] != expected["hp"]:
            failures.append(
                f"{key}: runtime HP {probe['max_hp']} != expected {expected['hp']}"
            )
        if probe["damage"] != expected["damage"]:
            failures.append(
                f"{key}: runtime damage {probe['damage']} != expected {expected['damage']}"
            )

    print("Runtime level-11 verification:")
    for key, probe in probes.items():
        print(
            f"  {key}: HP={probe['max_hp']} damage={probe['damage']} "
            f"(spawn card={probe['card']!r})"
        )

    if failures:
        raise RuntimeError("Tournament override did not reach Rudy runtime:\n  " + "\n  ".join(failures))

    return probes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-data-dir", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--verify-runtime", action="store_true")
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

    runtime_probes = None
    if args.verify_runtime:
        runtime_probes = verify_runtime(out, profile)

    manifest = {
        "profile": profile["profile"],
        "level": profile["level"],
        "source_data_dir": str(source),
        "generated_data_dir": str(out),
        "changes": changes,
        "runtime_probes": runtime_probes,
        "tower_princess_expected": profile["tower-princess"]["expected"],
        "tower_princess_note": profile["tower-princess"]["note"],
    }
    save_json(out / "TOURNAMENT11_OVERLAY_MANIFEST.json", manifest)

    print("Tournament-11 Rudy data generated:")
    print(f"  {out}")
    print("Applied overrides:")
    for ch in changes:
        print(f"  {ch['selector']}: matched {ch['match_count']} raw stats record(s)")
        for rec in ch["records"]:
            ids = rec["identifiers"]
            print(f"    record #{rec['index']}: {ids}")
            for field, value in rec["after"].items():
                old = rec["before"].get(field)
                print(f"      {field}: {old!r} -> {value!r}")


if __name__ == "__main__":
    main()
