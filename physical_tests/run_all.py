from __future__ import annotations

from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
TESTS = [
    HERE / "test_01_single_hog.py",
    HERE / "test_02_same_tick_dual_hog.py",
    HERE / "test_03_hand_mismatch_stops.py",
    HERE / "test_04_hog_vs_tower.py",
    HERE / "test_05_hog_vs_cannon.py",
]


def main() -> int:
    print("CR Coach physical adapter/mechanics tests")
    print("========================================")
    failures: list[str] = []

    for path in TESTS:
        print(f"\n>>> {path.name}")
        result = subprocess.run([sys.executable, str(path)], cwd=HERE.parent)
        if result.returncode != 0:
            failures.append(path.name)

    print("\n========================================")
    if failures:
        print("FAILED:")
        for name in failures:
            print(f"  - {name}")
        return 1

    print(f"ALL PASS ({len(TESTS)}/{len(TESTS)})")
    print("Mechanics traces (tests 04/05): outputs/physical_tests/*.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
