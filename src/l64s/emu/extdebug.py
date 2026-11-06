"""Launching an external debugger, RetroDebugger or its forerunner C64 Debugger, with the program
and its debug dump: the .dbg file of which source line made which bytes (Kick Assembler's
format), so it shows the source as the program runs.

Both take the same command line (RetroDebugger's README-C64-65XE-NES-Debugger.txt): -prg, -d64 or
-crt for the program, -debuginfo for the .dbg, -symbols for a labels file, -autojmp to start a
program with a BASIC SYS line, -wait to give it time to start first.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import host

NAMES = ("retrodebugger", "RetroDebugger", "C64Debugger", "c64debugger")
# where tools/install-retrodebugger.sh puts it
INSTALL_DIR = host.data_home() / "linux64studio" / "RetroDebugger"


def find(preferred: str = "") -> str | None:
    """The debugger's executable: the one in Preferences, else one on the PATH, else the one
    tools/install-retrodebugger.sh installed."""
    if preferred:
        p = host.which(preferred)
        if p:
            return p
    for name in NAMES:
        if host.which(name):
            return host.which(name)
    if INSTALL_DIR.is_dir():
        for p in sorted(INSTALL_DIR.rglob("*")):
            if p.name in NAMES and p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


def command(exe: str, target: Path, dbg: Path | None = None, labels: Path | None = None,
            extra: list[str] | None = None, wait_ms: int = 2000) -> list[str]:
    """The command line that opens ``target`` (a .prg, .d64/.d71/.d81 or .crt) in the debugger."""
    args = [exe, "-wait", str(wait_ms)]
    if dbg is not None and dbg.exists():
        args += ["-debuginfo", str(dbg)]
    if labels is not None and labels.exists():
        args += ["-symbols", str(labels)]
    suffix = target.suffix.lower()
    if suffix in (".d64", ".d71", ".d81"):
        args += ["-d64", str(target), "-autorundisk"]
    elif suffix == ".crt":
        args += ["-crt", str(target)]
    else:
        args += ["-prg", str(target), "-autojmp"]
    return args + list(extra or [])


def launch(args: list[str]) -> subprocess.Popen:
    return host.popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
