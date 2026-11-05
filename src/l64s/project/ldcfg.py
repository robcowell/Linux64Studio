"""Linker configs for C projects: ld65's memory layout for the program.

cc65's standard C64 layout puts the program at $0801 and lets it run up to $D000, with the C stack
at the top. A game often needs things at fixed addresses as well: music packed for $1000, a
character set where the VIC-II can see it. ``generate`` writes a config with those *fixed areas*
in it, each with a segment of the same name for the code to put things in::

    .segment "MUSIC"                    ; (ca65)
    .incbin "music.bin"

    #pragma rodata-name (push, "MUSIC")  /* (C) */
    const unsigned char tune[] = { ... };
    #pragma rodata-name (pop)

The program goes in the biggest space left between them, and anything in the way is padded in
the .prg (``fill = yes``), so every area loads at its address. The start-up code stays at $080D
(after the BASIC line's SYS 2061) in a small area of its own if the program has to go higher.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HEADER_END = 0x080D          # $0801 + the 12-byte BASIC line (10 SYS 2061) and its end marker
HIMEM = 0xD000               # where cc65's program memory ends (the I/O area starts)
STARTUP_ROOM = 0x80          # what cc65's start-up code needs below a fixed area
RESERVED = {"ZP", "LOADADDR", "HEADER", "MAIN", "BSS", "BOOT", "ZEROPAGE", "EXEHDR", "STARTUP", "LOWCODE",
            "CODE", "RODATA", "DATA", "INIT", "ONCE"}


class LayoutError(ValueError):
    pass


@dataclass
class Area:
    name: str
    start: int
    size: int

    @property
    def end(self) -> int:          # exclusive
        return self.start + self.size

    def to_dict(self) -> dict:
        return {"name": self.name, "start": self.start, "size": self.size}

    @classmethod
    def from_dict(cls, d: dict) -> Area:
        return cls(str(d.get("name", "")), int(d.get("start", 0)), int(d.get("size", 0)))


def check(areas: list[Area]) -> list[Area]:
    """The areas in address order, or LayoutError saying what's wrong."""
    seen = set()
    for a in areas:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", a.name):
            raise LayoutError(f"'{a.name}' can't be an area name: use letters, digits and _")
        if a.name.upper() in RESERVED:
            raise LayoutError(f"{a.name} is one of cc65's own names: choose another")
        if a.name.upper() in seen:
            raise LayoutError(f"There are two areas called {a.name}")
        seen.add(a.name.upper())
        if a.size <= 0:
            raise LayoutError(f"{a.name} needs a size")
        if a.start < HEADER_END + STARTUP_ROOM:
            raise LayoutError(f"{a.name} starts at ${a.start:04X}: fixed areas start at "
                              f"${HEADER_END + STARTUP_ROOM:04X} or above, after the BASIC line and cc65's "
                              f"start-up code")
        if a.end > 0x10000:
            raise LayoutError(f"{a.name} runs past $FFFF")
    out = sorted(areas, key=lambda a: a.start)
    for a, b in zip(out, out[1:]):
        if b.start < a.end:
            raise LayoutError(f"{a.name} (${a.start:04X}-${a.end - 1:04X}) and {b.name} "
                              f"(${b.start:04X}-${b.end - 1:04X}) overlap")
    return out


