"""Explicit-serial ADB calls: no shell interpolation or assumptions about devices."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


class ADBError(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    serial: str
    status: str


def run(adb: str, serial: str | None, args: list[str], timeout: float = 20.0) -> bytes:
    cmd = [adb] + (["-s", serial] if serial else []) + args
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ADBError(f"ADB command failed: {cmd[:3]}: {exc}") from exc
    if result.returncode:
        error = result.stderr.decode("utf-8", "replace").strip()
        raise ADBError(f"ADB exited {result.returncode}: {error}")
    return result.stdout


def devices(adb: str) -> list[Device]:
    lines = run(adb, None, ["devices", "-l"]).decode("utf-8", "replace").splitlines()[1:]
    return [Device(fields[0], fields[1]) for line in lines if len(fields := line.split()) >= 2]


def require_pair(adb: str, serials: list[str]) -> None:
    if len(serials) != 2 or len(set(serials)) != 2 or not all(serials):
        raise ValueError("team/opponent must use two distinct non-empty ADB serials")
    connected = {device.serial: device.status for device in devices(adb)}
    for serial in serials:
        if connected.get(serial) != "device":
            raise ADBError(f"{serial} is unavailable (status: {connected.get(serial, 'missing')})")


def png(adb: str, serial: str) -> bytes:
    result = run(adb, serial, ["exec-out", "screencap", "-p"], timeout=30)
    if not result.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ADBError(f"invalid PNG from {serial}: {result[:32]!r}")
    return result


def tap(adb: str, serial: str, x: int, y: int) -> None:
    if min(x, y) < 0:
        raise ValueError("tap pixels must be non-negative")
    run(adb, serial, ["shell", "input", "tap", str(x), str(y)])
