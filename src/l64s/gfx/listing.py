"""Reading character or sprite data out of a program listing (CBM prg Studio's Import → From
Listing): DATA statements in BASIC, from a line number, or byte lines in assembler, from a label.

In assembler the source is assembled when it can be, so data written any way the assembler
allows (`bits`, `%00111100`, expressions, `dcb`) comes out exactly as the program has it; when it
doesn't assemble on its own (it needs other files of a project, or it's Kick Assembler) the
numbers written on the byte lines are read instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUM = r"(?:\$[0-9a-fA-F]+|%[01]+|0x[0-9a-fA-F]+|&[0-9a-fA-F]+|\d+)"
_DATA_WORDS = r"(?:\.?byte|\.?byt|db|dfb|\.by|!byte|!by|\.db)"
_ASM_DATA = re.compile(rf"^\s*(?:([A-Za-z_@.!][\w.@]*):?\s+)?{_DATA_WORDS}\s+(.*)$", re.I)
_ASM_LABEL = re.compile(r"^([A-Za-z_][\w.]*):?\s*(?:;.*|//.*)?$")
_BAS_LINE = re.compile(r"^\s*(\d+)\s*(.*)$")


class ListingError(ValueError):
    pass


@dataclass
class Block:
    """Where data starts: a label (assembler) or a line number (BASIC), and how much follows."""
    name: str
    line: int            # 1-based line in the source
    count: int           # values from here on, as far as the data goes

    def describe(self, size: int = 8, what: str = "characters") -> str:
        n = self.count // size
        return f"{self.name}  (line {self.line}: {self.count} bytes, {n} {what if n != 1 else what[:-1]})"


def _number(s: str) -> int | None:
    s = s.strip()
    try:
        if s.startswith("$"):
            return int(s[1:], 16)
        if s.lower().startswith("0x"):
            return int(s[2:], 16)
        if s.startswith("&"):
            return int(s[1:], 16)
        if s.startswith("%"):
            return int(s[1:], 2)
        return int(s)
    except ValueError:
        return None


def _strip_comment(line: str) -> str:
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == ";" or line.startswith("//", i):
            return line[:i]
    return line


# ---------------------------------------------------------------- assembler
def _asm_values(line: str) -> list[int] | None:
    """The numbers on a byte line, or None if it isn't one (or has something else on it)."""
    m = _ASM_DATA.match(_strip_comment(line))
    if not m:
        return None
    out = []
    for item in m.group(2).split(","):
        v = _number(item)
        if v is None or not 0 <= v <= 255:
            return None
        out.append(v)
    return out


def _asm_literal_blocks(lines: list[str]) -> list[tuple[str, int, list[int]]]:
    """(label, line, values from there to the end of the run of byte lines)."""
    runs: list[tuple[str, int, list[int]]] = []
    i = 0
    while i < len(lines):
        line = _strip_comment(lines[i]).rstrip()
        m = _ASM_DATA.match(line)
        lab = _ASM_LABEL.match(line)
        if (m and m.group(1)) or lab:
            name = (m.group(1) if m and m.group(1) else lab.group(1)).rstrip(":")
            start = i
            values: list[int] = []
            j = i if m else i + 1
            while j < len(lines):
                s = _strip_comment(lines[j]).strip()
                if not s:
                    j += 1
                    continue
                v = _asm_values(lines[j])
                if v is None:
                    break
                values += v
                j += 1
            if values:
                runs.append((name, start + 1, values))
        i += 1
    return runs


def _assembled(text: str):
    """The source assembled on its own, or None."""
    from ..asm.assembler import Assembler, Options
    try:
        r = Assembler(Options()).assemble_text(text)
    except Exception:
        return None
    return r if r.ok else None


def _run_at(r, addr: int) -> list[int]:
    """The data the program has from addr, as far as it goes: up to a gap or the next code."""
    data = getattr(r, "_data_addrs", None)
    if data is None:
        data = r._data_addrs = {e.address + i for e in r.listing if e.kind != "instr" for i in range(len(e.data))}
    out, a = [], addr
    while a < 0x10000 and a in data:
        out.append(r.memory[a])
        a += 1
    return out