def layout(areas: list[Area]) -> tuple[tuple[int, int], list[tuple[str, int, int]]]:
    """(the program's memory (start, end), every memory area in address order as (name, start, end)),
    from $080D. The program has the biggest gap below $D000; gaps before it are BOOT (the start-up
    code) and FILLn (padding)."""
    areas = check(areas)
    gaps, cur = [], HEADER_END
    for a in areas:
        if a.start > cur:
            gaps.append((cur, min(a.start, HIMEM)))
        cur = max(cur, a.end)
    if cur < HIMEM:
        gaps.append((cur, HIMEM))
    gaps = [g for g in gaps if g[1] > g[0]]
    if not gaps:
        raise LayoutError("The fixed areas leave no room for the program below $D000")
    main = max(gaps, key=lambda g: g[1] - g[0])
    if main[1] - main[0] < 0x400:
        raise LayoutError(f"The biggest space left for the program is ${main[0]:04X}-${main[1] - 1:04X}: "
                          "too small. Move or shrink the fixed areas")
    regions, n = [], 0
    for g in gaps:
        if g == main:
            regions.append(("MAIN", *g))
        elif g[0] == HEADER_END:
            regions.append(("BOOT", *g))
        else:
            n += 1
            regions.append((f"FILL{n}", *g))
    top = areas[-1].start if areas else 0
    regions = [r for r in regions if r[0] == "MAIN" or r[1] < top]       # (nothing to pad above the last area)
    regions += [(a.name, a.start, a.end) for a in areas]
    return main, sorted(regions, key=lambda r: r[1])


def generate(areas: list[Area], stack_size: int = 0x0800, title: str = "") -> str:
    """An ld65 config: cc65's C64 layout, with the fixed areas."""
    areas = check(areas)
    if not areas:
        return _standard(stack_size, title)
    (m0, m1), regions = layout(areas)
    last_in_file = max(r[1] for r in regions)
    h = lambda v: f"${v:04X}"     # noqa: E731
    mem = [
        '    ZP:       file = "", define = yes, start = $0002, size = $001A;',
        "    LOADADDR: file = %O, start = %S - 2, size = $0002;",
        "    HEADER:   file = %O, define = yes, start = %S, size = $000D;",
    ]
    for name, lo, hi in regions:
        fill = ", fill = yes" if lo != last_in_file else ""
        size = "__HIMEM__ - " + h(lo) if name == "MAIN" else h(hi - lo)
        start = "__HEADER_LAST__" if lo == HEADER_END else h(lo)
        note = {"MAIN": "  # the program, its variables and the C stack",
                "BOOT": "  # cc65's start-up code (the SYS goes here)"}.get(name, "  # (padding)" if
                                                                               name.startswith("FILL") else "")
        mem.append(f"    {name + ':':<9} file = %O, define = yes, start = {start}, size = {size}{fill};{note}")
    mem.append("    BSS:      file = \"\", start = __ONCE_RUN__, size = __HIMEM__ - __STACKSIZE__ - __ONCE_RUN__;")
    boot = any(r[0] == "BOOT" for r in regions)
    segs = [
        "    ZEROPAGE: load = ZP,       type = zp;",
        "    LOADADDR: load = LOADADDR, type = ro;",
        "    EXEHDR:   load = HEADER,   type = ro;",
        f"    STARTUP:  load = {'BOOT' if boot else 'MAIN'},{' ' * (8 - len('BOOT' if boot else 'MAIN'))} type = ro;",
        "    LOWCODE:  load = MAIN,     type = ro,  optional = yes;",
        "    CODE:     load = MAIN,     type = ro;",
        "    RODATA:   load = MAIN,     type = ro;",
        "    DATA:     load = MAIN,     type = rw;",
        "    INIT:     load = MAIN,     type = rw;",
        "    ONCE:     load = MAIN,     type = ro,  define   = yes;",
        "    BSS:      load = BSS,      type = bss, define   = yes;",
    ]
    for a in areas:
        segs.append(f"    {a.name + ':':<9} load = {a.name}, type = rw, optional = yes;"
                    f"  # ${a.start:04X}-${a.end - 1:04X}")
    head = _comment(title) + (
        "# Fixed areas: " + ", ".join(f"{a.name} ${a.start:04X}-${a.end - 1:04X}" for a in areas) + ".\n"
        f"# The program goes in ${m0:04X}-${m1 - 1:04X}; what's in the way is padded in the .prg.\n"
        "# Put things in an area with its segment: .segment \"NAME\" (ca65), or\n"
        "# #pragma rodata-name (push, \"NAME\") ... #pragma rodata-name (pop) (C).\n\n")
    return head + _body(stack_size, h(m1), mem, segs)


