"""Memory to load before debugging, as CBM prg Studio's debugger does with its "external files":
data files (a .prg at its own load address, anything else at the address given) and overlay files,
CBM prg Studio's .ovl text format for small blocks of bytes in different places::

    ; a comment (a line starting with ;)
    *=1000          set the address for the bytes after it (hex)
    a9              a byte a line (or several, separated by spaces or commas)
    00*10           a byte repeated: $00 sixteen times ($10)
    decimal         the numbers after this are decimal (before it, hex)

The project keeps a list of them (Project.debug_memory: [{"file": "data/level1.bin", "address":
8192}]); the debugger writes them into memory once the program is loaded, before it runs, and a
transcript writes them once the program's in memory.
"""
from __future__ import annotations

import re
from pathlib import Path


class OverlayError(Exception):
    pass


def parse_ovl(text: str, name: str = "overlay") -> list[tuple[int, bytes]]:
    """CBM prg Studio's .ovl format -> [(address, bytes)], a block for each *= (in order)."""
    blocks: list[tuple[int, bytearray]] = []
    base = 16
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.lower() == "decimal":
            base = 10
            continue
        if line.lower() == "hex":
            base = 16
            continue
        m = re.fullmatch(r"\*\s*=\s*(\S+)", line)
        if m:
            address = _number(m.group(1), base, name, n)
            if not 0 <= address <= 0xFFFF:
                raise OverlayError(f"{name}, line {n}: {m.group(1)} is outside $0000-$FFFF")
            blocks.append((address, bytearray()))
            continue
        if not blocks:
            raise OverlayError(f"{name}, line {n}: bytes before the first *= (the address to put them)")
        for item in re.split(r"[\s,]+", line):
            value, _, times = item.partition("*")
            byte = _number(value, base, name, n)
            if not 0 <= byte <= 0xFF:
                raise OverlayError(f"{name}, line {n}: {value} isn't a byte")
            count = _number(times, base, name, n) if times else 1
            blocks[-1][1].extend([byte] * count)
    out = [(a, bytes(b)) for a, b in blocks if b]
    for a, b in out:
        if a + len(b) > 0x10000:
            raise OverlayError(f"{name}: the block at ${a:04X} runs past $FFFF")
    return out


def _number(text: str, base: int, name: str, line: int) -> int:
    t = text.strip()
    try:
        if t.startswith("$"):
            return int(t[1:], 16)
        if t.startswith("%"):
            return int(t[1:], 2)
        if t.startswith("#"):
            return int(t[1:], 10)
        return int(t, base)
    except ValueError:
        raise OverlayError(f"{name}, line {line}: '{t}' isn't a number") from None


def load(directory: Path, entry: dict) -> list[tuple[int, bytes]]:
    """One of the project's debug_memory entries -> [(address, bytes)]."""
    path = Path(entry.get("file", ""))
    path = path if path.is_absolute() else directory / path
    try:
        data = path.read_bytes()
    except OSError as e:
        raise OverlayError(f"Couldn't read {path.name}: {e.strerror or e}") from None
    if path.suffix.lower() == ".ovl":
        return parse_ovl(data.decode("latin-1"), path.name)
    address = entry.get("address")
    if address is None:
        if path.suffix.lower() != ".prg" or len(data) < 3:
            raise OverlayError(f"{path.name} needs an address to load at (only a .prg says where it goes)")
        address, data = data[0] | data[1] << 8, data[2:]
    if address + len(data) > 0x10000:
        raise OverlayError(f"{path.name} at ${address:04X} runs past $FFFF")
    return [(address, data)]


def load_all(directory: Path, entries: list[dict]) -> list[tuple[int, bytes]]:
    out = []
    for e in entries:
        out += load(directory, e)
    return out


def describe(entry: dict) -> str:
    a = entry.get("address")
    f = entry.get("file", "")
    if f.lower().endswith(".ovl"):
        return "overlay: its addresses"
    return f"at ${a:04X}" if a is not None else "at its load address"