def asm_blocks(text: str) -> list[Block]:
    lines = text.splitlines()
    r = _assembled(text)
    blocks = []
    for name, line, values in _asm_literal_blocks(lines):
        count = len(values)
        if r is not None:
            key = name.lower()
            addr = r.symbols.get(key)
            if addr is not None:
                count = max(count, len(_run_at(r, addr)))
        blocks.append(Block(name, line, count))
    if r is not None:                      # labels on data the literal reader can't read (bits, dcb...)
        seen = {b.name.lower() for b in blocks}
        for key, loc in r.label_locs.items():
            if key in seen or "__m" in key or "::" in key:
                continue
            e = next((e for e in r.listing if e.loc.line == loc.line and e.data and e.kind != "instr"), None)
            if e is not None:
                blocks.append(Block(r.names.get(key, key), loc.line, len(_run_at(r, r.symbols[key]))))
    return sorted(blocks, key=lambda b: b.line)


def asm_values(text: str, label: str) -> list[int]:
    """The data from a label onwards."""
    r = _assembled(text)
    if r is not None and label.lower() in r.symbols:
        return _run_at(r, r.symbols[label.lower()])
    for name, _line, values in _asm_literal_blocks(text.splitlines()):
        if name.lower() == label.lower():
            return values
    raise ListingError(f"No data after the label {label}")


# ---------------------------------------------------------------- BASIC
def _data_items(body: str) -> list[str] | None:
    """The items of the DATA statements on a line, or None if it has none."""
    from ..basic.reformat import scan
    items: list[str] | None = None
    for p in scan(body):
        if p.kind == "data":
            items = (items or []) + [x.strip() for x in body[p.start:p.end].split(",")]
    return items


def _basic_lines(text: str) -> list[tuple[int, int, list[str] | None]]:
    out = []
    for n, raw in enumerate(text.splitlines(), start=1):
        m = _BAS_LINE.match(raw)
        if m:
            out.append((int(m.group(1)), n, _data_items(m.group(2))))
    return out


def basic_blocks(text: str) -> list[Block]:
    lines = _basic_lines(text)
    blocks = []
    for i, (num, src, items) in enumerate(lines):
        if items is None or (i > 0 and lines[i - 1][2] is not None):
            continue                         # only where a run of DATA lines starts
        count = 0
        for _n, _s, it in lines[i:]:
            if it is None:
                break
            count += len(it)
        blocks.append(Block(f"line {num}", src, count))
    return blocks


def basic_values(text: str, line_number: int) -> list[int]:
    """DATA items from that line on, in order, as READ would read them, until a line without DATA."""
    out: list[int] = []
    started = False
    for num, src, items in _basic_lines(text):
        if not started:
            if num < line_number:
                continue
            started = True
        if items is None:
            if out:
                break
            continue
        for it in items:
            if it == "":
                out.append(0)                 # READ reads an empty item as 0
                continue
            try:
                v = float(it)
            except ValueError:
                raise ListingError(f"Line {num}: {it!r} isn't a number") from None
            if not (v.is_integer() and 0 <= v <= 255):
                raise ListingError(f"Line {num}: {it} isn't a byte (0-255)")
            out.append(int(v))
    if not out:
        raise ListingError(f"No DATA from line {line_number}")
    return out


# ---------------------------------------------------------------- characters and sprites
def blocks(text: str, basic: bool) -> list[Block]:
    return basic_blocks(text) if basic else asm_blocks(text)


def values(text: str, basic: bool, block: Block) -> list[int]:
    if basic:
        return basic_values(text, int(block.name.split()[1]))
    return asm_values(text, block.name)


def find(text: str, basic: bool, size: int) -> Block | None:
    """Find Character (or Sprite) Data: the first place with at least one whole one."""
    return next((b for b in blocks(text, basic) if b.count >= size), None)


def chars(vals: list[int], count: int | None = None) -> list[list[int]]:
    """8 bytes a character; `count` of them, or as many as there are."""
    n = len(vals) // 8 if count is None else min(count, len(vals) // 8)
    return [list(vals[i * 8:i * 8 + 8]) for i in range(n)]


def sprites(vals: list[int], count: int | None = None) -> list[bytes]:
    """63 bytes a sprite, or 64 when the data is padded to 64 (its length is a multiple of 64, or
    63 short of one, the last sprite unpadded)."""
    stride = 64 if len(vals) >= 64 and len(vals) % 64 in (0, 63) else 63
    n = (len(vals) + stride - 63) // stride
    n = n if count is None else min(count, n)
    return [bytes(vals[i * stride:i * stride + 63]) for i in range(n)]
