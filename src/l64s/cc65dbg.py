"""ld65's debug information file (--dbgfile), for C source-level debugging of cc65 builds, as
kickdbg reads Kick Assembler's debug dump.

The file is lines of ``kind<TAB>key=value,key=value``: ``file`` (id, name), ``seg`` (id, start
address), ``span`` (id, seg, start offset, size), ``line`` (file, line, type, spans) and ``sym``
(name, val). A ``line`` of type 1 is a line of C; type 0 is assembler (a .s file, or the assembly
cc65 made from a C file, which is deleted after compiling); type 2 is inside a macro.

``source_map`` turns it into {address: (file, line)} for the debugger, keeping the C lines and the
lines of assembler files that exist (not cc65's deleted assembly, nor the runtime library's).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class DebugFileError(Exception):
    pass


@dataclass
class DebugInfo:
    files: dict[int, str] = field(default_factory=dict)              # id -> name as ld65 wrote it
    segs: dict[int, int] = field(default_factory=dict)               # id -> start address
    spans: dict[int, tuple[int, int, int]] = field(default_factory=dict)   # id -> (seg, offset, size)
    lines: list[tuple[int, int, int, list[int]]] = field(default_factory=list)  # (file, line, type, spans)
    symbols: dict[int, str] = field(default_factory=dict)            # address -> name (labels)


def _fields(text: str) -> dict[str, str]:
    """key=value,key=value, where a "quoted" value may hold commas."""
    out, i, n = {}, 0, len(text)
    while i < n:
        eq = text.find("=", i)
        if eq < 0:
            break
        key = text[i:eq]
        j = eq + 1
        if j < n and text[j] == '"':
            end = text.find('"', j + 1)
            end = n if end < 0 else end
            out[key] = text[j + 1:end]
            i = end + 2                          # past the quote and the comma
        else:
            end = text.find(",", j)
            end = n if end < 0 else end
            out[key] = text[j:end]
            i = end + 1
    return out


def _int(v: str) -> int:
    return int(v, 16) if v.lower().startswith("0x") else int(v)


def parses(text: str) -> DebugInfo:
    info = DebugInfo()
    if not text.startswith("version"):
        raise DebugFileError("Not an ld65 debug file")
    for raw in text.splitlines():
        kind, _, rest = raw.partition("\t")
        if kind not in ("file", "seg", "span", "line", "sym"):
            continue
        f = _fields(rest)
        try:
            if kind == "file":
                info.files[_int(f["id"])] = f["name"]
            elif kind == "seg":
                info.segs[_int(f["id"])] = _int(f["start"])
            elif kind == "span":
                info.spans[_int(f["id"])] = (_int(f["seg"]), _int(f["start"]), _int(f.get("size", "0")))
            elif kind == "line":
                spans = [_int(s) for s in f["span"].split("+")] if f.get("span") else []
                info.lines.append((_int(f["file"]), _int(f["line"]), _int(f.get("type", "0")), spans))
            elif kind == "sym" and f.get("type") == "lab" and "val" in f:
                info.symbols.setdefault(_int(f["val"]), f["name"])
        except (KeyError, ValueError):
            continue                               # a line we don't understand: skip it
    return info


def parse(path: Path) -> DebugInfo:
    try:
        return parses(Path(path).read_text(errors="replace"))
    except OSError as e:
        raise DebugFileError(f"Couldn't read {path}: {e}") from None


def source_map(info: DebugInfo, base: Path) -> dict[int, tuple[str, int]]:
    """{address: (file, line)}: C lines first, then lines of assembler files that exist (relative
    names are from ``base``, the folder the build ran in)."""
    real: dict[int, str | None] = {}
    for fid, name in info.files.items():
        p = Path(name)
        p = p if p.is_absolute() else base / p
        real[fid] = str(p.resolve()) if p.is_file() else None
    out: dict[int, tuple[str, int]] = {}
    for want in (1, 0):                            # C lines win where both start at an address
        for fid, line, typ, spans in info.lines:
            if typ != want or real.get(fid) is None:
                continue
            for sid in spans:
                span = info.spans.get(sid)
                if span is None or span[2] == 0:
                    continue
                seg, offset, _size = span
                if seg in info.segs:
                    out.setdefault(info.segs[seg] + offset, (real[fid], line))
    return out
