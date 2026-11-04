"""Kick Assembler's debug dump (-debugdump): which source line made which bytes, and the labels.
With it a Kick Assembler build gets what the built-in assembler gives: source-level debugging,
a memory map by file, labels in the memory tools, and exact instruction counts.

The .dbg file is XML:
  <Sources values="INDEX,FILE">   0,KickAss.jar:/include/autoinclude.asm  1,/home/.../game.asm ...
  <Segment ...><Block name="...">  $0801,$0802,0,38,2,38,6   (START,END,FILE_IDX,LINE1,COL1,LINE2,COL2)
  <Labels values="SEGMENT,ADDRESS,NAME,START,END,FILE_IDX,LINE1,COL1,LINE2,COL2">
A line inside a macro is listed at the macro's own line, once for each place the macro is used.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .asm.opcodes import ILLEGAL_OPCODES, MODE_SIZE, OPCODES

_OPCODE_TABLE = {code: (m, mode) for table in (OPCODES, ILLEGAL_OPCODES) for m, modes in table.items()
                 for mode, code in modes.items()}
_MNEMONICS = set(OPCODES) | set(ILLEGAL_OPCODES)


class DebugDumpError(ValueError):
    pass


@dataclass
class Entry:
    start: int
    end: int             # included
    file: str | None     # None for Kick Assembler's own files (its autoinclude)
    line: int
    block: str


@dataclass
class DebugInfo:
    sources: dict[int, str | None]
    entries: list[Entry]
    labels: list[tuple[int, str, str | None, int]]        # (address, name, file, line)
    _lines: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def source_line(self, file: str | None, line: int) -> str:
        if not file:
            return ""
        if file not in self._lines:
            try:
                self._lines[file] = Path(file).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                self._lines[file] = []
        lines = self._lines[file]
        return lines[line - 1] if 0 < line <= len(lines) else ""


def _resolve(path: str, base: Path | None) -> str | None:
    """A source path from the dump, as a file here. Kick Assembler's own files (KickAss.jar:...)
    are None. A path from another machine (Windows, another folder) is matched to a file under
    `base` by as many of its last parts as possible."""
    if path.startswith("KickAss.jar:"):
        return None
    p = Path(path)
    if p.is_file():
        return str(p.resolve())
    if base is None:
        return path
    parts = [x for x in re.split(r"[\\/]", path) if x]
    if not parts:
        return path
    candidates = [c for c in base.rglob(parts[-1]) if c.is_file()]
    if not candidates:
        candidates = [c for c in base.rglob("*") if c.is_file() and c.name.lower() == parts[-1].lower()]

    def score(c: Path) -> int:
        cp = [x.lower() for x in c.parts]
        n = 0
        for a, b in zip(reversed(cp), reversed([x.lower() for x in parts])):
            if a != b:
                break
            n += 1
        return n
    if candidates:
        return str(max(candidates, key=score).resolve())
    return path


def parse(path: str | Path, base: Path | None = None) -> DebugInfo:
    """Read a .dbg file. `base` is where to look for sources whose paths aren't found as they are."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        raise DebugDumpError(f"Can't read the debug dump {Path(path).name}: {e}") from None
    sources: dict[int, str | None] = {}
    for el in root.iter("Sources"):
        for line in (el.text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            idx, _, name = line.partition(",")
            try:
                sources[int(idx)] = _resolve(name.strip(), base)
            except ValueError:
                continue
    entries: list[Entry] = []
    seen = set()
    for block in root.iter("Block"):
        name = block.get("name", "")
        for line in (block.text or "").splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) < 4 or not f[0].startswith("$"):
                continue
            try:
                key = (int(f[0][1:], 16), int(f[1][1:], 16), int(f[2]), int(f[3]))
            except ValueError:
                continue
            if key in seen:                    # the dump repeats some entries
                continue
            seen.add(key)
            entries.append(Entry(key[0], key[1], sources.get(key[2]), key[3], name))
    labels = []
    for el in root.iter("Labels"):
        for line in (el.text or "").splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) < 5 or not f[1].startswith("$"):
                continue
            try:
                labels.append((int(f[1][1:], 16), f[2], sources.get(int(f[3])), int(f[4])))
            except ValueError:
                continue
    entries.sort(key=lambda e: (e.start, e.end))
    return DebugInfo(sources, entries, labels)


