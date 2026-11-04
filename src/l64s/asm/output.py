"""Output writers: VICE label files, listings and an address -> source map."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .assembler import Result


def vice_labels(result: Result) -> str:
    """VICE monitor label file (load with -moncommands or `ll` in the monitor)."""
    lines = []
    for name, value in sorted(result.symbols.items(), key=lambda kv: (kv[1], kv[0])):
        if "__m" in name or not (0 <= value <= 0xFFFF):
            continue  # macro-local labels are noise in the monitor
        clean = result.names.get(name, name).replace("@", "_")
        lines.append(f"al C:{value:04x} .{clean}")
    return "\n".join(lines) + "\n"


def listing(result: Result, base_dir: str | None = None) -> str:
    out = []
    for e in result.listing:
        hexbytes = " ".join(f"{b:02X}" for b in e.data[:8])
        if len(e.data) > 8:
            hexbytes += f" ... (+{len(e.data) - 8})"
        f = os.path.relpath(e.loc.file, base_dir) if base_dir else e.loc.file
        where = f"{f}:{e.loc.line}"
        out.append(f"{e.address:04X}  {hexbytes:<30} {where:<28} {e.source.strip()}")
    return "\n".join(out) + "\n"


def source_map(result: Result) -> dict[int, tuple[str, int]]:
    """address -> (file, line) of the code that produced the byte at that address.

    Macro body lines map to the line that called the macro, which is what you want
    to see highlighted while stepping through code in the debugger.
    """
    m: dict[int, tuple[str, int]] = {}
    for e in result.listing:
        loc = e.called_from or e.loc
        for i in range(max(1, len(e.data)) if e.data else 0):
            m.setdefault(e.address + i, (loc.file, loc.line))
    return m


def write_outputs(result: Result, prg: Path, labels: Path | None = None, lst: Path | None = None,
                  srcmap: Path | None = None, raw: bool = False) -> None:
    prg.parent.mkdir(parents=True, exist_ok=True)
    prg.write_bytes(result.binary() if raw else result.prg())
    if labels:
        labels.write_text(vice_labels(result))
    if lst:
        lst.write_text(listing(result, str(prg.parent)))
    if srcmap:
        sm = source_map(result)
        srcmap.write_text(json.dumps({f"{a:04x}": [f, l] for a, (f, l) in sm.items()}))
