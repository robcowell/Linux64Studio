"""Where a program sits in the C64's 64K: segments by source file, free space, and warnings."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# The C64's memory, as the CPU sees it with the default banking.
SYSTEM_REGIONS = [
    (0x0000, 0x00FF, "Zero page"),
    (0x0100, 0x01FF, "Stack"),
    (0x0200, 0x03FF, "KERNAL and BASIC work area"),
    (0x0400, 0x07FF, "Screen RAM (default), sprite pointers at $07F8"),
    (0x0800, 0x9FFF, "BASIC program area"),
    (0xA000, 0xBFFF, "BASIC ROM (RAM underneath)"),
    (0xC000, 0xCFFF, "Free RAM"),
    (0xD000, 0xDFFF, "I/O: VIC-II, SID, colour RAM, CIAs (RAM and character ROM underneath)"),
    (0xE000, 0xFFFF, "KERNAL ROM (RAM underneath)"),
]

KINDS = ("code", "data", "binary", "variables", "stack")
RESERVED_KINDS = ("variables", "stack")     # set aside when the program runs, not loaded from the .prg


def system_region(addr: int) -> str:
    for lo, hi, name in SYSTEM_REGIONS:
        if lo <= addr <= hi:
            return name
    return ""


@dataclass
class Segment:
    start: int
    end: int          # inclusive
    owner: str        # source file (or "program")
    kind: str         # code, data or binary
    lines: list[tuple[str, int]] = field(default_factory=list, repr=False)  # (file, line) of the first entry

    @property
    def size(self) -> int:
        return self.end - self.start + 1


@dataclass
class MemoryMap:
    memory: bytes                      # 64K
    used: bytes                        # 1 where the program put a byte
    segments: list[Segment]
    owners: dict[int, int] = field(default_factory=dict, repr=False)   # address -> segment index
    reserved: bytes = b""              # 1 where the program keeps run-time memory (C variables, stack)

    def taken(self, addr: int) -> bool:
        """Loaded by the program or reserved by it when it runs."""
        return bool(self.used[addr] or (self.reserved and self.reserved[addr]))

    def owner_of(self, addr: int) -> Segment | None:
        i = self.owners.get(addr)
        return self.segments[i] if i is not None else None

    def free_ranges(self, lo: int = 0x0801, hi: int = 0xFFFF, minimum: int = 16) -> list[tuple[int, int]]:
        """Unused stretches of at least `minimum` bytes between lo and hi."""
        out, start = [], None
        for a in range(lo, hi + 1):
            if not self.taken(a):
                if start is None:
                    start = a
            elif start is not None:
                if a - start >= minimum:
                    out.append((start, a - 1))
                start = None
        if start is not None and hi + 1 - start >= minimum:
            out.append((start, hi))
        return out

    @property
    def total(self) -> int:
        return sum(self.used)


DATA_WORDS = {"byte", "byt", "db", "dfb", "word", "wor", "dw", "text", "dcb"}


def _kind(source: str) -> str:
    """code, data or binary, from the statement that produced the bytes (a label may come first)."""
    words = [w.lower().rstrip(":") for w in source.split()[:2]]
    for w in words:
        if w == "incbin":
            return "binary"
        if w in DATA_WORDS:
            return "data"
    return "code"


def from_build(result) -> MemoryMap:
    """From the built-in assembler's Result: segments by the source file each byte came from
    (macro code counts as the file that used the macro)."""
    entries = sorted(result.listing, key=lambda e: e.address)
    segments: list[Segment] = []
    owners: dict[int, int] = {}
    for e in entries:
        if not e.data:
            continue
        loc = e.called_from or e.loc
        owner = Path(loc.file).name if loc.file else "program"
        kind = "code" if "(BASIC)" in e.source else _kind(e.source)
        last = segments[-1] if segments else None
        if last and last.owner == owner and last.kind == kind and last.end + 1 >= e.address:
            last.end = max(last.end, e.address + len(e.data) - 1)
        else:
            segments.append(Segment(e.address, e.address + len(e.data) - 1, owner, kind, [(loc.file, loc.line)]))
        for a in range(e.address, e.address + len(e.data)):
            owners[a] = len(segments) - 1
    return MemoryMap(bytes(result.memory), bytes(result.used), segments, owners)


def from_prg(prg: bytes, name: str = "program") -> MemoryMap:
    """From a .prg alone (e.g. a Kick Assembler build): one segment, no per-file detail."""
    if len(prg) < 2:
        return MemoryMap(bytes(0x10000), bytes(0x10000), [])
    start = prg[0] | (prg[1] << 8)
    body = prg[2:][:0x10000 - start]
    mem = bytearray(0x10000)
    used = bytearray(0x10000)
    mem[start:start + len(body)] = body
    used[start:start + len(body)] = b"\x01" * len(body)
    segs = [Segment(start, start + len(body) - 1, name, "code")] if body else []
    return MemoryMap(bytes(mem), bytes(used), segs, {a: 0 for a in range(start, start + len(body))})


def from_memory(memory: bytes) -> MemoryMap:
    """Live memory read from VICE: nothing is known about who owns what."""
    mem = bytes(memory[:0x10000]).ljust(0x10000, b"\0")
    return MemoryMap(mem, bytes(0x10000), [])


@dataclass
class Warning:
    start: int
    end: int
    message: str


def warnings(m: MemoryMap) -> list[Warning]:
    """Places where a program's bytes are likely to cause trouble."""
    out: list[Warning] = []

    def overlap(seg: Segment, lo: int, hi: int):
        a, b = max(seg.start, lo), min(seg.end, hi)
        return (a, b) if a <= b else None

    for s in m.segments:
        if s.kind in RESERVED_KINDS:
            continue                    # (the C runtime's own places: its zero page, variables and stack)
        where = f"{s.owner} ({s.kind}, ${s.start:04X}-${s.end:04X})"
        if r := overlap(s, 0x0000, 0x01FF):
            out.append(Warning(*r, f"{where} is in the zero page or stack, which the system uses as it runs"))
        if r := overlap(s, 0x0200, 0x03FF):
            out.append(Warning(*r, f"{where} is in the KERNAL/BASIC work area: the system may overwrite it"))
        if r := overlap(s, 0x0400, 0x07E7):
            out.append(Warning(*r, f"{where} is in the default screen memory: it shows on screen and clearing "
                                   f"the screen erases it"))
        if s.kind == "code":
            for lo, hi, rom in ((0xA000, 0xBFFF, "BASIC"), (0xE000, 0xFFFF, "KERNAL")):
                if r := overlap(s, lo, hi):
                    out.append(Warning(*r, f"{where} is code under the {rom} ROM: it loads into the RAM there, "
                                           f"but the CPU runs the ROM unless you bank it out ($01)"))
        if r := overlap(s, 0xD000, 0xDFFF):
            out.append(Warning(*r, f"{where} is under the I/O area: it loads into the RAM there, which the CPU "
                                   f"only sees with I/O switched out ($01)"))
        if s.kind == "binary":
            for lo, hi in ((0x1000, 0x1FFF), (0x9000, 0x9FFF)):
                if r := overlap(s, lo, hi):
                    out.append(Warning(*r, f"{where}: if this is graphics for the VIC-II, it can't see it here. "
                                           f"In VIC banks 0 and 2 the VIC-II reads the character ROM at "
                                           f"${lo:04X}-${hi:04X} instead of RAM"))
    # Two segments claiming the same bytes (the assembler warns too)
    seen: dict[int, Segment] = {}
    for s in m.segments:
        if s.kind in RESERVED_KINDS:
            continue                    # (cc65 puts the variables over start-up code that has run)
        for a in range(s.start, s.end + 1):
            if a in seen and seen[a] is not s and seen[a].owner != s.owner:
                out.append(Warning(a, a, f"${a:04X} is written by both {seen[a].owner} and {s.owner}"))
                break
            seen.setdefault(a, s)
    return out
