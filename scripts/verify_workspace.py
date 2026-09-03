from __future__ import annotations
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
required = {
    "cr-bot": ["README.md", "src/cr_bot", "simulator"],
    "clash-royale-ai": ["README.md", "src/cr_replay_pipeline/parser.py", "src/cr_replay_pipeline/hand_tracker.py"],
    "KataCR": ["README.md"],
    "cr-api-data": ["README.md"],
}

ok = True
for repo, paths in required.items():
    base = root / "upstream" / repo
    for rel in paths:
        target = base / rel
        if target.exists():
            print(f"OK   {repo}/{rel}")
        else:
            ok = False
            print(f"MISS {repo}/{rel}")

raise SystemExit(0 if ok else 2)
