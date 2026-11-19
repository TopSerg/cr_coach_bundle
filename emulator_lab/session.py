"""Session configuration, frame capture, controlled ADB actions and replay export."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
from typing import Any

from . import adb as adb_api

TPS = 20
NS_PER_TICK = 50_000_000
SIDES = ("team", "opponent")


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict) or set(config.get("devices", {})) != set(SIDES):
        raise ValueError("config.devices must contain team and opponent")
    if config.get("calibration_confirmed") is not True:
        raise ValueError("set calibration_confirmed=true only after measuring both emulator screens")
    serials = []
    for side in SIDES:
        dev = config["devices"][side]
        serials.append(dev.get("serial"))
        rect = dev.get("arena_rect_px")
        slots = dev.get("hand_slots_px")
        if not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect) or rect[0] >= rect[2] or rect[1] >= rect[3]:
            raise ValueError(f"{side}.arena_rect_px must be [left,top,right,bottom] with increasing boundaries")
        if not isinstance(slots, list) or len(slots) != 4 or any(not isinstance(p, list) or len(p) != 2 or any(type(v) is not int or v < 0 for v in p) for p in slots):
            raise ValueError(f"{side}.hand_slots_px must contain four [x,y] pixel positions")
        for roi in dev.get("tower_hp_rois", []):
            if roi.get("owner") not in (0, 1) or roi.get("role") not in ("left", "right", "king") or not isinstance(roi.get("rect"), list) or len(roi["rect"]) != 4:
                raise ValueError("tower_hp_rois must specify owner 0/1, role, and rect")
    if not all(isinstance(s, str) and s for s in serials) or serials[0] == serials[1]:
        raise ValueError("two distinct device serials required")


def create_session(config_path: Path, directory: Path, adb: str = "adb", check_devices: bool = True) -> dict:
    config = read_json(config_path)
    validate_config(config)
    if check_devices:
        adb_api.require_pair(adb, [config["devices"][side]["serial"] for side in SIDES])
    if (directory / "config.json").exists():
        raise FileExistsError(f"session already exists: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory / "config.json", config)
    meta = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(), "ticks_per_second": TPS,
            "clock": "host time.time_ns; ADB send/ack brackets; not a game-server clock"}
    atomic_json(directory / "session.json", meta)
    return meta


def start_match(directory: Path, *, now_ns: int | None = None) -> dict:
    file = directory / "match_start.json"
    if file.exists():
        raise FileExistsError("match start is already marked; use a new session for another battle")
    if not (directory / "config.json").exists():
        raise ValueError("run init first")
    data = {"start_utc_ns": time.time_ns() if now_ns is None else now_ns,
            "source": "operator marker (approximate); calibrate against HUD clock for precise ticks"}
    atomic_json(file, data)
    return data


def screen_cell_to_px(config: dict, side: str, x: int, y: int) -> tuple[int, int]:
    if side not in SIDES or not (0 <= x < 18 and 0 <= y < 32) or type(x) is not int or type(y) is not int:
        raise ValueError("world cells must be x=0..17, y=0..31 and side team/opponent")
    # Every emulator shows its OWN towers at the bottom; opponent's view is rotated 180 degrees.
    local_x, local_y = (17 - x, 31 - y) if side == "opponent" else (x, y)
    left, top, right, bottom = config["devices"][side]["arena_rect_px"]
    return (round(left + (local_x + 0.5) * (right - left) / 18),
            round(top + (local_y + 0.5) * (bottom - top) / 32))


def record_action(directory: Path, side: str, card: str, slot: int, x: int, y: int,
                  adb: str = "adb", delay_s: float = 0.12) -> dict:
    config = read_json(directory / "config.json")
    start = read_json(directory / "match_start.json")["start_utc_ns"]
    validate_config(config)
    if side not in SIDES or not isinstance(card, str) or not card.strip() or type(slot) is not int or slot not in range(4):
        raise ValueError("side, nonempty card and hand slot 0..3 required")
    if not (0 <= delay_s <= 2):
        raise ValueError("delay must be 0..2 seconds")
    serial = config["devices"][side]["serial"]
    sx, sy = config["devices"][side]["hand_slots_px"][slot]
    dx, dy = screen_cell_to_px(config, side, x, y)
    adb_api.tap(adb, serial, sx, sy)
    time.sleep(delay_s)
    before_ns = time.time_ns()
    try:
        adb_api.tap(adb, serial, dx, dy)
        sent = True
        error = None
    except adb_api.ADBError as exc:
        sent = False
        error = str(exc)
    after_ns = time.time_ns()
    midpoint = (before_ns + after_ns) // 2
    entry = {"side": side, "serial": serial, "card": card.strip(), "slot": slot, "world_cell": [x, y],
             "tap_px": [dx, dy], "placement_send_ns": before_ns, "placement_ack_ns": after_ns,
             "estimated_tick": round((midpoint - start) / NS_PER_TICK),
             "timing_uncertainty_ticks": (after_ns - before_ns) / (2 * NS_PER_TICK),
             "adb_command_sent": sent, "game_accepted_unverified": True, "error": error}
    atomic_json(directory / "actions" / f"{midpoint}_{uuid.uuid4().hex}.json", entry)
    if not sent:
        raise adb_api.ADBError(str(error))
    return entry


def capture_frames(directory: Path, duration_s: float, interval_s: float = 0.5, adb: str = "adb") -> int:
    if duration_s <= 0 or interval_s < 0.1:
        raise ValueError("duration must be >0 and sample interval >=0.1 seconds")
    config = read_json(directory / "config.json")
    validate_config(config)
    adb_api.require_pair(adb, [config["devices"][side]["serial"] for side in SIDES])
    end = time.monotonic() + duration_s
    seq = 0

    def once(side: str, count: int) -> None:
        serial = config["devices"][side]["serial"]
        begin = time.time_ns()
        data = adb_api.png(adb, serial)
        finish = time.time_ns()
        rel = Path("frames") / side / f"{count:06d}"
        png_file = directory / rel.with_suffix(".png")
        png_file.parent.mkdir(parents=True, exist_ok=True)
        png_file.write_bytes(data)
        atomic_json(directory / rel.with_suffix(".json"), {
            "side": side, "serial": serial, "image": str(rel.with_suffix(".png")).replace("\\", "/"),
            "send_utc_ns": begin, "ack_utc_ns": finish, "timestamp_ns": (begin + finish) // 2,
            "time_uncertainty_ns": (finish - begin) // 2,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        while time.monotonic() < end:
            iteration_start = time.monotonic()
            futures = [pool.submit(once, side, seq) for side in SIDES]
            for future in futures:
                future.result()
            seq += 1
            pause = interval_s - (time.monotonic() - iteration_start)
            if pause > 0:
                time.sleep(pause)
    return seq


def export_replay(directory: Path, duration_s: float | None = None) -> dict:
    start = read_json(directory / "match_start.json")["start_utc_ns"]
    entries = [read_json(f) for f in (directory / "actions").glob("*.json")] if (directory / "actions").exists() else []
    events = []
    for entry in sorted(entries, key=lambda row: row["placement_send_ns"]):
        if not entry["adb_command_sent"]:
            continue
        tick = round(((entry["placement_send_ns"] + entry["placement_ack_ns"]) // 2 - start) / NS_PER_TICK)
        if tick < 0:
            raise ValueError("action occurred before match start")
        x, y = entry["world_cell"]
        events.append({"tick": tick, "side": entry["side"], "event_type": "card_play", "card": entry["card"], "x": x, "y": y})
    last = events[-1]["tick"] if events else 0
    end_tick = max(last + 1, round(duration_s * TPS) if duration_s is not None else last + TPS * 15)
    return {"battle_id": directory.name, "mode": "placements", "ticks_per_second": TPS,
            "coordinate_system": "world_cells", "end_tick": end_tick, "events": events,
            "notes": "Controlled ADB attempts only. Must verify actual accepted plays, HUD timing, patch and level. Match start manually marked."}


def capture_videos(directory: Path, seconds: int, adb: str = "adb", bitrate: int = 4_000_000) -> dict:
    """Supplemental Android screenrecord clips (frame timing must be HUD-calibrated)."""
    if type(seconds) is not int or seconds not in range(1, 181) or not 100_000 <= bitrate <= 20_000_000:
        raise ValueError("screenrecord requires 1..180 seconds and bitrate 100k..20M")
    config = read_json(directory / "config.json")
    adb_api.require_pair(adb, [config["devices"][s]["serial"] for s in SIDES])

    def record(side: str) -> dict:
        serial = config["devices"][side]["serial"]
        remote = f"/sdcard/crlab_{uuid.uuid4().hex}.mp4"
        file = directory / "videos" / f"{side}.mp4"
        file.parent.mkdir(parents=True, exist_ok=True)
        begin = time.time_ns()
        try:
            adb_api.run(adb, serial, ["shell", "screenrecord", "--time-limit", str(seconds), "--bit-rate", str(bitrate), remote], timeout=seconds + 40)
            end = time.time_ns()
            adb_api.run(adb, serial, ["pull", remote, str(file)], timeout=120)
        finally:
            try:
                adb_api.run(adb, serial, ["shell", "rm", remote], timeout=20)
            except adb_api.ADBError:
                pass
        return {"side": side, "serial": serial, "video": str(file.relative_to(directory)).replace("\\", "/"),
                "adb_begin_ns": begin, "adb_end_ns": end, "frame_time_uncertainty": "UNBOUNDED without HUD alignment"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(record, side) for side in SIDES]
        results = [future.result() for future in futures]
    manifest = {"videos": results, "warning": "Videos start at uncertain capture time; do not label 50ms event timing as verified."}
    atomic_json(directory / "video_manifest.json", manifest)
    return manifest
