#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"starter"))
from cr_coach.replay.io import load_replay
from cr_coach.runtime.rudy_runner import run_rudy_replay

CHECK_TICKS={0,21,48,49,50,55,60,80,85,100,120,140,160,180,190}

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
    generated=[json.loads(line) for line in (args.out/"events.jsonl").read_text(encoding="utf-8").splitlines()]
    bat_ticks=[
        int(row["state_tick"])
        for row in generated
        if row.get("kind")=="entity_created"
        and str((row.get("data") or {}).get("card_id","")).lower()=="bat"
    ]
    first_bat_tick=min(bat_ticks) if bat_ticks else None
    dart_death_ticks=[
        int(row["state_tick"])
        for row in generated
        if row.get("kind")=="entity_died"
        and str((row.get("data") or {}).get("card_id","")).lower() in {"blowdartgoblin","dart-goblin"}
    ]
    first_dart_death_tick=min(dart_death_ticks) if dart_death_ticks else None
    skeleton_counts_by_tick={}
    for snapshot in snaps:
        tick=int(snapshot["tick"])
        if tick not in {49,50,55,60}:
            continue
        skeleton_counts_by_tick[str(tick)]=sum(
            1 for entity in snapshot.get("entities",[])
            if entity.get("kind")!="tower"
            and "skeleton" in str(entity.get("card_id","")).lower()
            and bool(entity.get("alive",True))
        )
    # Video: Night Witch placement is ~19.1s and the first Bat is first visible
    # at ~22.0s.  With the replay origin at 18.0s this is tick ~80 (20 Hz).
    expected_first_bat_tick=80
    bat_error_ticks=None if first_bat_tick is None else first_bat_tick-expected_first_bat_tick
    bat_timing_pass=first_bat_tick is not None and abs(bat_error_ticks)<=2
    payload={
        "report":report,
        "selected":selected,
        "video_checks":{
            "first_bat":{
                "expected_tick":expected_first_bat_tick,
                "actual_tick":first_bat_tick,
                "error_ticks":bat_error_ticks,
                "tolerance_ticks":2,
                "passed":bat_timing_pass,
            },
            "dart_goblin_death":{
                "video_window_ticks":[78,80],
                "actual_tick":first_dart_death_tick,
                "gating":False,
            },
            "skeletons_after_play":{
                "play_tick":48,
                "counts_by_tick":skeleton_counts_by_tick,
                "expected_initial_count":3,
                "gating":False,
            },
        },
    }
    (args.out/"opening_probe.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    return 0 if report["status"]!="failed" and bat_timing_pass else 1

if __name__=="__main__":
    raise SystemExit(main())