def source_map(info: DebugInfo) -> dict[int, tuple[str, int]]:
    """address -> (file, line), as the debugger uses it (the first line listed for a byte wins)."""
    m: dict[int, tuple[str, int]] = {}
    for e in info.entries:
        if e.file:
            for a in range(e.start, e.end + 1):
                m.setdefault(a, (e.file, e.line))
    return m


def symbols(info: DebugInfo) -> dict[int, str]:
    """address -> label. Where several labels share an address, a name used once is preferred
    over one that's reused in many places (such as a macro's loop)."""
    uses: dict[str, int] = {}
    for _a, name, _f, _l in info.labels:
        uses[name] = uses.get(name, 0) + 1
    out: dict[int, tuple[str, tuple]] = {}
    for a, name, f, ln in info.labels:
        # fewer uses first; then the label defined later, the more specific one (a block's start
        # label, then its first variable on the next line, say)
        key = (-uses[name], (f or "", ln))
        if a not in out or key > out[a][1]:
            out[a] = (name, key)
    return {a: name for a, (name, _k) in out.items()}


def _statement(text: str) -> str:
    """A source line without its comment and leading labels."""
    code = text.split("//")[0].split(";")[0].strip()
    while True:
        m = re.match(r"^!?[A-Za-z_@][\w.@]*:\s*", code)
        if not m:
            return code
        code = code[m.end():]


def kind_of(info: DebugInfo, e: Entry, memory: bytes | None = None) -> str:
    """code, data or binary, for an entry."""
    stmt = _statement(info.source_line(e.file, e.line)).lower()
    first = stmt.split(None, 1)[0] if stmt else ""
    if first.startswith(".import") or "loadbinary" in stmt or "loadsid" in stmt:
        return "binary" if ".import" in first else "data"
    if first.startswith("."):
        return "data"
    mn = first.split(".")[0]
    if mn in _MNEMONICS:
        return "code"
    if memory is not None:
        hit = _OPCODE_TABLE.get(memory[e.start])
        if hit and MODE_SIZE[hit[1]] == e.end - e.start + 1 and not first:
            return "code"
    return "data" if first else "code"


def instructions(info: DebugInfo, memory: bytes) -> list[tuple[str, int, str, str, str]]:
    """(file, line, mnemonic, mode, source) for each instruction in the build, from the dump and
    the program's bytes. Each use of a macro counts, at the macro's line."""
    out = []
    for e in info.entries:
        if not e.file or kind_of(info, e, memory) != "code":
            continue
        hit = _OPCODE_TABLE.get(memory[e.start])
        if not hit or MODE_SIZE[hit[1]] != e.end - e.start + 1:
            continue
        out.append((e.file, e.line, hit[0], hit[1], info.source_line(e.file, e.line).strip()))
    return out


def memory_map(prg: bytes, info: DebugInfo, name: str = "program"):
    """A MemoryMap with segments by source file and kind, like the built-in assembler's."""
    from .memmap import MemoryMap, Segment, from_prg
    base = from_prg(prg, name)
    mem = base.memory
    segments: list[Segment] = []
    owners: dict[int, int] = {}
    for e in info.entries:
        if not base.used[e.start]:
            continue                            # not in this program (a stale dump, or another segment)
        owner = Path(e.file).name if e.file else "Kick Assembler"
        kind = kind_of(info, e, mem)
        last = segments[-1] if segments else None
        if last and last.owner == owner and last.kind == kind and last.end + 1 >= e.start and last.start <= e.start:
            last.end = max(last.end, e.end)
        else:
            segments.append(Segment(e.start, e.end, owner, kind, [(e.file or "", e.line)]))
        for a in range(e.start, e.end + 1):
            owners.setdefault(a, len(segments) - 1)
    # bytes the dump doesn't mention (padding, for instance) stay as part of the program
    rest = [a for a in range(0x10000) if base.used[a] and a not in owners]
    if rest:
        segments.append(Segment(rest[0], rest[-1], name, "data"))
        for a in rest:
            owners[a] = len(segments) - 1
    return MemoryMap(mem, base.used, segments, owners)
