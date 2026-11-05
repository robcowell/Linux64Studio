"""Where things are defined, for the editor's Go to Definition and auto-complete.

The project's sources are scanned line by line (not assembled), so it works while code is being
written and doesn't compile. Both dialects are read:

* CBM prg Studio: a label in column 1 (`loop`, `loop:`), `NAME = value`, `defm NAME`, and `@local`
  labels, which belong to the label before them. Labels are any case; macros are case-sensitive.
* Kick Assembler: `name:` labels, `.const`/`.var`/`.label NAME =`, `.macro`/`.function`/
  `.pseudocommand name`, `.namespace name`. Everything is case-sensitive; `!name:` labels are
  skipped (there are many of each).

* ca65, cc65's assembler (.s files in C projects): `name:` labels, `@cheap` locals (belonging to
  the label before them), `NAME = value` / `:=` / `.set`, `.define`, `.macro`, `.proc` (a label
  too), `.scope`/`.struct`/`.union`/`.enum` (and an enum's members). Names are case-sensitive.
* C (.c and .h, cc65 projects), read by cvars: functions (a definition before a prototype),
  global variables, macros, typedefs, struct/union/enum tags and enum constants, and each
  function's parameters and locals (found first from inside that function). C names are
  case-sensitive.

Also: the file an `incasm`/`incbin`/`#import`/`.import`/`#include` line names, and in BASIC the
line a GOTO/GOSUB goes to (or a pBASIC `@label`).
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
CA65_DIRECTIVES = sorted("." + d for d in (
    "a16 a8 addr align asciiz assert autoimport bankbytes bss byt byte case charmap code condes constructor "
    "cpu data dbyt debuginfo define delmac delmacro destructor dword else elseif end endenum endif endmac "
    "endmacro endproc endrep endrepeat endscope endstruct endunion enum error exitmac exitmacro export "
    "exportzp faraddr fatal feature fileopt fopt forceimport global globalzp hibytes i16 i8 if ifblank "
    "ifconst ifdef ifnblank ifndef ifnref ifp02 ifp816 ifpc02 ifref import importzp incbin include "
    "interruptor linecont list listbytes literal lobytes local localchar macpack mac macro org out p02 "
    "p816 pagelen pagelength pc02 popcpu popseg proc pushcpu pushseg referto reloc repeat res rodata "
    "scope segment set setcpu smart struct tag undef undefine union warning word zeropage "
    "addrsize bank bankbyte blank concat const def defined definedmacro hibyte hiword ident ismnemonic "
    "left lobyte loword match max mid min ref referenced right sizeof sprintf strat string strlen tcount "
    "time version xmatch").split())
_CA65_LABEL = re.compile(r"^\s*(@?[A-Za-z_]\w*):(?![:=+\-<>])")      # (not "bne :-")
_CA65_CONST = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?::?=|\.set\b)")
_CA65_NAMED = re.compile(r"^\s*(?:[A-Za-z_]\w*\s*:\s*)?\.(define|macro|mac|proc|scope|struct|union|enum)\s+"
                         r"([A-Za-z_]\w*)", re.I)
_C_INCLUDE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]')
C_EXTS = (".c", ".h")
C_KEYWORDS = sorted({"auto", "break", "case", "char", "const", "continue", "default", "do", "else", "enum",
                     "extern", "for", "goto", "if", "int", "long", "register", "return", "short", "signed",
                     "sizeof", "static", "struct", "switch", "typedef", "union", "unsigned", "void", "volatile",
                     "while", "__fastcall__", "__asm__", "#include", "#define", "#ifdef", "#ifndef", "#endif",
                     "#pragma", "NULL"})
# the kinds a C name can be (Symbol.kind), as they're described to the user
C_KINDS = {"c-function": "function", "c-prototype": "function declaration", "c-variable": "variable",
           "c-extern": "extern variable", "c-typedef": "typedef", "c-struct": "struct", "c-union": "union",
           "c-enum": "enum", "c-enumconst": "enum constant", "c-macro": "macro", "c-param": "parameter",
           "c-local": "local variable"}
_C_DEFINITION_ORDER = ["c-local", "c-param", "c-function", "c-variable", "c-typedef", "c-struct", "c-union",
                       "c-enum", "c-enumconst", "c-macro", "c-prototype", "c-extern"]
_INCLUDE = re.compile(r"^\s*(?:[A-Za-z_][\w.]*:?\s+)?(incasm|incbin|\.include|\.incbin|#import|#importif\s+\S+|"
                      r"\.import\s+\w+)"
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


CA65_EXTS = (".s", ".asm", ".inc", ".a")


def scan_ca65(text: str, file: str = "") -> list[tuple[Symbol, str]]:
    """The definitions in a ca65 file, each with its scope (for @cheap locals: the label before)."""
    out: list[tuple[Symbol, str]] = []
    scope = ""
    in_enum = False
    for n, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        shown = raw.strip()
        low = line.strip().lower()
        if in_enum:
            if low.startswith(".endenum"):
                in_enum = False
                continue
            m = re.match(r"\s*([A-Za-z_]\w*)", line)
            if m:
                out.append((Symbol(m.group(1), "const", file, n, m.start(1), shown), ""))
            continue
        m = _CA65_NAMED.match(line)
        if m:
            kind = {"define": "const", "macro": "macro", "mac": "macro", "proc": "label"}.get(m.group(1).lower(),
                                                                                          "namespace")
            out.append((Symbol(m.group(2), kind, file, n, m.start(2), shown), ""))
            if kind == "label":
                scope = m.group(2).lower()
            in_enum = m.group(1).lower() == "enum"
            continue
        m = _CA65_LABEL.match(line)
        if m and m.group(1).lower() not in OPCODES:
            name = m.group(1)
            if name.startswith("@"):
                out.append((Symbol(name, "local", file, n, m.start(1), shown), scope))
            else:
                scope = name.lower()
                out.append((Symbol(name, "label", file, n, m.start(1), shown), ""))
            continue
        m = _CA65_CONST.match(line)
        if m and m.group(1).lower() not in OPCODES:
            kind = "var" if ".set" in line[m.end(1):m.end()].lower() else "const"
            out.append((Symbol(m.group(1), kind, file, n, m.start(1), shown), ""))
    return out


_CA65_UNNAMED_DEF = re.compile(r"^\s*:(?![:=+\-<>])")
_CA65_UNNAMED_REF = re.compile(r":(\++|-+|<+|>+)")


def ca65_unnamed_target(lines: list[str], line_no: int, col: int) -> int | None:
    """The line of the unnamed label (``:``) a ``:+``/``:-`` (or ``:>``/``:<``) at the cursor refers
    to: ``:-`` the nearest at or above the line (one at the start of the line comes before its
    instruction), ``:--`` the one before that; ``:+`` the next below. None if the cursor isn't on one."""
    if not 0 < line_no <= len(lines):
        return None
    text = _strip_comment(lines[line_no - 1])
    for m in _CA65_UNNAMED_REF.finditer(text):
        if m.start() <= col <= m.end():
            marks = m.group(1)
            back, count = marks[0] in "-<", len(marks)
            break
    else:
        return None
    defs = [n for n, ln in enumerate(lines, start=1) if _CA65_UNNAMED_DEF.match(_strip_comment(ln))]
    if back:
        before = [n for n in defs if n <= line_no]
        return before[-count] if len(before) >= count else None
    after = [n for n in defs if n > line_no]
    return after[count - 1] if len(after) >= count else None


