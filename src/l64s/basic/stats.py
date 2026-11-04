"""BASIC program statistics, as CBM prg Studio's Statistics tool gives them: the variables a
program sets and the line each is first set on, and the variables that are really the same one.

On the C64 only the first two characters of a variable's name count (and its type: $ string,
% integer, or neither for a number; arrays are separate from plain variables), so SCORE and
SCALE are the same variable, SC. A keyword inside a name is read as that keyword (SCORE is
SC OR E), which is a common mistake, so those are listed too, along with jumps to lines that
don't exist and assignments to the system variables ST and TI.

The program is read as the C64 reads it: tokenised, so keywords are found where the ROM finds
them, and strings, REM and DATA are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .renumber import find_line_refs
from .tokenizer import BasicErrors, KEYWORDS, TOKEN, crunch, parse_source, tokenize

BASIC_BYTES = 38911                 # what the C64 says is free when it's switched on ($0801-$9FFF)
_T = TOKEN
_ASSIGN_LISTS = {_T["input"]: "input", _T["input#"]: "input#", _T["get"]: "get", _T["read"]: "read"}
_QUOTE, _COLON = 0x22, 0x3A
_NAME = re.compile(rb"[A-Z][A-Z0-9]*[$%]?")


@dataclass
class Variable:
    key: str                        # what the C64 sees: SC, SC$, SC% (arrays end in "(")
    spellings: list[str] = field(default_factory=list)   # as written, in the order met
    first_set: int | None = None    # BASIC line number
    how: str = ""                   # "=", "for", "input", "read", "get", "dim"
    lines_used: list[int] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.spellings[0] if self.spellings else self.key

    @property
    def kind(self) -> str:
        base = self.key.rstrip("(")
        t = "string" if base.endswith("$") else "integer" if base.endswith("%") else "number"
        return t + (" array" if self.key.endswith("(") else "")


@dataclass
class Problem:
    line: int                       # BASIC line number
    message: str


@dataclass
class Stats:
    variables: dict[str, Variable]
    lines: int
    start: int
    size: int                       # bytes in memory, including the end marker
    problems: list[Problem]
    keyword_words: list[Problem]    # names with a keyword inside
    source_line: dict[int, int] = field(default_factory=dict)   # BASIC line number -> line in the file

    @property
    def end(self) -> int:
        return self.start + self.size - 1

    @property
    def free(self) -> int:
        return BASIC_BYTES - self.size

    def assigned(self) -> list[Variable]:
        return sorted((v for v in self.variables.values() if v.first_set is not None),
                      key=lambda v: (v.first_set, v.key))

    def duplicates(self) -> list[Variable]:
        return [v for v in self.assigned() if len(v.spellings) > 1]

    def never_set(self) -> list[Variable]:
        return sorted((v for v in self.variables.values() if v.first_set is None),
                      key=lambda v: (v.lines_used[0] if v.lines_used else 0, v.key))


def _significant(name: str) -> str:
    suffix = name[-1] if name[-1] in "$%" else ""
    base = name[:-1] if suffix else name
    return base[:2] + suffix


def _statements(data: bytes):
    """The statements of a tokenised line, as byte strings, without strings, REM or DATA text."""
    out, cur, i = [], bytearray(), 0
    while i < len(data):
        b = data[i]
        if b == _QUOTE:
            j = data.find(b'"', i + 1)
            cur += b'"'                     # keep a placeholder so names either side stay apart
            i = len(data) if j < 0 else j + 1
            continue
        if b == _T["rem"]:
            break
        if b == _T["data"]:
            cur.append(b)
            j = i + 1
            while j < len(data) and data[j] != _COLON:
                if data[j] == _QUOTE:
                    k = data.find(b'"', j + 1)
                    j = len(data) if k < 0 else k + 1
                else:
                    j += 1
            i = j
            continue
        if b == _COLON:
            out.append(bytes(cur))
            cur = bytearray()
        else:
            cur.append(b)
        i += 1
    out.append(bytes(cur))
    return [s for s in out if s.strip()]


def _names(stmt: bytes):
    """(name, is_array, offset) for each variable reference in a statement."""
    out = []
    i = 0
    while i < len(stmt):
        b = stmt[i]
        if b == _T["fn"]:                      # FN name(...): a function, not a variable
            m = _NAME.match(stmt, i + 1 + (stmt[i + 1:i + 2] == b" "))
            i = m.end() if m else i + 1
            continue
        if 0x41 <= b <= 0x5A and (i == 0 or not (0x30 <= stmt[i - 1] <= 0x39 or 0x41 <= stmt[i - 1] <= 0x5A)):
            m = _NAME.match(stmt, i)
            j = m.end()
            k = j
            while k < len(stmt) and stmt[k] == 0x20:
                k += 1
            out.append((m.group(0).decode(), k < len(stmt) and stmt[k] == 0x28, i))
            i = j
            continue
        if 0x30 <= b <= 0x39 or b == 0x2E:     # a number: skip it (and any E exponent)
            m = re.compile(rb"[0-9.]+(E[+-]?[0-9]+)?").match(stmt, i)
            i = m.end() if m else i + 1
            continue
        i += 1
    return out


def _assigned_in(stmt: bytes, names) -> dict[int, str]:
    """{offset of a name: how it's set} for the names a statement gives a value to."""
    s = stmt.lstrip(b" ")
    lead = len(stmt) - len(s)
    out: dict[int, str] = {}
    if not s:
        return out
    first = s[0]
    if first == _T["for"] and names:
        out[names[0][2]] = "for"
    elif first == _T["let"] and names:
        out[names[0][2]] = "="
    elif first in _ASSIGN_LISTS:
        how = _ASSIGN_LISTS[first]
        body_from = lead + 1
        if how == "get" and stmt[body_from:].lstrip(b" ")[:1] == b"#":
            how = "get#"                       # GET# is GET followed by #
        if how.endswith("#"):                  # skip the channel number, up to the first comma
            comma = stmt.find(b",", body_from)
            body_from = comma + 1 if comma >= 0 else len(stmt)
        if how == "input":                     # skip a prompt: INPUT "name";A$
            semi = stmt.find(b";", body_from)
            quote = stmt.find(b'"', body_from)
            if quote >= 0 and semi > quote:
                body_from = semi + 1
        depth = 0
        for name, arr, off in names:
            if off < body_from:
                continue
            # only names at the top level of the list (not inside an array index)
            depth = stmt[body_from:off].count(b"(") - stmt[body_from:off].count(b")")
            if depth == 0:
                out[off] = how
    elif first == _T["dim"]:
        for name, arr, off in names:
            depth = stmt[:off].count(b"(") - stmt[:off].count(b")")
            if arr and depth == 0:
                out[off] = "dim"
    elif names and names[0][2] == lead:
        # an implicit LET: NAME = ... or NAME(...) = ...
        name, arr, off = names[0]
        j = off + len(name)
        if arr:
            depth = 0
            while j < len(stmt):
                depth += {0x28: 1, 0x29: -1}.get(stmt[j], 0)
                j += 1
                if depth == 0:
                    break
        rest = stmt[j:].lstrip(b" ")
        if rest[:1] == bytes([_T["="]]):
            out[off] = "="
    return out


def _keyword_inside(word: str) -> str | None:
    """How the C64 reads a word if a keyword hides inside it after a letter (SCORE is SC OR E)."""
    try:
        data = crunch(word)
    except Exception:
        return None
    for i, b in enumerate(data):
        if b >= 0x80 and i > 0 and 0x41 <= data[i - 1] <= 0x5A:
            parts, run = [], ""
            for c in data:
                if c >= 0x80:
                    if run:
                        parts.append(run)
                        run = ""
                    parts.append(KEYWORDS[c - 0x80].upper())
                else:
                    run += chr(c)
            if run:
                parts.append(run)
            return " ".join(parts)
    return None


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*[$%]?")


def _words_outside_strings(body: str):
    low = body
    i, out = 0, []
    while i < len(low):
        c = low[i]
        if c == '"':
            j = low.find('"', i + 1)
            i = len(low) if j < 0 else j + 1
            continue
        m = _WORD.match(low, i)
        if m:
            w = m.group(0)
            lw = w.lower()
            if lw.startswith("rem") or lw.startswith("data"):
                break
            out.append(w)
            i = m.end()
            continue
        i += 1
    return out


def analyse(text: str) -> Stats:
    """Statistics for a BASIC program in listing notation. Raises BasicErrors if it won't tokenise."""
    result = tokenize(text)
    entries, _ = parse_source(text)
    body_of = {num: body for num, body, _src in entries}
    numbers = {ln.number for ln in result.lines}
    variables: dict[str, Variable] = {}
    problems: list[Problem] = []
    keyword_words: list[Problem] = []
    seen_words: set[str] = set()
    for ln in result.lines:
        for stmt in _statements(ln.data):
            names = _names(stmt)
            if stmt.lstrip(b" ")[:1] == bytes([_T["def"]]):
                # DEF FN name(param)=...: the parameter is local to the function, not a variable
                open_ = stmt.find(b"(")
                close = stmt.find(b")", open_ + 1)
                params = {n[0] for n in names if open_ < n[2] < close}
                names = [n for n in names if n[0] not in params]
            sets = _assigned_in(stmt, names)
            for name, arr, off in names:
                key = _significant(name) + ("(" if arr else "")
                v = variables.setdefault(key, Variable(key))
                if name not in v.spellings:
                    v.spellings.append(name)
                if not v.lines_used or v.lines_used[-1] != ln.number:
                    v.lines_used.append(ln.number)
                how = sets.get(off)
                if how:
                    if v.first_set is None:
                        v.first_set, v.how = ln.number, how
                    base = key.rstrip("(")
                    if base in ("ST", "TI") and not arr:
                        problems.append(Problem(ln.number, f"{name} is the system variable {base}: "
                                                           f"BASIC won't let you set it (TI$ can be set)"))
        body = body_of.get(ln.number, "")
        for ref in find_line_refs(body):
            target = int(body[ref.start:ref.end])
            if target not in numbers:
                problems.append(Problem(ln.number, f"Line {ln.number} jumps to line {target}, which doesn't exist"))
        for w in _words_outside_strings(body):
            key = w.lower()
            if key in seen_words:
                continue
            reading = _keyword_inside(w)
            if reading:
                seen_words.add(key)
                keyword_words.append(Problem(ln.number, f"{w} is read as {reading}"))
    size = len(result.program)
    return Stats(variables, len(result.lines), result.start, size, problems, keyword_words,
                 {ln.number: ln.source_line for ln in result.lines})


def report(st: Stats, title: str = "") -> str:
    """The statistics as text, in the style of CBM prg Studio's."""
    out = ["BASIC Program Statistics" + (f": {title}" if title else ""), "-" * 24, "",
           f"Lines: {st.lines}   Start: ${st.start:04X} ({st.start})   End: ${st.end:04X} ({st.end})   "
           f"Size: {st.size} bytes   Free: {st.free} of {BASIC_BYTES} bytes", "",
           f"{'Variable':<20}{'Type':<16}Line First Used (assignment)",
           "-" * 64]
    for v in st.assigned():
        out.append(f"{v.name + (' (' + ', '.join(v.spellings[1:]) + ')' if len(v.spellings) > 1 else ''):<20}"
                   f"{v.kind:<16}{v.first_set} ({v.how})")
    dups = st.duplicates()
    if dups:
        out += ["", "Duplicate Variables (only the first two characters count)", "-" * 64]
        out += [f"{' = '.join(v.spellings):<36}all {v.key}, first set on line {v.first_set}" for v in dups]
    never = st.never_set()
    if never:
        out += ["", "Used but never set (they're 0, or empty for strings)", "-" * 64]
        out += [f"{v.name:<20}{v.kind:<16}line {v.lines_used[0]}" for v in never]
    if st.keyword_words:
        out += ["", "Names with a keyword inside", "-" * 64] + [f"line {p.line}: {p.message}" for p in st.keyword_words]
    if st.problems:
        out += ["", "Problems", "-" * 64] + [f"line {p.line}: {p.message}" for p in st.problems]
    return "\n".join(out) + "\n"


__all__ = ["BasicErrors", "Stats", "Variable", "analyse", "report"]
