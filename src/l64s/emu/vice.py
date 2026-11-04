"""Launching VICE (x64sc) to run or debug a program."""
from __future__ import annotations

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


def launch(prg: Path, emulator: str = "", labels: Path | None = None, monitor_port: int | None = None,
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
    args += ["-autostartprgmode", "1", str(prg)]
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
