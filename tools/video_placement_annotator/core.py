from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence
import json, math

import cv2
import numpy as np


@dataclass(frozen=True)
class RectN:
    x1: float; y1: float; x2: float; y2: float
    def px(self, w:int, h:int) -> tuple[int,int,int,int]:
        return (round(self.x1*w), round(self.y1*h), round(self.x2*w), round(self.y2*h))

@dataclass
class LayoutConfig:
    top_slots: list[RectN]
    bottom_slots: list[RectN]
    sample_fps: float = 12.0
    stable_samples: int = 3
    hand_threshold: float = 0.43
    # Logical cell-center mapping for this replay UI family.
    grid_origin_norm: tuple[float,float] = (0.0570, 0.2400)
    grid_step_norm: tuple[float,float] = (0.0528, 0.0202)
    hough_min_radius_norm: float = 12/720
    hough_max_radius_norm: float = 24/720
    deploy_lookback_s: float = 0.20
    deploy_lookahead_s: float = 0.85

    @classmethod
    def load(cls, path: str|Path) -> 'LayoutConfig':
        raw=json.loads(Path(path).read_text(encoding='utf-8'))
        def rr(x): return RectN(*map(float,x))
        return cls(
            top_slots=[rr(x) for x in raw['top_slots']],
            bottom_slots=[rr(x) for x in raw['bottom_slots']],
            sample_fps=float(raw.get('sample_fps',12)),
            stable_samples=int(raw.get('stable_samples',3)),
            hand_threshold=float(raw.get('hand_threshold',0.43)),
            grid_origin_norm=tuple(map(float,raw.get('grid_origin_norm',[0.057,0.240]))),
            grid_step_norm=tuple(map(float,raw.get('grid_step_norm',[0.0528,0.0202]))),
            hough_min_radius_norm=float(raw.get('hough_min_radius_norm',12/720)),
            hough_max_radius_norm=float(raw.get('hough_max_radius_norm',24/720)),
            deploy_lookback_s=float(raw.get('deploy_lookback_s',0.20)),
            deploy_lookahead_s=float(raw.get('deploy_lookahead_s',0.85)),
        )


def _prep(img: np.ndarray, size=(64,72)) -> tuple[np.ndarray,np.ndarray]:
    if img is None or img.size == 0:
        raise ValueError('empty image')
    # Ignore borders/elixir badge: central artwork is far more stable between
    # database card images, enabled/disabled hand cards, and replay UI skins.
    h,w=img.shape[:2]
    x1=int(w*.12); x2=int(w*.88); y1=int(h*.08); y2=int(h*.82)
    crop=img[y1:y2,x1:x2]
    crop=cv2.resize(crop,size,interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    gray=cv2.equalizeHist(gray)
    edge=cv2.Canny(gray,60,150)
    return gray,edge

class CardMatcher(Protocol):
    def match(self, crop: np.ndarray, observed_elixir: int | None = None) -> tuple[str,float,float]:
        ...


class CardTemplateMatcher:
    def __init__(self, template_dir: str|Path, allowed: Iterable[str]|None=None):
        allowed=set(allowed or [])
        self.templates: dict[str,tuple[np.ndarray,np.ndarray]]={}
        for p in sorted(Path(template_dir).glob('*')):
            if p.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}: continue
            key=p.stem.lower().replace('_','-')
            if allowed and key not in allowed: continue
            img=cv2.imread(str(p),cv2.IMREAD_COLOR)
            if img is not None: self.templates[key]=_prep(img)
        if not self.templates:
            raise ValueError(f'no card templates loaded from {template_dir}')

    def match(self, crop: np.ndarray, observed_elixir: int | None = None) -> tuple[str,float,float]:
        g,e=_prep(crop)
        scores=[]
        for key,(tg,te) in self.templates.items():
            # Database artwork and in-hand cards differ mostly at borders and in
            # saturation. Equalized intensity + edges is intentionally robust to
            # insufficient-elixir greyscale cards.
            sg=float(cv2.matchTemplate(g,tg,cv2.TM_CCOEFF_NORMED)[0,0])
            se=float(cv2.matchTemplate(e,te,cv2.TM_CCOEFF_NORMED)[0,0])
            scores.append((0.72*sg+0.28*se,key))
        scores.sort(reverse=True)
        best,key=scores[0]
        second=scores[1][0] if len(scores)>1 else -1.0
        # margin is useful when two goblin-ish cards look similar
        conf=max(0.0,min(1.0,0.65*(best+1)/2 + 0.35*max(0.0,best-second)*3))
        return key,conf,best-second


