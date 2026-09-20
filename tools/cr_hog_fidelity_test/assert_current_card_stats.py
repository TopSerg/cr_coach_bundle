#!/usr/bin/env python3
"""Strict coverage gate for the current public Clash Royale card stat overlay."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def ids(record: dict[str, Any]) -> set[str]:
    return {norm(record.get(k)) for k in ("key", "name", "name_en", "sc_key") if record.get(k)}


def find(records: list[dict[str, Any]], *selectors: str) -> dict[str, Any] | None:
    wanted={norm(x) for x in selectors if x}
    for record in records:
        if ids(record) & wanted:
            return record
    return None


def lv11(record: dict[str, Any], array_field: str, scalar_field: str) -> int | None:
    arr=record.get(array_field)
    if isinstance(arr,list) and len(arr)>10 and arr[10] is not None:
        return int(arr[10])
    value=record.get(scalar_field)
    return None if value is None else int(value)


def find_spell_projectile(
    projectiles: list[dict[str, Any]],
    registry_record: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not registry_record:
        return None
    sk=str(registry_record.get("sc_key") or "")
    if not sk:
        return None
    for candidate in (f"{sk}Spell",f"{sk}Projectile",f"{sk}ProjectileRolling",sk):
        found=find(projectiles,candidate)
        if found is not None:
            return found
    wanted=norm(sk)
    candidates=[
        p for p in projectiles
        if wanted and wanted in norm(p.get("name"))
        and (int(p.get("damage") or 0)>0 or int(p.get("spawn_character_count") or 0)>0)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p:int(p.get("damage") or 0)+int(p.get("spawn_character_count") or 0)*100,
    )


def require(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--data-dir",required=True)
    ap.add_argument("--catalog",default=str(Path(__file__).with_name("current_card_stats_2026_09.json")))
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    data_dir=Path(args.data_dir).resolve()
    root=data_dir/"royaleapi"
    catalog=load(Path(args.catalog).resolve())
    manifest=load(data_dir/"CURRENT_CARD_STATS_MANIFEST.json")
    registry=load(root/"cards.json")
    characters=load(root/"cards_stats_characters.json")
    buildings=load(root/"cards_stats_building.json")
    spells=load(root/"cards_stats_spell.json")
    projectiles=load(root/"cards_stats_projectile.json")

    base=[(k,v) for k,v in catalog["cards"].items() if not v.get("evolution") and not v.get("hero")]
    evolutions=[k for k,v in catalog["cards"].items() if v.get("evolution")]
    heroes=[k for k,v in catalog["cards"].items() if v.get("hero")]
    failures:list[str]=[]

    require(len(base)==123,f"base catalog count={len(base)}, expected 123",failures)
    require(len(evolutions)==42,f"evolution count={len(evolutions)}, expected 42",failures)
    require(len(heroes)==17,f"hero count={len(heroes)}, expected 17",failures)
    require(len(catalog["cards"])==182,f"total catalog count={len(catalog['cards'])}, expected 182",failures)
    cross=catalog["meta"].get("official_api_crosscheck") or {}
    require(cross.get("matched_base_cards")==123,"official API cross-check is not 123/123",failures)
    require(not cross.get("missing"),f"official API cross-check missing={cross.get('missing')}",failures)

    missing_registry=[]
    missing_runtime=[]
    for key,stat in base:
        selectors=(key.replace("_","-"),stat.get("display",""))
        registry_record=find(registry,*selectors)
        if registry_record is None:
            missing_registry.append(key)
        direct_runtime=(
            find(characters,*selectors)
            or find(buildings,*selectors)
            or find(spells,*selectors)
        )
        projectile_runtime=(
            find_spell_projectile(projectiles,registry_record)
            if stat.get("kind")=="spell" else None
        )
        if direct_runtime is None and projectile_runtime is None:
            missing_runtime.append(key)
    require(not missing_registry,f"missing registry cards: {missing_registry}",failures)
    require(not missing_runtime,f"missing runtime stat records: {missing_runtime}",failures)
    require(len(manifest.get("runtime_records_patched",[]))==123,
            f"overlay patched {len(manifest.get('runtime_records_patched',[]))}/123 runtime rows",failures)

    def char(key:str,display:str) -> dict[str,Any] | None:
        return find(characters,key,display) or find(buildings,key,display)

    # Internal identity must stay data-driven. Display names are not safe SC keys
    # (Magic Archer is EliteArcher in Supercell/Rudy data).
    magic_registry=find(registry,"magic-archer","Magic Archer")
    require(magic_registry is not None,"Magic Archer registry record missing",failures)
    if magic_registry:
        require(
            magic_registry.get("sc_key")=="EliteArcher",
            f"Magic Archer sc_key changed to {magic_registry.get('sc_key')!r}",
            failures,
        )

    # Current Cannon value after the April 2026 official nerf is 202 at Level 11.
    cannon=char("cannon","Cannon")
    require(cannon is not None,"Cannon runtime record missing",failures)
    if cannon:
        require(lv11(cannon,"hitpoints_per_level","hitpoints")==824,"Cannon HP != 824",failures)
        cannon_projectile=find(projectiles,str(cannon.get("projectile") or ""))
        require(cannon_projectile is not None,"Cannon projectile missing",failures)
        if cannon_projectile:
            require(
                lv11(cannon_projectile,"damage_per_level","damage")==202,
                "Cannon Level-11 damage != 202",
                failures,
            )

    three=catalog["cards"].get("three_musketeers") or {}
    require(three.get("melee_damage")==314,"Three Musketeers melee damage != 314",failures)
    require(three.get("melee_range_tiles")==1.6,"Three Musketeers melee range != 1.6 tiles",failures)
    require(three.get("melee_hit_speed")==1.3,"Three Musketeers melee hit speed != 1.3s",failures)

    # Screenshot/public-stat anchor: Electro Spirit.
    es=char("electro-spirit","Electro Spirit")
    require(es is not None,"Electro Spirit runtime record missing",failures)
    if es:
        require(lv11(es,"hitpoints_per_level","hitpoints")==215,"Electro Spirit HP != 215",failures)
        require(lv11(es,"damage_per_level","damage")==99,"Electro Spirit damage != 99",failures)
        require(int(es.get("range",0))==2500,"Electro Spirit range != 2.5 tiles",failures)
        p=find(projectiles,str(es.get("projectile") or ""))
        require(p is not None,"Electro Spirit projectile missing",failures)
        if p:
            require(int(p.get("chained_hit_count",0))==9,"Electro Spirit chain count != 9",failures)
            require(int(p.get("chained_hit_radius",0))==3000,"Electro Spirit chain range != 3 tiles (Aug 26 current patch)",failures)

    checks=[
        ("fire-spirit","Fire Spirit","damage_per_level","damage",215),
        ("ice-golem","Ice Golem","hitpoints_per_level","hitpoints",1228),
        ("wizard","Wizard","damage_per_level","damage",304),
        ("bomber","Bomber","damage_per_level","damage",212),
    ]
    for key,display,arr,scalar,expected in checks:
        rec=char(key,display)
        require(rec is not None,f"{display} runtime record missing",failures)
        if rec:
            require(lv11(rec,arr,scalar)==expected,f"{display} current value != {expected}",failures)

    z=char("zappies","Zappies")
    require(z is not None and int(z.get("hit_speed",0))==2300,"Zappies hit speed != 2.3s",failures)

    golem=char("golem","Golem")
    require(golem is not None and int(golem.get("sight_range",0))==7500,"Golem sight != 7.5 tiles",failures)
    br=char("battle-ram","Battle Ram")
    require(br is not None and int(br.get("sight_range",0))==6500,"Battle Ram sight != 6.5 tiles",failures)

    mg=char("minion-giant","Minion Giant")
    require(mg is not None,"Minion Giant runtime stub missing",failures)
    if mg:
        require(lv11(mg,"hitpoints_per_level","hitpoints")==1817,"Minion Giant HP != 1817",failures)
        require(lv11(mg,"damage_per_level","damage")==168,"Minion Giant damage != 168",failures)
        require(int(mg.get("hit_speed",0))==1500,"Minion Giant hit speed != 1.5s",failures)
        require(int(mg.get("range",0))==4000,"Minion Giant range != 4.0 tiles",failures)
        require(bool(mg.get("target_only_buildings")),"Minion Giant must target buildings",failures)
        require(int(mg.get("flying_height",0))>0,"Minion Giant must be flying",failures)

    ronin=char("ronin","Ronin")
    require(ronin is not None,"Ronin runtime stub missing",failures)
    if ronin:
        require(lv11(ronin,"hitpoints_per_level","hitpoints")==1779,"Ronin HP != 1779",failures)
        require(lv11(ronin,"damage_per_level","damage")==337,"Ronin damage != 337",failures)
        require(int(ronin.get("hit_speed",0))==1300,"Ronin hit speed != 1.3s",failures)

    fireball_registry=find(registry,"fireball","Fireball")
    fireball=find_spell_projectile(projectiles,fireball_registry)
    require(fireball is not None,"Fireball projectile-spell record missing",failures)
    if fireball:
        require(lv11(fireball,"damage_per_level","damage")==688,
                "Fireball Level-11 damage != 688",failures)
        require(int(fireball.get("crown_tower_damage_percent",999))==-77,
                "Fireball current crown-tower reduction should encode 159/688 ~= -77%",failures)

    result={
        "status":"FAIL" if failures else "PASS",
        "catalog":{
            "snapshot":catalog["meta"]["snapshot_date"],
            "base":len(base),"evolutions":len(evolutions),"heroes":len(heroes),
            "total":len(catalog["cards"]),
        },
        "runtime":{
            "registry_cards":len(registry),
            "patched_base_records":len(manifest.get("runtime_records_patched",[])),
            "generated_stubs":manifest.get("runtime_stubs_created",[]),
            "missing_registry":missing_registry,
            "missing_runtime":missing_runtime,
        },
        "failures":failures,
    }
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if failures:
        raise SystemExit("; ".join(failures))


if __name__=="__main__":
    main()
