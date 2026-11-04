"""Output writers: VICE label files, listings and an address -> source map."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from .assembler import Result
from .opcodes import ILLEGAL_OPCODES, OPCODES


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


def _columns(source: str) -> tuple[int, int]:
    """The 1-based first and last columns of a line's instruction or directive (after any label),
    as Kick Assembler's debug dump gives them."""
    text = source.split(";", 1)[0].rstrip()
    i = len(text) - len(text.lstrip())
    if i == 0:
        m = re.match(r"([^\s:=]+):?\s+(?=\S)", text)
        if m and m.group(1).lower() not in OPCODES and m.group(1).lower() not in ILLEGAL_OPCODES:
            i = m.end()                         # a label in column 1, then the statement
    word = re.match(r"\S+", text[i:])
    return i + 1, i + (len(word.group(0)) if word else 1)


def debug_dump(result: Result) -> str:
    """Kick Assembler 5's debug dump (-debugdump) for the program: which source line made which
    bytes, the labels, breakpoints and watches. Debuggers that read Kick Assembler's .dbg files
    (C64 Debugger, RetroDebugger, VS64) can then show the source as the program runs. As in
    Kick Assembler's, a line in a macro is listed at the macro's own line."""
    files: dict[str, int] = {}

    def index(f: str) -> int:
        return files.setdefault(str(Path(f).resolve()) if f else "", len(files))
    blocks: list[tuple[str, list[str]]] = []
    for e in result.listing:
        if not e.data or not e.loc.file:
            continue
        c1, c2 = _columns(e.source)
        row = f"${e.address:04x},${e.address + len(e.data) - 1:04x},{index(e.loc.file)},{e.loc.line},{c1}," \
              f"{e.loc.line},{c2}"
        name = Path(e.loc.file).name
        if not blocks or blocks[-1][0] != name:
            blocks.append((name, []))
        blocks[-1][1].append(row)
    texts = {(e.loc.file, e.loc.line): e.source for e in result.listing}
    files_text: dict[str, list[str]] = {}

    def line_text(file: str, line: int) -> str:
        if (file, line) in texts:
            return texts[file, line]
        if file not in files_text:
            try:
                files_text[file] = Path(file).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                files_text[file] = []
        lines = files_text[file]
        return lines[line - 1] if 0 < line <= len(lines) else ""
    labels = []
    for key, loc in result.label_locs.items():
        value = result.symbols.get(key)
        if value is None or "__m" in key or not loc.file or not 0 <= value <= 0xFFFF:
            continue
        name = result.names.get(key, key).split("::")[-1]
        m = re.match(r"\s*([^\s:=;]+:?)", line_text(loc.file, loc.line))   # as written, with any colon
        c1, c2 = (m.start(1) + 1, m.end(1)) if m else (1, len(name))
        labels.append((value, f"Default,${value:04x},{name},{index(loc.file)},{loc.line},{c1},{loc.line},{c2}"))
    out = ['<C64debugger version="1.0">', '   <Sources values="INDEX,FILE">']
    out += [f"      {i},{f}" for f, i in files.items()]
    out += ["   </Sources>", "", '   <Segment name="Default" dest="" values="START,END,FILE_IDX,LINE1,COL1,LINE2,COL2">']
    for name, rows in blocks:
        out.append(f'      <Block name="{xml_escape(name, {chr(34): "&quot;"})}">')
        out += [f"         {r}" for r in rows]
        out.append("      </Block>")
    out += ["   </Segment>", "", '   <Labels values="SEGMENT,ADDRESS,NAME,START,END,FILE_IDX,LINE1,COL1,LINE2,COL2">']
    out += [f"      {xml_escape(r)}" for _v, r in sorted(labels)]
    out += ["   </Labels>", "", '   <Breakpoints values="SEGMENT,ADDRESS,ARGUMENT">']
    out += [f"      Default,${a:04x},{xml_escape(cond)}" for a, cond in result.breakpoints]
    out += ["   </Breakpoints>", "", '   <Watchpoints values="SEGMENT,ADDRESS1,ADDRESS2,ARGUMENT">']
    out += [f"      Default,${a:04x},," for _n, a, _c in result.watches]
    out += ["   </Watchpoints>", "", "</C64debugger>"]
    return "\n".join(out) + "\n"


def write_outputs(result: Result, prg: Path, labels: Path | None = None, lst: Path | None = None,
                  srcmap: Path | None = None, raw: bool = False, dbg: Path | None = None) -> None:
    prg.parent.mkdir(parents=True, exist_ok=True)
    prg.write_bytes(result.binary() if raw else result.prg())
    if dbg:
        dbg.write_text(debug_dump(result))
    if labels:
        labels.write_text(vice_labels(result))
    if lst:
        lst.write_text(listing(result, str(prg.parent)))
    if srcmap:
        sm = source_map(result)
        srcmap.write_text(json.dumps({f"{a:04x}": [f, l] for a, (f, l) in sm.items()}))