def crop_rect(frame: np.ndarray, rect: RectN) -> np.ndarray:
    h,w=frame.shape[:2]; x1,y1,x2,y2=rect.px(w,h)
    return frame[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]

@dataclass
class HandObservation:
    ordered: tuple[str,...]
    confidence: float
    per_slot: tuple[float,...]


def classify_hand(frame: np.ndarray, slots: Sequence[RectN], matcher: CardMatcher) -> HandObservation:
    keys=[]; cs=[]
    for r in slots:
        k,c,_=matcher.match(crop_rect(frame,r)); keys.append(k); cs.append(c)
    return HandObservation(tuple(keys),float(min(cs)),tuple(cs))


def counter_subtract(a: Sequence[str], b: Sequence[str]) -> list[str]:
    """Multiset a-b in deterministic order."""
    remain=Counter(b); out=[]
    for x in a:
        if remain[x]: remain[x]-=1
        else: out.append(x)
    return out

@dataclass
class HandTransition:
    side: str
    video_time: float
    card: str
    incoming: str|None
    confidence: float
    before: tuple[str,...]
    after: tuple[str,...]
    slot: int | None = None

class StableHandTracker:
    """Turn noisy classifications into fixed-slot card replacements.

    In the supplied Clash Royale replay HUD, the four hand cards do *not* shift
    left/right after a play. The played slot is replaced by the next card. A
    persistent one-slot change therefore directly identifies both the outgoing
    (played) card and the incoming card.
    """
    def __init__(self, side:str, stable_samples:int=3, threshold:float=.43):
        self.side=side; self.n=stable_samples; self.threshold=threshold
        self.hist=deque(maxlen=stable_samples)
        self.stable: HandObservation|None=None
        self.unstable_since: float|None=None

    def push(self,t:float,obs:HandObservation) -> HandTransition|None:
        if obs.confidence < self.threshold:
            if self.unstable_since is None: self.unstable_since=t
            self.hist.clear(); return None
        self.hist.append((t,obs))
        if len(self.hist)<self.n: return None
        ordered=[x[1].ordered for x in self.hist]
        if any(x != ordered[0] for x in ordered[1:]):
            if self.unstable_since is None: self.unstable_since=self.hist[0][0]
            return None
        new=self.hist[-1][1]
        if self.stable is None:
            self.stable=new; self.unstable_since=None; return None
        changed=[i for i,(a,b) in enumerate(zip(self.stable.ordered,new.ordered)) if a!=b]
        if not changed:
            self.stable=new; self.unstable_since=None; return None
        old=self.stable
        if len(changed)!=1:
            # Multi-slot differences are almost always an animation /
            # classification glitch. Do not advance the stable hand on them.
            if self.unstable_since is None: self.unstable_since=self.hist[0][0]
            return None
        slot=changed[0]
        self.stable=new
        t0=self.unstable_since if self.unstable_since is not None else self.hist[0][0]
        te=(t0+self.hist[0][0])/2
        self.unstable_since=None
        conf=min(old.per_slot[slot],new.per_slot[slot])
        return HandTransition(
            self.side,te,old.ordered[slot],new.ordered[slot],conf,
            old.ordered,new.ordered,slot=slot
        )


def pixel_to_cell(x:float,y:float,w:int,h:int,cfg:LayoutConfig) -> tuple[int,int,float]:
    ox=cfg.grid_origin_norm[0]*w; oy=cfg.grid_origin_norm[1]*h
    sx=cfg.grid_step_norm[0]*w; sy=cfg.grid_step_norm[1]*h
    xf=(x-ox)/sx; yf=(y-oy)/sy
    xi=int(round(xf)); yi=int(round(yf))
    # residual in cell units: doubles as geometric confidence input
    residual=math.hypot(xf-xi,yf-yi)
    return max(0,min(17,xi)),max(0,min(31,yi)),residual