def is_c(file: str | Path | None) -> bool:
    return bool(file) and Path(file).suffix.lower() in C_EXTS


def scan_c(text: str, file: str = "") -> tuple[list[tuple[Symbol, str]], list[tuple[str, int, int]]]:
    """A C file's names (each with the function it belongs to, for parameters and locals), and its
    functions' line ranges."""
    from .cvars import parse_source
    src = parse_source(text)
    lines = text.splitlines()

    def sym(name: str, kind: str, line: int) -> Symbol:
        shown = lines[line - 1] if 0 < line <= len(lines) else ""
        col = max(0, shown.find(name))
        return Symbol(name, kind, file, line, col, shown.strip())
    out = [(sym(name, f"c-{kind}", line), "") for name, kind, line in src.symbols]
    funcs = []
    for fn in src.functions.values():
        funcs.append((fn.name, fn.first_line, fn.last_line))
        for name, _t in fn.params:
            out.append((sym(name, "c-param", fn.param_lines.get(name, fn.first_line)), fn.name))
        for name, _t, decl, _end in fn.locals:
            out.append((sym(name, "c-local", decl), fn.name))
    return out, funcs


def c_word_at(line: str, col: int) -> tuple[int, int, str]:
    """The C name at a column (letters, digits and _)."""
    s = col
    while s > 0 and (line[s - 1].isalnum() or line[s - 1] == "_"):
        s -= 1
    e = col
    while e < len(line) and (line[e].isalnum() or line[e] == "_"):
        e += 1
    word = line[s:e]
    return (s, e, word) if word and not word[0].isdigit() else (s, e, "")


