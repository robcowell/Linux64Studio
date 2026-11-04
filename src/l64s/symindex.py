"""Where things are defined, for the editor's Go to Definition and auto-complete.

The project's sources are scanned line by line (not assembled), so it works while code is being
written and doesn't compile. Both dialects are read:

* CBM prg Studio: a label in column 1 (`loop`, `loop:`), `NAME = value`, `defm NAME`, and `@local`
  labels, which belong to the label before them. Labels are any case; macros are case-sensitive.
* Kick Assembler: `name:` labels, `.const`/`.var`/`.label NAME =`, `.macro`/`.function`/
  `.pseudocommand name`, `.namespace name`. Everything is case-sensitive; `!name:` labels are
  skipped (there are many of each).

Also: the file an `incasm`/`incbin`/`#import`/`.import` line names, and in BASIC the line a
GOTO/GOSUB goes to (or a pBASIC `@label`).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .asm.opcodes import ILLEGAL_OPCODES, OPCODES
from .asm.source import DIRECTIVES

KICK_DIRECTIVES = [
    ".align", ".assert", ".asserterror", ".break", ".byte", ".by", ".const", ".cpu", ".define", ".disk",
    ".dword", ".dw", ".encoding", ".enum", ".error", ".errorif", ".eval", ".file", ".filemodify",
    ".filenamespace", ".fill", ".fillword", ".for", ".function", ".if", ".import", ".importonce", ".label",
    ".lohifill", ".macro", ".memblock", ".modify", ".namespace", ".pc", ".plugin", ".print", ".printnow",
    ".pseudocommand", ".pseudopc", ".return", ".segment", ".segmentdef", ".segmentout", ".struct", ".text",
    ".var", ".watch", ".while", ".word", ".wo", ".zp", "#import", "#importif", "#define", "#if", "#elif",
    "#else", "#endif", "#undef",
]

_MNEMONICS = sorted(set(OPCODES) | set(ILLEGAL_OPCODES))
_WORD = re.compile(r"[A-Za-z0-9_@$.]")
_CBM_LABEL = re.compile(r"^([@A-Za-z_][A-Za-z0-9_.@]*\$?)(:?)(?=\s|$|;|=)")
_CBM_CONST = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*\$?)\s*(=|\bequ\b)", re.I)
_CBM_MACRO = re.compile(r"^\s*defm\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_KICK_LABEL = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):")
_KICK_CONST = re.compile(r"^\s*\.(const|var|label)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")
_KICK_MACRO = re.compile(r"^\s*\.(macro|function|pseudocommand)\s+@?([A-Za-z_][A-Za-z0-9_]*)")
_KICK_NAMESPACE = re.compile(r"^\s*\.(namespace|filenamespace)\s+([A-Za-z_][A-Za-z0-9_]*)")
_INCLUDE = re.compile(r"^\s*(?:[A-Za-z_][\w.]*:?\s+)?(incasm|incbin|#import|#importif\s+\S+|\.import\s+\w+)"
                      r"\s+\"?([^\",;]+?)\"?\s*(?:[,;]|//|$)", re.I)


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str          # label, local, const, var, macro, function, namespace
    file: str
    line: int          # 1-based
    col: int           # 0-based, where the name starts
    text: str          # the defining line, for showing


def _strip_comment(line: str) -> str:
    """The line without its comment (`;`, or `//`), outside quotes."""
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


def looks_like_kick(text: str) -> bool:
    return bool(re.search(r"^\s*(\.(const|var|macro|function|import|pc|namespace|label)\b|#import\b|"
                          r"[A-Za-z_]\w*:\s*$|BasicUpstart)", text, re.M))


def scan(text: str, file: str = "", kickass: bool = False) -> list[tuple[Symbol, str]]:
    """The definitions in one file, each with its scope (for CBM `@local` labels: the label they
    follow)."""
    out: list[tuple[Symbol, str]] = []
    scope = ""
    for n, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        shown = raw.strip()
        if kickass:
            for rx, kind in ((_KICK_CONST, None), (_KICK_MACRO, None), (_KICK_NAMESPACE, "namespace")):
                m = rx.match(line)
                if m:
                    k = kind or m.group(1)
                    out.append((Symbol(m.group(2), "macro" if k == "pseudocommand" else k, file, n,
                                       m.start(2), shown), ""))
                    break
            else:
                m = _KICK_LABEL.match(line)
                if m:
                    out.append((Symbol(m.group(1), "label", file, n, m.start(1), shown), ""))
            continue
        m = _CBM_MACRO.match(line)
        if m:
            out.append((Symbol(m.group(1), "macro", file, n, m.start(1), shown), ""))
            continue
        m = _CBM_CONST.match(line)
        if m and m.group(1).lower() not in OPCODES:
            out.append((Symbol(m.group(1), "const", file, n, m.start(1), shown), ""))
            continue
        m = _CBM_LABEL.match(line)
        if m:
            name = m.group(1)
            low = name.lower()
            if low in OPCODES or low in ILLEGAL_OPCODES or low in DIRECTIVES or low in ("else", "endif"):
                continue
            if name.startswith("@"):
                out.append((Symbol(name, "local", file, n, 0, shown), scope))
            else:
                scope = low
                out.append((Symbol(name, "label", file, n, 0, shown), ""))
    return out


def word_at(line: str, col: int) -> tuple[int, int, str]:
    """The name at a column (letters, digits, _, @, $, and . for Kick's `name.sub`)."""
    s = col
    while s > 0 and _WORD.match(line[s - 1]):
        s -= 1
    e = col
    while e < len(line) and _WORD.match(line[e]):
        e += 1
    while s < e and line[s] in ".$":          # .const -> const isn't a name; $c000 isn't either
        if line[s] == "$" and s + 1 < e and re.match(r"[0-9a-fA-F]+$", line[s + 1:e]):
            return s, e, ""
        s += 1
    return s, e, line[s:e]


def include_at(line: str, base: Path) -> Path | None:
    """The file an include line names (incasm, incbin, #import, .import source/binary/c64)."""
    m = _INCLUDE.match(_strip_comment(line) if '"' not in line else line)
    if not m:
        return None
    return (base / m.group(2).strip()).resolve()


class SymbolIndex:
    """The definitions in a set of files. `update()` rescans only what changed."""

    def __init__(self):
        self._files: dict[str, tuple[object, bool, list[tuple[Symbol, str]]]] = {}   # file -> (stamp, kick, syms)
        self._by_name: dict[str, list[Symbol]] = {}       # lower-case name -> its definitions (not locals)

    def update(self, files: list[Path], overrides: dict[str, str] | None = None, kickass: bool | None = None):
        """Scan `files` (paths as strings in `overrides` give their unsaved text). `kickass` None
        means decide per file from its contents."""
        overrides = {str(Path(k).resolve()): v for k, v in (overrides or {}).items()}
        keep = set()
        for p in files:
            key = str(Path(p).resolve())
            keep.add(key)
            if key in overrides:
                text = overrides[key]
                stamp = ("text", hash(text))
            else:
                try:
                    st = os.stat(key)
                except OSError:
                    continue
                stamp = (st.st_mtime_ns, st.st_size)
                if key in self._files and self._files[key][0] == stamp and \
                        (kickass is None or self._files[key][1] == kickass):
                    continue
                try:
                    data = Path(key).read_bytes()
                except OSError:
                    continue
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = data.decode("cp1252")
            if key in self._files and self._files[key][0] == stamp and \
                    (kickass is None or self._files[key][1] == kickass):
                continue
            kick = looks_like_kick(text) if kickass is None else kickass
            self._files[key] = (stamp, kick, scan(text, key, kick))
        for k in list(self._files):
            if k not in keep:
                del self._files[k]
        self._by_name = {}
        for s in self.symbols():
            if s.kind != "local":
                self._by_name.setdefault(s.name.lower(), []).append(s)

    def symbols(self) -> list[Symbol]:
        return [s for _st, _k, syms in self._files.values() for s, _scope in syms]

    def _kick(self, file: str | None) -> bool:
        return bool(file) and self._files.get(str(Path(file).resolve()), (None, False))[1]

    def definitions(self, name: str, from_file: str | None = None, from_line: int = 0) -> list[Symbol]:
        """Where `name` is defined: the file it's used in first, then the others. A CBM `@local`
        is found under the same label as the line using it."""
        if not name:
            return []
        here = str(Path(from_file).resolve()) if from_file else None
        kick = self._kick(here)
        if name.startswith("@") and here in self._files:
            syms = self._files[here][2]
            scope = ""
            for s, _sc in syms:                     # the label in force at from_line
                if s.kind == "label" and s.line <= from_line:
                    scope = s.name.lower()
            return [s for s, sc in syms if s.kind == "local" and sc == scope and s.name.lower() == name.lower()]
        parts = [name] + (name.split(".")[::-1] if kick and "." in name else [])
        for want in parts:
            found = [s for s in self._by_name.get(want.lower(), [])
                     if s.name == want or not (s.kind == "macro" or self._files[s.file][1])]
            if found:
                found.sort(key=lambda s: (s.file != here, s.file, s.line))
                return found
        return []

    def completions(self, prefix: str, from_file: str | None = None, basic: bool = False,
                    limit: int = 200) -> list[tuple[str, str, Symbol | None]]:
        """What could finish `prefix`: (text, what it is, its definition). The project's names
        (this file's first), then instructions, directives (or BASIC keywords)."""
        if not prefix:
            return []
        here = str(Path(from_file).resolve()) if from_file else None
        kick = self._kick(here)
        low = prefix.lower()
        seen: set[str] = set()
        out: list[tuple[int, str, str, Symbol | None]] = []

        def add(rank, text, what, sym=None):
            key = text if kick else text.lower()
            if key in seen or text == prefix:
                return
            if text.lower().startswith(low):
                seen.add(key)
                out.append((rank, text, what, sym))
            elif len(prefix) >= 2 and low in text.lower():
                seen.add(key)
                out.append((rank + 10, text, what, sym))
        if basic:
            from .basic.tokenizer import KEYWORDS
            for k in sorted(KEYWORDS):
                add(2, k, "BASIC keyword")
        else:
            for s in sorted(self.symbols(), key=lambda s: (s.file != here, s.name.lower())):
                if s.kind == "local" and s.file != here:
                    continue
                add(0 if s.file == here else 1, s.name, f"{s.kind} · {Path(s.file).name}:{s.line}", s)
            for m in _MNEMONICS:
                add(2, m, "instruction")
            if kick:
                for d in KICK_DIRECTIVES:
                    add(3, d.lstrip(".#") if prefix[:1] not in ".#" else d, "directive")
            else:
                for d in sorted(DIRECTIVES):
                    add(3, d, "directive")
        out.sort(key=lambda r: (r[0], r[1].lower()))
        return [(t, w, s) for _r, t, w, s in out[:limit]]


def basic_target(text: str, line_no: int, col: int, prefix: str = "@") -> int | None:
    """In BASIC, the editor line (1-based) a GOTO/GOSUB/THEN/RUN/LIST at (line_no, col) goes to;
    in pBASIC (with `prefix` labels), the line holding the label."""
    from .basic.pbasic import jump_target_at, label_refs
    lines = text.split("\n")
    if not 0 < line_no <= len(lines):
        return None
    line = lines[line_no - 1]
    for s, e, name in label_refs(line, prefix):
        if s <= col <= e:
            want = re.compile(rf"^\s*{re.escape(prefix)}{re.escape(name)}\s*$", re.I)
            return next((i for i, ln in enumerate(lines, start=1) if want.match(ln)), None)
    target = jump_target_at(line, col)
    if target is None:
        return None
    rx = re.compile(rf"^\s*{target}(?!\d)")
    return next((i for i, ln in enumerate(lines, start=1) if rx.match(ln)), None)