def _comment(title: str) -> str:
    return (f"# {title}\n" if title else "") + "# ld65 linker config for the C64 (cc65), made by Linux64Studio.\n"


def _standard(stack_size: int, title: str) -> str:
    """cc65's own c64.cfg."""
    mem = [
        '    ZP:       file = "", define = yes, start = $0002,           size = $001A;',
        "    LOADADDR: file = %O,               start = %S - 2,          size = $0002;",
        "    HEADER:   file = %O, define = yes, start = %S,              size = $000D;",
        "    MAIN:     file = %O, define = yes, start = __HEADER_LAST__, size = __HIMEM__ - __HEADER_LAST__;",
        "    BSS:      file = \"\",               start = __ONCE_RUN__,    size = __HIMEM__ - __STACKSIZE__ - "
        "__ONCE_RUN__;",
    ]
    segs = [
        "    ZEROPAGE: load = ZP,       type = zp;",
        "    LOADADDR: load = LOADADDR, type = ro;",
        "    EXEHDR:   load = HEADER,   type = ro;",
        "    STARTUP:  load = MAIN,     type = ro;",
        "    LOWCODE:  load = MAIN,     type = ro,  optional = yes;",
        "    CODE:     load = MAIN,     type = ro;",
        "    RODATA:   load = MAIN,     type = ro;",
        "    DATA:     load = MAIN,     type = rw;",
        "    INIT:     load = MAIN,     type = rw;",
        "    ONCE:     load = MAIN,     type = ro,  define   = yes;",
        "    BSS:      load = BSS,      type = bss, define   = yes;",
    ]
    head = _comment(title) + (
        "# This is cc65's standard layout: the program from $0801 up to $D000, the C stack at the top.\n"
        "# To put something at a fixed address, add a memory area for it (and leave MAIN room), e.g.\n"
        "#     MUSIC: file = %O, start = $C000, size = $1000;     (in MEMORY, after MAIN; MAIN needs\n"
        "#                                                      fill = yes and __HIMEM__ = $C000)\n"
        "#     MUSIC: load = MUSIC, type = rw;                    (in SEGMENTS)\n"
        "# or let Linux64Studio work the layout out: Project Settings > Build > Fixed areas.\n\n")
    return head + _body(stack_size, "$D000", mem, segs)


def _body(stack_size: int, himem: str, mem: list[str], segs: list[str]) -> str:
    return "\n".join([
        "FEATURES {",
        "    STARTADDRESS: default = $0801;",
        "}",
        "SYMBOLS {",
        "    __LOADADDR__:  type = import;",
        "    __EXEHDR__:    type = import;",
        f"    __STACKSIZE__: type = weak, value = ${stack_size:04X}; # the C stack",
        f"    __HIMEM__:     type = weak, value = {himem};",
        "}",
        "MEMORY {",
        *mem,
        "}",
        "SEGMENTS {",
        *segs,
        "}",
        "FEATURES {",
        "    CONDES: type    = constructor,",
        "            label   = __CONSTRUCTOR_TABLE__,",
        "            count   = __CONSTRUCTOR_COUNT__,",
        "            segment = ONCE;",
        "    CONDES: type    = destructor,",
        "            label   = __DESTRUCTOR_TABLE__,",
        "            count   = __DESTRUCTOR_COUNT__,",
        "            segment = RODATA;",
        "    CONDES: type    = interruptor,",
        "            label   = __INTERRUPTOR_TABLE__,",
        "            count   = __INTERRUPTOR_COUNT__,",
        "            segment = RODATA,",
        "            import  = __CALLIRQ__;",
        "}",
    ]) + "\n"


def parse_address(text: str) -> int:
    """$1000, 0x1000, 1000 (hex, as the music tool's addresses), or #4096 / 4096d decimal."""
    t = text.strip().lower()
    if t.startswith("#"):
        return int(t[1:])
    if t.endswith("d") and t[:-1].isdigit():
        return int(t[:-1])
    t = t.removeprefix("$").removeprefix("0x")
    return int(t, 16)
