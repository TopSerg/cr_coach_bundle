#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"starter"))
from cr_coach.replay.io import load_replay
from cr_coach.runtime.rudy_runner import run_rudy_replay

CHECK_TICKS={0,21,48,60,80,100,120,140,160,180,190}

def compact(snapshot):
    rows=[]
    for e in snapshot.get("entities",[]):
        if e.get("kind")=="tower" or not e.get("alive",True):
            continue
        rows.append({
            "uid":e["uid"],"owner":e["owner"],"card":e["card_id"],
            "x":e["x_mtile"],"y":e["y_mtile"],"hp":e["hp"],
            "target":e.get("target_uid"),"deploy_us":e.get("deploy_remaining_us"),
            "phase":e.get("attack_phase"),
        })
    return {"tick":snapshot["tick"],"entities":rows}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-dir",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args()
    spec=load_replay(ROOT/"examples/golem_demo_20260920_first_segment.json")
    report=run_rudy_replay(spec,args.out,data_dir=args.data_dir,sample_ticks=1)
    snaps=[json.loads(line) for line in (args.out/"snapshots.jsonl").read_text(encoding="utf-8").splitlines()]
    selected=[compact(s) for s in snaps if int(s["tick"]) in CHECK_TICKS]
    payload={"report":report,"selected":selected}
    (args.out/"opening_probe.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    return 0 if report["status"]!="failed" else 1

if __name__=="__main__":
    raise SystemExit(main())
