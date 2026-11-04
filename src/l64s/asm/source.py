"""Reading source files, stripping comments, INCASM and macro (DEFM/ENDM) expansion.

The output is a flat list of `Line`s ready for the assembler. Macros are collected from
*all* files first, because in CBM prg Studio projects the library files that define the
macros come after gameMain.asm in the build order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import AsmError, Diagnostic, SourceLoc
from .opcodes import OPCODES, ILLEGAL_OPCODES

# Directives recognised at the start of a statement (case-insensitive).
DIRECTIVES = {
    "byte", "byt", "db", "dfb",
    "word", "wor", "dw", "fltp",
    "text", "dcb", "incbin", "incasm", "operator", "align", "org",
    "defm", "endm", "if", "ifdef", "ifndef", "else", "endif", "equ",
    "generateto", "watch",
    # also from CBM prg Studio's directive list
    "bits", "bytes", "words", "dcw", "null", "ptext", "long", "longs", "func", "funcw", "random", "randomw",
    "relocate", "noloadaddr", "saveblock", "padbyte", "target", "charmap", "charset", "zpopt", "warning",
    "debug", "export", "breakpoint", "debugstartaddress", "checksum", "repeat", "endrepeat", "todo",
}
_TODO_RE = re.compile(r"\s*todo(\s|:|$)", re.I)

LABEL_RE = re.compile(r"[@A-Za-z_][A-Za-z0-9_.@]*\$?")   # a trailing $ makes a label project-wide


@dataclass
class Line:
    code: str              # comment-free source text
    loc: SourceLoc
    called_from: SourceLoc | None = None  # macro call site, for macro body lines
    raw: str = ""          # original text (for listings)


@dataclass
class Macro:
    name: str
    body: list[Line]
    loc: SourceLoc


def strip_comment(text: str, in_block: bool) -> tuple[str, bool]:
    """Remove ';', '//' and '/* */' comments that aren't inside quotes.

    Returns (code, still_in_block_comment).
    """
    out = []
    i = 0
    quote = None
    n = len(text)
    while i < n:
        c = text[i]
        if in_block:
            if text.startswith("*/", i):
                in_block = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            out.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"":
            # A quote opens a string only if it closes on this line (avoids apostrophes in odd places).
            if text.find(c, i + 1) != -1:
                quote = c
            out.append(c)
            i += 1
            continue
        if c == ";":
            break
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            break
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            in_block = True
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out).rstrip(), in_block


def split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split on `sep` outside quotes and parentheses."""
    parts, depth, quote, cur = [], 0, None, []
    for c in text:
        if quote:
            cur.append(c)
            if c == quote:
                quote = None
            continue
        if c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(c)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


class Keywords:
    """What counts as an instruction word (vs. a label) at the start of a line."""

    def __init__(self, illegal: bool):
        self.mnemonics = set(OPCODES) | (set(ILLEGAL_OPCODES) if illegal else set())
        self.macros: dict[str, Macro] = {}

    def is_keyword(self, word: str) -> bool:
        w = word.lower()
        return w in self.mnemonics or w in DIRECTIVES or word in self.macros


def split_label(code: str, kw: Keywords) -> tuple[str | None, str]:
    """Split a code line into (label, rest).

    A label starts in column 1 and is any word that isn't a mnemonic, directive or macro
    name. A trailing ':' is allowed. An indented `NAME = value` also defines a label.
    """
    if not code.strip():
        return None, ""
    if not code[0].isspace():
        m = LABEL_RE.match(code)
        if m:
            word = m.group(0)
            after = code[m.end():]
            if after.startswith(":"):
                return word, after[1:].strip()
            if not kw.is_keyword(word) or after.lstrip().startswith("="):
                return word, after.strip()
        return None, code.strip()
    stripped = code.strip()
    m = LABEL_RE.match(stripped)
    if m:
        after = stripped[m.end():].lstrip()
        if after.startswith("=") and not after.startswith("=="):
            return m.group(0), after
        if after.startswith(":"):
            return m.group(0), after[1:].strip()
        if after.lower().startswith("equ") and (len(after) == 3 or after[3].isspace()):
            return m.group(0), after
    return None, stripped


def first_word(rest: str) -> tuple[str, str]:
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$", rest, re.S)
    if not m:
        return "", rest
    return m.group(1), m.group(2).strip()


