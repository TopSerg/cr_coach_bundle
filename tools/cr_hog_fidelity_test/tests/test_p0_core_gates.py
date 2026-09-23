from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[3]


def load_module():
    sys.modules.setdefault("cr_engine", types.ModuleType("cr_engine"))
    sys.path.insert(0, str(ROOT / "tools" / "cr_hog_fidelity_test"))
    spec = importlib.util.spec_from_file_location("p0_core_gates", ROOT / "tools" / "p0_core_gates.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_p0_registry_and_manifest_cover_the_same_gates():
    module = load_module()
    manifest = json.loads((ROOT / "physical_tests" / "references" / "p0_manifest.json").read_text(encoding="utf-8"))
    assert tuple(module.GATES) == module.P0_IDS
    assert set(manifest["gates"]) == set(module.P0_IDS)


def test_gate_keeps_the_first_divergence():
    module = load_module()
    gate = module.Gate("MXX", "test", snapshots=[{"tick": 4, "entities": []}])
    gate.fail(5, "targeting", "A", "B", "first")
    gate.fail(6, "combat", 1, 2, "second")
    report = gate.result()
    assert report["passed"] is False
    assert report["first_divergence"]["tick"] == 5
    assert report["first_divergence"]["subsystem"] == "TARGETING"
    assert report["first_divergence"]["last_exact_tick"] == 4
