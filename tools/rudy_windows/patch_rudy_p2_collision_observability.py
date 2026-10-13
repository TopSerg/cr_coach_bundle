#!/usr/bin/env python3
"""P2 trace extension: expose collision geometry owned by Rust, never guessed by tests.

Apply after P1 and M17/M18 patches. No gameplay rules or stats are modified.
"""
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2]
    / "third_party" / "clash-royale-suite"
    / "cr-rudy-sim" / "simulator" / "engine" / "src"
)
path = ROOT / "lib.rs"
old = '            row.set_item("shield_hp", e.shield_hp)?;\n'
new = (
    old
    + '            row.set_item("collision_radius", e.collision_radius)?;\n'
    + '            row.set_item("mass", e.mass)?;\n'
    + '            row.set_item("is_flying", e.is_flying())?;\n'
)
source = path.read_text(encoding="utf-8")
if new in source:
    print("P2 collision observability already patched")
elif source.count(old) == 1:
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print("P2 collision observability installed")
else:
    raise RuntimeError("P2 collision observability marker mismatch")
