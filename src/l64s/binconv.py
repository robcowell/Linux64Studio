"""Binary import and export: binaries as assembler data, BASIC DATA statements or a
disassembly that reassembles to the same bytes; memory ranges out to .bin or .prg."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .asm.opcodes import MODE_SIZE, OPCODES

# opcode -> (mnemonic, mode), documented opcodes only (others are written as data)
_DECODE = {op: (m, mode) for m, modes in OPCODES.items() for mode, op in modes.items()}
_ABS_TO_ZP = {"abs": "zp", "abx": "zpx", "aby": "zpy"}
_BRANCH_END = {"rts", "rti", "jmp", "brk"}


class ConvertError(ValueError):
    pass


@dataclass
class Binary:
    start: int
    data: bytes
    name: str = ""

    @property
    def end(self) -> int:          # exclusive
        return self.start + len(self.data)


def load_binary(path: str | Path, load_address: int | None = None, skip: int = 0,
                length: int | None = None) -> Binary:
    """A file's bytes and where they load. A .prg's first two bytes are its load address,
    unless load_address is given (then the whole file is data)."""
    p = Path(path)
    raw = p.read_bytes()
    if load_address is None:
        if p.suffix.lower() != ".prg":
            raise ConvertError("Give a load address for a file without one (only .prg files carry it)")
        if len(raw) < 2:
            raise ConvertError(f"{p.name} is too short to be a .prg")
        load_address, raw = raw[0] | (raw[1] << 8), raw[2:]
    data = raw[skip:skip + length if length is not None else None]
    start = (load_address + skip) & 0xFFFF if load_address is not None else 0
    if start + len(data) > 0x10000:
        raise ConvertError(f"${start:04X} + {len(data)} bytes runs past $FFFF")
    return Binary(start, data, p.name)


# ---------------------------------------------------------------------- data

def _fmt(b: int, radix: str) -> str:
    return {"hex": f"${b:02X}", "dec": str(b), "bin": f"%{b:08b}"}[radix]


def to_asm_data(b: Binary, label: str = "", per_line: int = 16, radix: str = "hex", kickass: bool = False,
                origin: bool = True, syntax: str | None = None) -> str:
    from .syntax import CA65, C, resolve, table
    from .syntax import origin as origin_line
    sx = resolve(syntax, kickass)
    if sx in (CA65, C):
        head = f"{b.name or 'binary'}: ${b.start:04X}-${b.end - 1:04X} ({len(b.data)} bytes)"
        text = table(sx, label or "binary", b.data, per_line=per_line, radix=radix, comment_text=head)
        return (origin_line(sx, b.start) + "\n" + text) if origin else text
    directive = ".byte" if kickass else "byte"
    c = "//" if kickass else ";"
    lines = [f"{c} {b.name or 'binary'}: ${b.start:04X}-${b.end - 1:04X} ({len(b.data)} bytes)"]
    if origin:
        lines.append(f"*= ${b.start:04X}" if kickass else f"*=${b.start:04X}")
    if label:
        lines.append(f"{label}:" if kickass else label)
    for i in range(0, len(b.data), per_line):
        lines.append(f"        {directive} " + ", ".join(_fmt(x, radix) for x in b.data[i:i + per_line]))
    return "\n".join(lines) + "\n"


def to_basic_data(b: Binary, first_line: int = 1000, step: int = 10, per_line: int = 16, loader: bool = True,
                  loader_line: int = 10) -> str:
    """DATA statements (decimal, as BASIC reads them), optionally with a loader that POKEs them."""
    if per_line < 1:
        raise ConvertError("Values per line must be at least 1")
    lines = []
    if loader:
        lines.append(f"{loader_line} for i={b.start} to {b.end - 1}:read v:poke i,v:next")
        if first_line <= loader_line:
            raise ConvertError("The DATA lines must come after the loader line")
    n = first_line
    for i in range(0, len(b.data), per_line):
        lines.append(f"{n} data " + ",".join(str(x) for x in b.data[i:i + per_line]))
        n += step
    if n - step > 63999:
        raise ConvertError("Too many DATA lines: use a smaller step or more values per line")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- disassembly

def basic_sys_address(b: Binary) -> int | None:
    """The address in a BASIC loader's SYS, e.g. 10 SYS 2064 (or SYS (2064))."""
    if b.start != 0x0801 or len(b.data) < 8:
        return None
    end = b.data.find(b"\0", 4)
    line = b.data[4:end] if end > 0 else b""
    if 0x9E not in line:
        return None
    m = re.search(rb"\x9e\s*\(?\s*(\d+)", line)
    return int(m.group(1)) if m else None


@dataclass
class _Unit:
    addr: int
    size: int
    code: bool
    mnem: str = ""
    mode: str = ""
    operand: int = 0


def _decode(mem: bytes, start: int, off: int) -> _Unit | None:
    op = mem[off]
    entry = _DECODE.get(op)
    if not entry:
        return None
    mnem, mode = entry
    size = MODE_SIZE[mode]
    if off + size > len(mem):
        return None
    if size == 1:
        val = 0
    elif size == 2:
        val = mem[off + 1]
        if mode == "rel":
            val = (start + off + 2 + (val - 256 if val > 127 else val)) & 0xFFFF
    else:
        val = mem[off + 1] | (mem[off + 2] << 8)
    return _Unit(start + off, size, True, mnem, mode, val)