def unquote(arg: str) -> str:
    arg = arg.strip()
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "'\"":
        return arg[1:-1]
    return arg


class SourceLoader:
    """Turns a list of files (in build order) into expanded Lines."""

    def __init__(self, illegal: bool = False, overrides: dict[str, str] | None = None):
        self.kw = Keywords(illegal)
        self.diagnostics: list[Diagnostic] = []
        self.files: list[str] = []
        # path -> text, used by the IDE to assemble unsaved editor buffers.
        self.overrides = {str(Path(k).resolve()): v for k, v in (overrides or {}).items()}
        self._expansions = 0

    def error(self, msg: str, loc: SourceLoc | None):
        self.diagnostics.append(Diagnostic("error", msg, loc))

    def read_text(self, path: Path) -> str:
        key = str(path.resolve())
        if key in self.overrides:
            return self.overrides[key]
        data = path.read_bytes()
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1252")

    def load(self, paths: list[Path]) -> list[Line]:
        lines: list[Line] = []
        for p in paths:
            lines.extend(self._read_file(Path(p), depth=0))
        lines = self._collect_macros(lines)
        return self._expand(self._repeats(lines))

    # ---------------------------------------------------------------- REPEAT ... ENDREPEAT
    _CONST_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([$%]?[0-9A-Fa-f]+)\s*$")

    def _number(self, text: str, consts: dict[str, int], loc) -> int:
        t = text.strip()
        try:
            if t.startswith("$"):
                return int(t[1:], 16)
            if t.startswith("%"):
                return int(t[1:], 2)
            if t.lstrip("-").isdigit():
                return int(t)
        except ValueError:
            pass
        if t.lower() in consts:
            return consts[t.lower()]
        raise AsmError(f"REPEAT needs numbers (or constants set to a number earlier): '{t}'")

    def _repeats(self, lines: list[Line]) -> list[Line]:
        """Expand REPEAT blocks. As in CBM prg Studio:
             repeat count[, name]            name runs 1..count
             repeat start, end[, name]       name runs start..end
             repeat start, end, step[, name]
        and `name` in the block is replaced by the counter."""
        consts: dict[str, int] = {}
        out: list[Line] = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            m = self._CONST_RE.match(ln.code)
            if m:
                try:
                    consts[m.group(1).lower()] = self._number(m.group(2), {}, ln.loc)
                except AsmError:
                    pass
            label, rest = split_label(ln.code, self.kw)
            word, args = first_word(rest)
            if word.lower() == "endrepeat":
                self.error("ENDREPEAT without REPEAT", ln.loc)
                i += 1
                continue
            if word.lower() != "repeat":
                out.append(ln)
                i += 1
                continue
            # find the matching ENDREPEAT (blocks may nest)
            depth, j = 1, i + 1
            while j < len(lines):
                w = first_word(split_label(lines[j].code, self.kw)[1])[0].lower()
                depth += 1 if w == "repeat" else -1 if w == "endrepeat" else 0
                if depth == 0:
                    break
                j += 1
            if j >= len(lines):
                self.error("REPEAT without ENDREPEAT", ln.loc)
                return out
            body = self._repeats(lines[i + 1:j])
            parts = split_top_level(args) if args.strip() else []
            name = None
            if parts and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[-1]) and parts[-1].lower() not in consts:
                name = parts.pop()
            try:
                nums = [self._number(x, consts, ln.loc) for x in parts]
                if len(nums) == 1:
                    values = list(range(1, nums[0] + 1))
                elif len(nums) == 2:
                    values = list(range(nums[0], nums[1] + 1))
                elif len(nums) == 3:
                    if nums[2] == 0:
                        raise AsmError("REPEAT's step can't be 0")
                    values = list(range(nums[0], nums[1] + (1 if nums[2] > 0 else -1), nums[2]))
                else:
                    raise AsmError("REPEAT needs a count, or a start and an end (and a step), then an optional name")
                if len(values) > 65536:
                    raise AsmError("REPEAT repeats more than 65536 times")
            except AsmError as e:
                self.error(e.message, ln.loc)
                i = j + 1
                continue
            if label:
                out.append(Line(label, ln.loc, ln.called_from, raw=ln.raw))
            word_re = re.compile(rf"(?<![A-Za-z0-9_@$]){re.escape(name)}(?![A-Za-z0-9_])", re.I) if name else None
            for v in values:
                for b in body:
                    code = word_re.sub(str(v), b.code) if word_re else b.code
                    out.append(Line(code, b.loc, b.called_from, raw=b.raw))
            i = j + 1
        return out

    def _read_file(self, path: Path, depth: int, from_loc: SourceLoc | None = None) -> list[Line]:
        if depth > 16:
            self.error(f"INCASM nested too deeply at {path}", from_loc)
            return []
        try:
            text = self.read_text(path)
        except OSError as e:
            self.error(f"Can't read {path}: {e.strerror}", from_loc)
            return []
        self.files.append(str(path))
        out: list[Line] = []
        in_block = False
        for n, raw in enumerate(text.splitlines(), start=1):
            loc = SourceLoc(str(path), n)
            if not in_block and _TODO_RE.match(raw):
                out.append(Line("", loc, raw=raw))      # TODO: a task for the Tasks list; not code
                continue
            code, in_block = strip_comment(raw.rstrip("\r\n"), in_block)
            label, rest = split_label(code, self.kw)
            word, args = first_word(rest)
            if word.lower() == "incasm":
                if label:
                    out.append(Line(label, loc, raw=raw))
                inc = path.parent / unquote(args)
                out.extend(self._read_file(inc, depth + 1, loc))
                continue
            out.append(Line(code, loc, raw=raw))
        return out

    def _collect_macros(self, lines: list[Line]) -> list[Line]:
        # First find macro names, so col-1 words that are macro calls aren't taken as labels.
        for ln in lines:
            word, args = first_word(ln.code.strip())
            if word.lower() == "defm":
                name, _ = first_word(args)
                if name:
                    self.kw.macros[name] = Macro(name, [], ln.loc)
        out: list[Line] = []
        current: Macro | None = None
        for ln in lines:
            label, rest = split_label(ln.code, self.kw)
            word, args = first_word(rest)
            w = word.lower()
            if w == "defm":
                if current:
                    self.error(f"DEFM inside macro {current.name} (missing ENDM?)", ln.loc)
                name, _ = first_word(args)
                if not name:
                    self.error("DEFM needs a macro name", ln.loc)
                    continue
                current = self.kw.macros[name]
                if current.body:
                    self.error(f"Macro {name} is defined twice", ln.loc)
                    current.body = []
                current.loc = ln.loc
                continue
            if w == "endm":
                if not current:
                    self.error("ENDM without DEFM", ln.loc)
                else:
                    if label:
                        current.body.append(Line(label, ln.loc, raw=ln.raw))
                    current = None
                continue
            if current:
                current.body.append(ln)
            else:
                out.append(ln)
        if current:
            self.error(f"Macro {current.name} has no ENDM", current.loc)
        return out

    _PARAM_RE = re.compile(r"(?<![A-Za-z0-9_)$])/([1-9])(?![0-9])")
    _LOCAL_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")

    def _expand(self, lines: list[Line], depth: int = 0) -> list[Line]:
        out: list[Line] = []
        for ln in lines:
            label, rest = split_label(ln.code, self.kw)
            word, args = first_word(rest)
            macro = self.kw.macros.get(word) if word else None
            if macro is None:
                out.append(ln)
                continue
            if depth > 32:
                self.error(f"Macro {macro.name} expands recursively", ln.loc)
                continue
            if label:
                out.append(Line(label, ln.loc, ln.called_from, raw=ln.raw))
            argv = split_top_level(args) if args.strip() else []
            self._expansions += 1
            tag = f"__m{self._expansions}"
            body: list[Line] = []
            for b in macro.body:
                def sub(m: re.Match) -> str:
                    idx = int(m.group(1)) - 1
                    if idx >= len(argv):
                        raise AsmError(f"Macro {macro.name} uses /{idx + 1} but only {len(argv)} parameter(s) given")
                    return argv[idx] if argv[idx].strip() else "0"      # an empty parameter is 0 (CBM prg Studio)
                try:
                    code = self._PARAM_RE.sub(sub, b.code)
                except AsmError as e:
                    self.error(e.message, ln.loc)
                    break
                code = self._LOCAL_RE.sub(lambda m: f"@{m.group(1)}{tag}", code)
                body.append(Line(code, SourceLoc(b.loc.file, b.loc.line, macro.name),
                                 ln.called_from or ln.loc, raw=b.raw))
            out.extend(self._expand(body, depth + 1))
        return out
