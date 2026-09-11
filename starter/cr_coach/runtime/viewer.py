"""Generate a self-contained, deterministic replay viewer.

The HTML deliberately embeds a compact projection of the authoritative trace.
That makes it usable from a ``file://`` URL on Windows without a web server,
while ``snapshots.jsonl`` and ``events.jsonl`` remain the full machine-readable
artifacts next to it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _entity(value: Any) -> dict[str, Any]:
    """Keep only fields used by the canvas and inspector."""

    fields = (
        "uid",
        "card_id",
        "kind",
        "role",
        "owner",
        "alive",
        "hp",
        "max_hp",
        "x_mtile",
        "y_mtile",
        "target_uid",
        "pending_target_uid",
        "deploy_remaining_us",
        "river_airborne_active",
    )
    return {name: _get(value, name) for name in fields if _get(value, name) is not None}


def _projectile(value: Any) -> dict[str, Any]:
    fields = (
        "uid",
        "source_card_id",
        "source_uid",
        "target_uid",
        "owner",
        "alive",
        "x_mtile",
        "y_mtile",
    )
    return {name: _get(value, name) for name in fields if _get(value, name) is not None}


def _player(value: Any) -> dict[str, Any]:
    fields = ("crowns", "elixir_milli", "hand", "draw_pile", "last_played_card_id")
    return {name: _get(value, name) for name in fields if _get(value, name) is not None}


def _snapshot(value: Any) -> dict[str, Any]:
    tick = int(_get(value, "tick", _get(value, "state_tick", 0)))
    elapsed_us = _get(value, "elapsed_us", tick * 50_000)
    return {
        "tick": tick,
        "elapsed_us": int(elapsed_us),
        "phase": _get(value, "phase"),
        "terminal": bool(_get(value, "terminal", False)),
        "winner": _get(value, "winner"),
        "entities": [_entity(row) for row in (_get(value, "entities", ()) or ())],
        "projectiles": [_projectile(row) for row in (_get(value, "projectiles", ()) or ())],
        "players": [_player(row) for row in (_get(value, "players", ()) or ())],
    }


def _json_for_script(value: Any) -> str:
    # Escaping '<' prevents data containing ``</script>`` from ending the
    # inline script.  U+2028/U+2029 are escaped for older JavaScript parsers.
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def write_viewer(
    path: str | Path,
    *,
    snapshots: Iterable[Any],
    events: Iterable[Any],
    report: Mapping[str, Any] | Any,
) -> Path:
    """Write an offline HTML player and return its path."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    compact_snapshots = [_snapshot(row) for row in snapshots]
    compact_events = list(events)
    payload = {
        "snapshots": compact_snapshots,
        "events": compact_events,
        "report": dict(report) if isinstance(report, Mapping) else report,
    }
    html = _HTML.replace("__REPLAY_DATA__", _json_for_script(payload))
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(html, encoding="utf-8", newline="\n")
        temporary.replace(destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination


_HTML = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CR Coach Replay</title>
<style>
:root{color-scheme:dark;--panel:#172033;--line:#33415d;--text:#eef3ff;--muted:#9fabc2;--blue:#57a6ff;--red:#ff6577}
*{box-sizing:border-box}body{margin:0;background:#0d1422;color:var(--text);font:14px system-ui,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:18px;margin:0}.muted{color:var(--muted)}main{display:grid;grid-template-columns:minmax(300px,580px) minmax(280px,1fr);gap:14px;padding:14px;max-width:1180px;margin:auto}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}canvas{display:block;width:100%;aspect-ratio:18/32;background:#6eaa54;border-radius:7px}
.controls{display:grid;grid-template-columns:auto 1fr auto auto;gap:8px;align-items:center;margin-top:10px}button,select{background:#26334b;color:var(--text);border:1px solid #435372;border-radius:6px;padding:7px 10px}input[type=range]{width:100%}
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:10px}.stat{background:#111a2a;border-radius:7px;padding:8px}.stat b{display:block;font-size:16px}
#entities{width:100%;border-collapse:collapse}th,td{text-align:left;padding:5px;border-bottom:1px solid #293751;font-size:12px}#events{height:270px;overflow:auto;background:#101827;border-radius:7px;padding:6px}.event{padding:4px 6px;border-bottom:1px solid #26334b}.team{color:#8bc5ff}.opponent{color:#ff9aa6}
.warning{color:#ffd36a}@media(max-width:760px){main{grid-template-columns:1fr}.controls{grid-template-columns:auto 1fr auto}}
</style>
</head>
<body>
<header><h1>CR Coach Replay</h1><span id="battle"></span><span id="status" class="muted"></span></header>
<main>
<section class="panel">
<canvas id="arena" width="540" height="960" aria-label="Clash Royale arena"></canvas>
<div class="controls"><button id="play">▶</button><input id="seek" type="range" min="0" value="0"><select id="speed"><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select><b id="clock">0.00 s</b></div>
</section>
<aside class="panel">
<div class="stats"><div class="stat"><span class="muted">Tick</span><b id="tick">0</b></div><div class="stat"><span class="muted">Phase</span><b id="phase">—</b></div><div class="stat"><span class="muted">Team</span><b id="team">—</b></div><div class="stat"><span class="muted">Opponent</span><b id="opponent">—</b></div></div>
<table><thead><tr><th>UID</th><th>Card</th><th>Side</th><th>HP</th><th>Target</th></tr></thead><tbody id="entities"></tbody></table>
<h3>События рядом с кадром</h3><div id="events"></div>
<p class="muted">Полные данные: snapshots.jsonl и events.jsonl. Этот файл автономен и не обращается к сети.</p>
</aside>
</main>
<script>
'use strict';
const DATA=__REPLAY_DATA__;
const frames=DATA.snapshots, events=DATA.events, report=DATA.report||{};
const canvas=document.getElementById('arena'),ctx=canvas.getContext('2d'),seek=document.getElementById('seek');
let index=0,playing=false,last=0,carry=0;
seek.max=Math.max(0,frames.length-1);document.getElementById('battle').textContent=report.battle_id||'replay';
document.getElementById('status').textContent=[report.status,report.physics_profile,report.fidelity].filter(Boolean).join(' · ');
function xy(x,y){return [x/18000*canvas.width,y/32000*canvas.height]}
function short(s){return String(s||'?').replaceAll('-',' ')}
function arena(){
 const w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);ctx.fillStyle='#72aa56';ctx.fillRect(0,0,w,h);
 ctx.fillStyle='#3c88c9';ctx.fillRect(0,h*14/32,w,h*4/32);ctx.fillStyle='#c9aa69';ctx.fillRect(w*2/18,h*14/32,w*3/18,h*4/32);ctx.fillRect(w*13/18,h*14/32,w*3/18,h*4/32);
 ctx.strokeStyle='rgba(255,255,255,.09)';ctx.lineWidth=1;for(let x=1;x<18;x++){ctx.beginPath();ctx.moveTo(x*w/18,0);ctx.lineTo(x*w/18,h);ctx.stroke()}for(let y=1;y<32;y++){ctx.beginPath();ctx.moveTo(0,y*h/32);ctx.lineTo(w,y*h/32);ctx.stroke()}
}
function sideClass(owner){return Number(owner)===0?'team':'opponent'}
function draw(){
 if(!frames.length){arena();ctx.fillStyle='white';ctx.fillText('No snapshots',20,30);return}
 const f=frames[index];arena();const live=(f.entities||[]).filter(e=>e.alive!==false),byUid=new Map(live.map(e=>[Number(e.uid),e]));
 ctx.lineWidth=2;for(const e of live){const target=byUid.get(Number(e.target_uid??e.pending_target_uid));if(!target)continue;const a=xy(e.x_mtile,e.y_mtile),b=xy(target.x_mtile,target.y_mtile);ctx.strokeStyle=Number(e.owner)===0?'rgba(87,166,255,.5)':'rgba(255,101,119,.5)';ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}
 for(const e of live){const [x,y]=xy(e.x_mtile,e.y_mtile),tower=e.kind==='tower',r=tower?19:(e.kind==='building'?15:12);ctx.fillStyle=Number(e.owner)===0?'#4d9cf2':'#f25569';ctx.strokeStyle=e.river_airborne_active?'#fff4a6':'#101827';ctx.lineWidth=e.river_airborne_active?4:2;ctx.beginPath();tower?ctx.rect(x-r,y-r,r*2,r*2):ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.fillStyle='white';ctx.textAlign='center';ctx.font='bold 10px system-ui';ctx.fillText(short(e.card_id).split(' ')[0],x,y+3);if(e.max_hp){ctx.fillStyle='#172033';ctx.fillRect(x-r,y-r-8,r*2,4);ctx.fillStyle='#74e08b';ctx.fillRect(x-r,y-r-8,r*2*Math.max(0,e.hp)/e.max_hp,4)}}
 for(const p of f.projectiles||[]){if(p.alive===false||p.x_mtile==null)continue;const [x,y]=xy(p.x_mtile,p.y_mtile);ctx.fillStyle='#ffe278';ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill()}
 document.getElementById('tick').textContent=f.tick;document.getElementById('clock').textContent=(f.elapsed_us/1e6).toFixed(2)+' s';document.getElementById('phase').textContent=f.terminal?'terminal':(f.phase||'—');
 for(const [n,id] of [[0,'team'],[1,'opponent']]){const p=(f.players||[])[n]||{};document.getElementById(id).textContent=p.elixir_milli==null?'physical only':`${(p.elixir_milli/1000).toFixed(2)} elixir · ${p.crowns??0} crowns`}
 document.getElementById('entities').innerHTML=live.map(e=>`<tr><td>${e.uid}</td><td>${short(e.card_id)}</td><td class="${sideClass(e.owner)}">${sideClass(e.owner)}</td><td>${e.hp??'—'}/${e.max_hp??'—'}</td><td>${e.target_uid??e.pending_target_uid??'—'}</td></tr>`).join('');
 const nearby=events.filter(e=>Math.abs(Number(e.state_tick??e.tick??0)-Number(f.tick))<=20).slice(-40);document.getElementById('events').innerHTML=nearby.map(e=>`<div class="event"><b>${((e.tick??0)/20).toFixed(2)}</b> ${short(e.kind)} <span class="muted">${escapeHtml(JSON.stringify(e.data||{}))}</span></div>`).join('')||'<span class="muted">Нет событий ±1 с</span>';
 seek.value=index;
}
function escapeHtml(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function animate(now){if(!playing)return;const speed=Number(document.getElementById('speed').value);if(!last)last=now;carry+=(now-last)*speed;last=now;while(carry>=50&&index<frames.length-1){index++;carry-=50}draw();if(index>=frames.length-1){playing=false;document.getElementById('play').textContent='▶';return}requestAnimationFrame(animate)}
document.getElementById('play').addEventListener('click',()=>{playing=!playing;document.getElementById('play').textContent=playing?'❚❚':'▶';last=0;if(playing){if(index>=frames.length-1)index=0;requestAnimationFrame(animate)}});
seek.addEventListener('input',()=>{index=Number(seek.value);carry=0;draw()});document.addEventListener('keydown',e=>{if(e.key==='ArrowRight'){index=Math.min(frames.length-1,index+1);draw()}if(e.key==='ArrowLeft'){index=Math.max(0,index-1);draw()}if(e.key===' '){e.preventDefault();document.getElementById('play').click()}});draw();
</script>
</body></html>
'''


__all__ = ["write_viewer"]