def _code_addresses(b: Binary, entries: list[int]) -> set[int]:
    """Instruction start addresses reachable from the entry points (recursive descent)."""
    seen: set[int] = set()
    todo = [e for e in entries if b.start <= e < b.end]
    while todo:
        a = todo.pop()
        while b.start <= a < b.end and a not in seen:
            u = _decode(b.data, b.start, a - b.start)
            if u is None:
                break
            if any(x in seen for x in range(a + 1, a + u.size)):
                break  # would overlap code already found
            seen.add(a)
            if u.mode == "rel" or (u.mnem in ("jsr", "jmp") and u.mode == "abs"):
                todo.append(u.operand)
            if u.mnem in _BRANCH_END:
                break
            a += u.size
    return seen


@dataclass
class Disassembly:
    source: str
    code_bytes: int
    data_bytes: int
    labels: dict[int, str] = field(default_factory=dict)


def disassemble_to_source(b: Binary, entries: list[int] | None = None, kickass: bool = False,
                          label_prefix: str = "L", syntax: str | None = None) -> Disassembly:
    """6502 source that reassembles to exactly these bytes.

    With entries, only code reachable from them is disassembled and the rest is data; without,
    everything that decodes is treated as code. Instructions an assembler would encode
    differently (absolute addressing of a zero-page address) and undocumented opcodes are
    written as bytes, with the instruction in a comment.
    """
    mem, start = b.data, b.start
    code_at = _code_addresses(b, entries) if entries is not None else None
    units: list[_Unit] = []
    off = 0
    while off < len(mem):
        a = start + off
        u = _decode(mem, start, off) if (code_at is None or a in code_at) else None
        if u is not None and code_at is None and off + u.size > len(mem):
            u = None
        if u is None:
            units.append(_Unit(a, 1, False))
            off += 1
        else:
            units.append(u)
            off += u.size
    starts = {u.addr: u for u in units}

    # Labels for jump/branch/data targets that land on the start of a unit in the range.
    targets: set[int] = set()
    for u in units:
        if u.code and u.mode not in ("imp", "acc", "imm") and start <= u.operand < b.end:
            targets.add(u.operand)
    labels: dict[int, str] = {}
    for t in sorted(targets):
        if t in starts:
            labels[t] = f"{label_prefix}{t:04X}"

    def operand_text(u: _Unit) -> str:
        v = u.operand
        if v in labels:
            return labels[v]
        # inside an instruction (self-modifying code): label of the instruction + offset
        for back in (1, 2):
            if v - back in labels and starts.get(v - back) and starts[v - back].size > back:
                return f"{labels[v - back]}+{back}"
        return f"${v:02X}" if u.mode in ("zp", "zpx", "zpy", "izx", "izy") else f"${v:04X}"

    from .syntax import CA65, C, resolve
    ca65 = resolve(syntax, kickass) in (CA65, C)     # (disassembled code is assembler, in a C project too)
    if ca65:
        kickass = False
    c = "//" if kickass else ";"
    org = f"        .org ${start:04X}" if ca65 else (f"*= ${start:04X}" if kickass else f"*=${start:04X}")
    out = [f"{c} {b.name or 'binary'} disassembled: ${start:04X}-${b.end - 1:04X}", org, ""]
    directive = ".byte" if kickass or ca65 else "byte"
    pad = "        "
    i = 0
    code_bytes = data_bytes = 0
    while i < len(units):
        u = units[i]
        lab = labels.get(u.addr, "")
        head = (f"{lab}:" if (kickass or ca65) and lab else lab).ljust(8) if lab else pad
        if not u.code:
            # gather a run of data bytes, up to 8, stopping at the next label
            run = [u]
            while (i + len(run) < len(units) and not units[i + len(run)].code and len(run) < 8
                   and units[i + len(run)].addr not in labels):
                run.append(units[i + len(run)])
            vals = ", ".join(f"${mem[x.addr - start]:02X}" for x in run)
            out.append(f"{head}{directive} {vals}")
            data_bytes += len(run)
            i += len(run)
            continue
        raw = mem[u.addr - start:u.addr - start + u.size]
        # An assembler picks zero page for addresses below $100, so keep these as bytes.
        forced_abs = u.mode in _ABS_TO_ZP and u.operand < 0x100 and _ABS_TO_ZP[u.mode] in OPCODES[u.mnem]
        text = _instruction_text(u, operand_text)
        if forced_abs:
            out.append(f"{head}{directive} " + ", ".join(f"${x:02X}" for x in raw) + f"   {c} {text} (absolute)")
        else:
            out.append(f"{head}{text}")
        code_bytes += u.size
        i += 1
    return Disassembly("\n".join(out) + "\n", code_bytes, data_bytes, labels)


def _instruction_text(u: _Unit, operand_text) -> str:
    m = u.mnem
    o = operand_text(u) if u.mode not in ("imp", "acc", "imm") else ""
    return {
        "imp": m, "acc": f"{m} a", "imm": f"{m} #${u.operand:02X}",
        "zp": f"{m} {o}", "zpx": f"{m} {o},x", "zpy": f"{m} {o},y",
        "abs": f"{m} {o}", "abx": f"{m} {o},x", "aby": f"{m} {o},y",
        "ind": f"{m} ({o})", "izx": f"{m} ({o},x)", "izy": f"{m} ({o}),y", "rel": f"{m} {o}",
    }[u.mode]


# ---------------------------------------------------------------------- export

def export_range(memory: bytes, start: int, end: int, prg: bool) -> bytes:
    """Bytes start..end (inclusive), with a 2-byte load address for .prg."""
    if not 0 <= start <= end <= 0xFFFF:
        raise ConvertError(f"${start:04X}-${end:04X} isn't a range inside $0000-$FFFF")
    body = bytes(memory[start:end + 1])
    return (bytes([start & 0xFF, start >> 8]) + body) if prg else body
