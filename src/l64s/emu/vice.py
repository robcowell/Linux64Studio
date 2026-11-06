"""Launching VICE (x64sc) to run or debug a program."""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

DEFAULT_EMULATOR = "x64sc"


def find_emulator(preferred: str = "") -> str | None:
    for cand in [preferred, DEFAULT_EMULATOR, "x64"]:
        if cand and (shutil.which(cand) or Path(cand).is_file()):
            return shutil.which(cand) or cand
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# What can drive the C64's joystick ports in VICE (its -joydev1/-joydev2 numbers): (key, label, device)
JOYSTICKS = (("none", "None", 0), ("keypad", "Keypad: 8 4 6 2 move, 0 fires", 1),
             ("keyset1", "VICE keyset A (set its keys in VICE)", 2), ("keyset2", "VICE keyset B", 3),
             ("joy1", "Joystick or gamepad 1", 4), ("joy2", "Joystick or gamepad 2", 5))


def joystick_args(port1: str, port2: str, other_args: list[str] | None = None) -> list[str]:
    """VICE options for what drives joystick ports 1 and 2 ("none", "keypad", ...). Left out for a
    port the other options already set (a -joydev typed into Preferences' extra arguments wins)."""
    devices = {key: dev for key, _label, dev in JOYSTICKS}
    out: list[str] = []
    for port, key in ((1, port1), (2, port2)):
        if key in devices and key != "none" and f"-joydev{port}" not in (other_args or []):
            out += [f"-joydev{port}", str(devices[key])]
    return out


def launch(prg: Path | None, emulator: str = "", labels: Path | None = None, monitor_port: int | None = None,
           extra_args: list[str] | None = None) -> subprocess.Popen:
    exe = find_emulator(emulator)
    if not exe:
        raise FileNotFoundError("VICE (x64sc) not found. Install it with: sudo apt install vice")
    args = [exe]
    if monitor_port:
        args += ["-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{monitor_port}"]
    if labels and labels.exists():
        args += ["-moncommands", str(labels)]
    args += list(extra_args or [])
    if prg is None:                            # just the machine, at READY
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    # A disk image may name the program to start: game.d64:intro (VICE autostarts it)
    image = Path(re.sub(r"(?i)(\.d(64|71|81)):[^/]*$", r"\1", str(prg)))
    # A 1571 or 1581 disk needs drive 8 to be that kind of drive.
    drive = {".d71": "1571", ".d81": "1581"}.get(image.suffix.lower())
    if drive and not any(a.startswith("-drive8type") for a in args):
        args += ["-drive8type", drive]
    if image.suffix.lower() == ".crt":
        args += ["-cartcrt", str(prg)]  # cartridges are plugged in, not loaded
    else:
        args += ["-autostartprgmode", "1", str(prg)]
    # VICE's log goes nowhere: it writes a line each time the monitor lets it go on ("Sync reset"),
    # so a pipe that isn't read fills after a few thousand debugger steps, and VICE stops dead.
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


def wait_for_port(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False