def default_layout() -> LayoutConfig:
    # Full card faces in the 720x1600 dual-hand replay HUD.
    xs=[(.133,.254),(.261,.389),(.397,.518),(.525,.654)]
    top=[RectN(a,.077,b,.148) for a,b in xs]
    bottom=[RectN(a,.891,b,.967) for a,b in xs]
    return LayoutConfig(top,bottom)

# --- Replay deployment-marker matcher ---------------------------------------
# The spectator/replay UI used by the supplied demo draws a small analog clock
# at the exact deployment point while a troop/building is spawning. Matching
# that marker is substantially more accurate than following the unit after it
# starts to move.
def _clock_template(side: str) -> np.ndarray:
    name='deployment_clock_team.png' if side=='team' else 'deployment_clock_opponent.png'
    img=cv2.imread(str(Path(__file__).resolve().with_name(name)),cv2.IMREAD_COLOR)
    if img is None: raise RuntimeError(f'deployment-clock template missing: {name}')
    return img


def _template_hits(frame:np.ndarray, tpl:np.ndarray, threshold:float=.58, max_hits:int=8):
    h,w=frame.shape[:2]
    scale=w/720.0
    tw=max(20,round(tpl.shape[1]*scale)); th=max(20,round(tpl.shape[0]*scale))
    tt=cv2.resize(tpl,(tw,th),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_CUBIC)
    roi_y1=max(0,round(h*.20)); roi_y2=min(h,round(h*.89))
    gray=cv2.cvtColor(frame[roi_y1:roi_y2],cv2.COLOR_BGR2GRAY)
    tg=cv2.cvtColor(tt,cv2.COLOR_BGR2GRAY)
    if gray.shape[0]<tg.shape[0] or gray.shape[1]<tg.shape[1]: return []
    res=cv2.matchTemplate(gray,tg,cv2.TM_CCOEFF_NORMED)
    hits=[]; rr=res.copy()
    for _ in range(max_hits):
        _,mx,_,loc=cv2.minMaxLoc(rr)
        if mx < threshold: break
        cx=loc[0]+tw/2; cy=loc[1]+th/2+roi_y1
        hits.append((float(mx),float(cx),float(cy)))
        x1=max(0,loc[0]-tw//2); y1=max(0,loc[1]-th//2)
        x2=min(rr.shape[1]-1,loc[0]+tw//2); y2=min(rr.shape[0]-1,loc[1]+th//2)
        rr[y1:y2+1,x1:x2+1]=-1
    return hits


def locate_deployment_clock(video_path:str|Path, t:float, cfg:LayoutConfig, side:str|None=None) -> tuple[int,int,float,tuple[float,float]|None]:
    side=side or 'team'
    tpl=_clock_template(side)
    cap=cv2.VideoCapture(str(video_path))
    if not cap.isOpened(): raise OSError(f'cannot open {video_path}')
    fps=float(cap.get(cv2.CAP_PROP_FPS) or 30)
    # Hand-state confirmation can lag the actual click/release slightly. Build
    # baseline before that uncertainty window, then search through it.
    search_start=max(0.0,t-.34); baseline_start=max(0.0,t-.70); end=t+1.00
    cap.set(cv2.CAP_PROP_POS_MSEC,baseline_start*1000)
    baseline=[]; observations=[]; shape=None; frame_no=0
    stride=max(1,round(fps/20.0))
    while True:
        ok,fr=cap.read()
        if not ok: break
        now=float(cap.get(cv2.CAP_PROP_POS_MSEC))/1000.0
        if now>end: break
        frame_no+=1
        if frame_no%stride: continue
        shape=fr.shape[:2]
        hits=_template_hits(fr,tpl)
        if now < search_start-.03:
            baseline.extend((x,y) for s,x,y in hits if s>=.58)
        elif now>=search_start:
            observations.append((now,hits))
    cap.release()
    if shape is None: return -1,-1,0.0,None
    h,w=shape; tol=max(16.0,w*.035)
    def in_baseline(x,y): return any(math.hypot(x-bx,y-by)<=tol for bx,by in baseline)
    clusters=[]
    for now,hits in observations:
        for raw,x,y in hits:
            if in_baseline(x,y): continue
            cx,cy,res=pixel_to_cell(x,y,w,h,cfg)
            if side=='team' and cy<16: continue
            if side=='opponent' and cy>15: continue
            cl=next((z for z in clusters if math.hypot(x-z['x'],y-z['y'])<=tol),None)
            if cl is None:
                clusters.append({'x':x,'y':y,'n':1,'best':raw,'first':now,'last':now})
            else:
                n=cl['n']; cl['x']=(cl['x']*n+x)/(n+1); cl['y']=(cl['y']*n+y)/(n+1)
                cl['n']=n+1; cl['best']=max(cl['best'],raw); cl['last']=now
    if not clusters: return -1,-1,0.0,None
    best=None
    for cl in clusters:
        cx,cy,res=pixel_to_cell(cl['x'],cl['y'],w,h,cfg)
        persist=min(1.0,cl['n']/3.0)
        geom=max(0.0,1.0-res/.85)
        score=.60*cl['best']+.25*persist+.15*geom
        if cl['n']==1: score*=.78
        cand=(score,cx,cy,(cl['x'],cl['y']))
        if best is None or cand[0]>best[0]: best=cand
    return best[1],best[2],float(min(1,best[0])),best[3]


def locate_effect_change(video_path:str|Path,t:float,cfg:LayoutConfig) -> tuple[int,int,float,tuple[float,float]|None]:
    """Fallback for spells that do not draw a deployment clock.

    Returns the strongest compact *new* visual effect in the 1.15 s following
    the hand transition. This is intentionally lower confidence than the clock
    marker and should remain reviewable in output.
    """
    cap=cv2.VideoCapture(str(video_path))
    if not cap.isOpened(): return -1,-1,0.0,None
    fps=float(cap.get(cv2.CAP_PROP_FPS) or 30)
    # Pull a short sequence by seek; only ~25 frames are needed per uncertain event.
    times=np.arange(max(0,t-.35),t+1.16,.05)
    frames=[]
    for tt in times:
        cap.set(cv2.CAP_PROP_POS_MSEC,float(tt*1000)); ok,fr=cap.read()
        if ok: frames.append((float(tt),fr))
    cap.release()
    if len(frames)<4: return -1,-1,0.0,None
    h,w=frames[0][1].shape[:2]
    ox=cfg.grid_origin_norm[0]*w; oy=cfg.grid_origin_norm[1]*h
    sx=cfg.grid_step_norm[0]*w; sy=cfg.grid_step_norm[1]*h
    y1=max(0,round(oy-sy*.75)); y2=min(h,round(oy+sy*31.75))
    pre_maps=[]; candidates=[]
    prev_t,prev=frames[0]; prevg=cv2.cvtColor(prev,cv2.COLOR_BGR2GRAY)
    for now,fr in frames[1:]:
        g=cv2.cvtColor(fr,cv2.COLOR_BGR2GRAY)
        d=cv2.absdiff(g,prevg).astype(np.float32)
        d[:y1]=0; d[y2:]=0
        energy=cv2.GaussianBlur(d,(0,0),sigmaX=max(8,sx*.42),sigmaY=max(8,sy*.55))
        if now < t-.05:
            pre_maps.append(energy)
        elif now >= t-.03:
            candidates.append((now,energy))
        prevg=g
    if not candidates: return -1,-1,0.0,None
    baseline=np.median(np.stack(pre_maps),axis=0) if pre_maps else 0
    best=None
    for now,en in candidates:
        novelty=np.maximum(0,en-(baseline*1.25 if isinstance(baseline,np.ndarray) else 0))
        _,mx,_,loc=cv2.minMaxLoc(novelty)
        # Prefer earlier causal changes when strengths are comparable.
        temporal=max(.65,1-(now-t)*.25)
        sc=float(mx)*temporal
        if best is None or sc>best[0]: best=(sc,float(mx),loc,now)
    sc,mx,(x,y),now=best
    cx,cy,res=pixel_to_cell(x,y,w,h,cfg)
    # Absolute energy varies by recording; map to conservative 0..0.72.
    conf=min(.72,max(.10,(mx-25)/120)) * max(.45,1-res/.9)
    return cx,cy,float(conf),(float(x),float(y))