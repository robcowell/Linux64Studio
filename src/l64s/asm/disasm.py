"""A small 6502 disassembler for the debugger."""
from __future__ import annotations

from .opcodes import MODE_SIZE, build_reverse_table

_TABLE = build_reverse_table(include_illegal=True)


def disassemble_one(mem: bytes, offset: int, address: int, labels: dict[int, str] | None = None) -> tuple[int, str, str]:
    """Return (length, hex bytes, text) for the instruction at mem[offset] (which lives at `address`)."""
    op = mem[offset]
    entry = _TABLE.get(op)
    if not entry:
        return 1, f"{op:02X}", f"byte ${op:02X}"
    mnem, mode = entry
    size = MODE_SIZE[mode]
    raw = mem[offset:offset + size]
    if len(raw) < size:
        return 1, f"{op:02X}", f"byte ${op:02X}"
    lo = raw[1] if size > 1 else 0
    word = lo | (raw[2] << 8) if size > 2 else lo

    def name(v: int, digits: int) -> str:
        if labels and v in labels:
            return labels[v]
        return f"${v:0{digits}X}"

    if mode in ("imp",):
        text = mnem
    elif mode == "acc":
        text = f"{mnem} a"
    elif mode == "imm":
        text = f"{mnem} #${lo:02X}"
    elif mode == "zp":
        text = f"{mnem} {name(lo, 2)}"
    elif mode == "zpx":
        text = f"{mnem} {name(lo, 2)},x"
    elif mode == "zpy":
        text = f"{mnem} {name(lo, 2)},y"
    elif mode == "abs":
        text = f"{mnem} {name(word, 4)}"
    elif mode == "abx":
        text = f"{mnem} {name(word, 4)},x"
    elif mode == "aby":
        text = f"{mnem} {name(word, 4)},y"
    elif mode == "ind":
        text = f"{mnem} ({name(word, 4)})"
    elif mode == "izx":
        text = f"{mnem} ({name(lo, 2)},x)"
    elif mode == "izy":
        text = f"{mnem} ({name(lo, 2)}),y"
    elif mode == "rel":
        target = (address + 2 + (lo - 256 if lo > 127 else lo)) & 0xFFFF
        text = f"{mnem} {name(target, 4)}"
    else:
        text = mnem
    return size, " ".join(f"{b:02X}" for b in raw), text


def disassemble(mem: bytes, address: int, count: int, labels: dict[int, str] | None = None) -> list[tuple[int, str, str]]:
    """Disassemble up to `count` instructions from mem (which starts at `address`)."""
    out, off = [], 0
    while len(out) < count and off < len(mem):
        size, hx, text = disassemble_one(mem, off, address + off, labels)
        out.append((address + off, hx, text))
        off += size
    return out
