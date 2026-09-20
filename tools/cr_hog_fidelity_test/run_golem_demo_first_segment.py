#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"starter"))
from cr_coach.replay.io import load_replay
from cr_coach.runtime.rudy_runner import run_rudy_replay

CHECK_TICKS={0,21,48,49,50,55,60,78,80,85,100,120,140,160,180,189,190,200,220,240,260,335,336,345,355,365,385,405,409,410,420,440,460,479,480,500,520,541,542,560,574,575,580,600,618,619,630,650,700,740,760,900,948,949,960,980,990,991,1000,1040,1100,1160,1161,1180,1220,1260,1300}

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
    dart_damage_events=[
        {
            "tick":int(row.get("tick",0)),
            "state_tick":int(row.get("state_tick",0)),
            "kind":row.get("kind"),
            "source_card":(row.get("data") or {}).get("source_card_id"),
            "damage":(row.get("data") or {}).get("damage"),
            "hp_after":(row.get("data") or {}).get("hp_after"),
        }
        for row in generated
        if row.get("kind") in {"damage_applied","damage_observed"}
        and int((row.get("data") or {}).get("target_uid") or -1)==1
    ]
    skeleton_counts_by_tick={}
    goblin_gang_by_tick={}
    for snapshot in snaps:
        tick=int(snapshot["tick"])
        if tick in {49,50,55,60}:
            skeleton_counts_by_tick[str(tick)]=sum(
                1 for entity in snapshot.get("entities",[])
                if entity.get("kind")!="tower"
                and "skeleton" in str(entity.get("card_id","")).lower()
                and bool(entity.get("alive",True))
            )
        if tick in {190,200}:
            breakdown={}
            for entity in snapshot.get("entities",[]):
                if entity.get("kind")=="tower" or not bool(entity.get("alive",True)):
                    continue
                card=str(entity.get("card_id","")).lower()
                if card in {"goblin","goblin-gang","speargoblin","spear-goblin"}:
                    breakdown[card]=breakdown.get(card,0)+1
            goblin_gang_by_tick[str(tick)]={
                "total":sum(breakdown.values()),
                "breakdown":breakdown,
            }
    # Video: Night Witch placement is ~19.1s and the first Bat is first visible
    # at ~22.0s.  With the replay origin at 18.0s this is tick ~80 (20 Hz).
    expected_first_bat_tick=80
    bat_error_ticks=None if first_bat_tick is None else first_bat_tick-expected_first_bat_tick
    bat_timing_pass=first_bat_tick is not None and abs(bat_error_ticks)<=2
    demolisher_by_tick={}
    for snapshot in snaps:
        tick=int(snapshot["tick"])
        if tick not in {336,345,355,365,385}:
            continue
        rows=[
            {
                "uid":int(entity["uid"]),
                "card":str(entity.get("card_id","")),
                "x":int(entity["x_mtile"]),
                "y":int(entity["y_mtile"]),
                "hp":int(entity["hp"]),
                "deploy_us":int(entity.get("deploy_remaining_us") or 0),
            }
            for entity in snapshot.get("entities",[])
            if "goblindemolisher" in str(entity.get("card_id","")).lower()
            or "goblin-demolisher" in str(entity.get("card_id","")).lower()
        ]
        demolisher_by_tick[str(tick)]=rows
    demolisher_created=bool(demolisher_by_tick.get("336"))

    golden_knight_ability_events=[
        row for row in generated
        if row.get("kind")=="ability_activated"
        and str((row.get("data") or {}).get("card_id","")).lower()=="golden-knight"
    ]

    expected_new_cards={
        "electro-dragon":409,
        "suspicious-bush":479,
        "golden-knight":541,
        "valkyrie":618,
        "golem":948,
        "dart-goblin":990,
        "goblin-cage":1160,
    }
    created_cards={}
    for card,play_tick in expected_new_cards.items():
        seen=[]
        compact_card=card.replace("-","")
        for snapshot in snaps:
            tick=int(snapshot["tick"])
            if tick < play_tick or tick > play_tick+3:
                continue
            for entity in snapshot.get("entities",[]):
                key=str(entity.get("card_id","")).lower().replace("-","")
                if compact_card in key and bool(entity.get("alive",True)):
                    seen.append({
                        "tick":tick,
                        "uid":int(entity["uid"]),
                        "card":str(entity.get("card_id","")),
                        "x":int(entity["x_mtile"]),
                        "y":int(entity["y_mtile"]),
                        "deploy_us":int(entity.get("deploy_remaining_us") or 0),
                    })
        created_cards[card]=seen

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
                "damage_events":dart_damage_events,
                "passed":first_dart_death_tick is not None and 78 <= first_dart_death_tick <= 80,
                "gating":True,
            },
            "skeletons_after_play":{
                "play_tick":48,
                "counts_by_tick":skeleton_counts_by_tick,
                "expected_initial_count":3,
                "passed":skeleton_counts_by_tick.get("49")==3,
                "gating":True,
            },
            "goblin_gang_after_play":{
                "play_tick":189,
                "counts_by_tick":goblin_gang_by_tick,
                "expected_total":6,
                "expected_composition":{"goblin":3,"speargoblin":3},
                "passed":(goblin_gang_by_tick.get("190") or {}).get("total")==6,
                "gating":True,
            },
            "goblin_demolisher_after_play":{
                "play_tick":335,
                "video_time_s":34.75,
                "placement_cell_estimate":[9,8],
                "states_by_tick":demolisher_by_tick,
                "passed":demolisher_created,
                "gating":True,
            },
            "extended_opening_plays":{
                "expected":{
                    "electro-dragon":{"tick":409,"video_time_s":38.45,"cell":[9,18]},
                    "suspicious-bush":{"tick":479,"video_time_s":41.95,"cell":[4,14]},
                    "golden-knight":{"tick":541,"video_time_s":45.05,"cell":[4,13]},
                    "golden-knight-ability":{"tick":574,"video_time_s":46.70},
                    "valkyrie":{"tick":618,"video_time_s":48.90,"cell":[3,24]},
                    "golem":{"tick":948,"video_time_s":65.40,"cell":[9,30]},
                    "dart-goblin-2":{"tick":990,"video_time_s":67.50,"cell":[4,14]},
                    "goblin-cage":{"tick":1160,"video_time_s":76.00,"cell":[9,10]},
                },
                "created":created_cards,
                "ability_events":golden_knight_ability_events,
                "passed":all(created_cards.get(card) for card in expected_new_cards) and bool(golden_knight_ability_events),
                "gating":True,
            },
        },
    }
    (args.out/"opening_probe.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    dart_pass=first_dart_death_tick is not None and 78 <= first_dart_death_tick <= 80
    skeleton_pass=skeleton_counts_by_tick.get("49")==3
    gang_pass=(goblin_gang_by_tick.get("190") or {}).get("total")==6
    extended_pass=all(created_cards.get(card) for card in expected_new_cards) and bool(golden_knight_ability_events)
    return 0 if report["status"]!="failed" and bat_timing_pass and dart_pass and skeleton_pass and gang_pass and demolisher_created and extended_pass else 1

if __name__=="__main__":
    raise SystemExit(main())