def c_include_at(line: str, here: Path, search: list[Path]) -> Path | None:
    """The header an ``#include`` line names: "x.h" from the file's folder first, then the search
    folders; <x.h> from the search folders (cc65's own headers among them). None if it isn't one."""
    m = _C_INCLUDE.match(line)
    if not m:
        return None
    name = m.group(2).strip()
    folders = ([here] if m.group(1) == '"' else []) + list(search)
    for d in folders:
        if (d / name).is_file():
            return (d / name).resolve()
    return (folders[0] / name) if folders else Path(name)


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
        self._c_funcs: dict[str, list[tuple[str, int, int]]] = {}   # C file -> its functions' line ranges
        self._ca65: set[str] = set()                                 # the files read as ca65
        self._by_name: dict[str, list[Symbol]] = {}       # lower-case name -> its definitions (not locals)

    def update(self, files: list[Path], overrides: dict[str, str] | None = None, kickass: bool | None = None,
               ca65: bool = False):
        """Scan `files` (paths as strings in `overrides` give their unsaved text). `kickass` None
        means decide per file from its contents. `ca65`: a C project, whose assembler is ca65."""
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
                        (kickass is None or self._files[key][1] == kickass or (ca65 and key in self._ca65)):
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
                    (kickass is None or self._files[key][1] == kickass or (ca65 and key in self._ca65)):
                continue
            if is_c(key):
                syms, funcs = scan_c(text, key)
                self._files[key] = (stamp, False, syms)
                self._c_funcs[key] = funcs
                continue
            if ca65 and Path(key).suffix.lower() in CA65_EXTS:
                self._files[key] = (stamp, True, scan_ca65(text, key))     # (case-sensitive, as Kick's)
                self._ca65.add(key)
                continue
            self._ca65.discard(key)
            kick = looks_like_kick(text) if kickass is None else kickass
            self._files[key] = (stamp, kick, scan(text, key, kick))
        for k in list(self._files):
            if k not in keep:
                del self._files[k]
                self._c_funcs.pop(k, None)
        self._by_name = {}
        for s in self.symbols():
            if s.kind not in ("local", "c-local", "c-param"):
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
        if is_c(here):
            return self._c_definitions(name, here, from_line)
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
        if name.startswith("_") and len(name) > 1:          # assembler calling C: jsr _twice
            return [s for s in self._c_definitions(name[1:], None, 0) if s.kind in ("c-function", "c-variable")]
        return []

    def _c_function_at(self, file: str, line: int) -> str | None:
        best = None
        for name, first, last in self._c_funcs.get(file, []):
            if first <= line <= last and (best is None or first > best[1]):
                best = (name, first)
        return best[0] if best else None

    def _c_definitions(self, name: str, here: str | None, from_line: int) -> list[Symbol]:
        """Where a C name is defined: a parameter or local of the function the line is in, else the
        program's definitions (a function's body before its prototypes), this file's first."""
        fn = self._c_function_at(here, from_line) if here else None
        if fn:
            mine = [s for s, scope in self._files[here][2] if scope == fn and s.name == name]
            if mine:
                return sorted(mine, key=lambda s: s.line)
        found = [s for s in self._by_name.get(name.lower(), []) if s.name == name and s.kind.startswith("c-")]
        order = {k: i for i, k in enumerate(_C_DEFINITION_ORDER)}
        found.sort(key=lambda s: (order.get(s.kind, 99), s.file != here, s.file, s.line))
        return found

    def completions(self, prefix: str, from_file: str | None = None, basic: bool = False,
                    limit: int = 200, from_line: int = 0) -> list[tuple[str, str, Symbol | None]]:
        """What could finish `prefix`: (text, what it is, its definition). The project's names
        (this file's first), then instructions, directives (or BASIC keywords)."""
        if not prefix:
            return []
        here = str(Path(from_file).resolve()) if from_file else None
        kick = self._kick(here) or is_c(here)        # (both case-sensitive)
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
        if is_c(here):
            fn = self._c_function_at(here, from_line) if from_line else None
            for s, scope in self._files.get(here, (None, False, []))[2]:
                if scope and scope == fn:
                    add(0, s.name, f"{C_KINDS[s.kind]} in {fn}()", s)
            for s in sorted(self.symbols(), key=lambda s: (s.file != here, s.name.lower())):
                if s.kind.startswith("c-") and s.kind not in ("c-local", "c-param"):
                    add(0 if s.file == here else 1, s.name, f"{C_KINDS[s.kind]} · {Path(s.file).name}:{s.line}", s)
            for k in C_KEYWORDS:
                add(2, k, "C keyword")
        elif basic:
            from .basic.tokenizer import KEYWORDS
            for k in sorted(KEYWORDS):
                add(2, k, "BASIC keyword")
        else:
            for s in sorted(self.symbols(), key=lambda s: (s.file != here, s.name.lower())):
                if (s.kind == "local" and s.file != here) or s.kind.startswith("c-"):
                    continue
                add(0 if s.file == here else 1, s.name, f"{s.kind} · {Path(s.file).name}:{s.line}", s)
            for m in _MNEMONICS:
                add(2, m, "instruction")
            if here in self._ca65:
                for d in CA65_DIRECTIVES:
                    add(3, d, "ca65 control command")
            elif kick:
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
