from __future__ import annotations

from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
TESTS = [
    HERE / "test_01_single_hog.py",
    HERE / "test_02_same_tick_dual_hog.py",
    HERE / "test_03_hand_mismatch_stops.py",
]


def main() -> int:
    print("CR Coach physical adapter tests")
    print("================================")
    failures: list[str] = []

    for path in TESTS:
        print(f"\n>>> {path.name}")
        result = subprocess.run([sys.executable, str(path)], cwd=HERE.parent)
        if result.returncode != 0:
            failures.append(path.name)

    print("\n================================")
    if failures:
        print("FAILED:")
        for name in failures:
            print(f"  - {name}")
        return 1

    print(f"ALL PASS ({len(TESTS)}/{len(TESTS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
