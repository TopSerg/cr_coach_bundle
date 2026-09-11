#!/usr/bin/env python3
"""Probe PRIMARY annotations without treating an isolated clip as full truth."""
import argparse
import json
from pathlib import Path
from simulate import ROOT, prepare_imports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'examples/hog_cannon_primary.json')
    parser.add_argument('--reference',type=Path,default=ROOT/'physical_tests/references/d03_hog_cannon_02_primary.json')
    parser.add_argument('--out',type=Path,default=ROOT/'outputs/demo_comparison')
    args=parser.parse_args()
    prepare_imports()
    from cr_coach.replay.io import load_replay
    from cr_coach.runtime.runner import run_replay, write_json
    from cr_coach.validation.event_times import hog_cannon_metrics,compare_event_times
    spec=load_replay(args.input)
    report=run_replay(spec,args.out,sample_ticks=1)
    events=[json.loads(l) for l in (args.out/'events.jsonl').read_text().splitlines()]
    actual=hog_cannon_metrics(events)
    reference=json.loads(args.reference.read_text())
    expected={k:reference['events_relative_to_hog_play_s'][k] for k in ('hog_hits_cannon','cannon_death','hog_death')}
    comparison=compare_event_times(expected,actual,reference['comparison_tolerance_s'])
    result=dict(reference_id=reference['id'],ruleset_id=report['ruleset_id'],simulation=actual,**comparison)
    result['reference_complete']=False
    result['certified_real_game_fidelity']=False
    result['limitations']=[
        'The isolated input omits the concurrent left-lane push visible in PRIMARY.',
        'Mapped cells are approximate; see docs/SIMULATOR_AUDIT_RU.md.',
        'Events on tick N are compared at first observable state boundary (N+1)/20 s.'
    ]
    write_json(args.out/'comparison.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if comparison['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
