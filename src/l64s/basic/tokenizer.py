"""Commodore BASIC V2 tokenizer and detokenizer.

Tokenizing follows the C64 ROM's CRUNCH routine, so programs behave as if typed in:
  * keywords are matched in ROM table order wherever they occur, even inside a variable
    name (`score` crunches the `or`, exactly as on a real C64)
  * `?` becomes PRINT
  * characters $30-$3B (digits, `:` and `;`) are never crunched
  * nothing is crunched inside quotes or after REM, and DATA is left alone up to the next `:`
  * spaces are kept
"""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field

from .petscii import ControlCodeError, char_to_petscii, parse_control, petscii_to_text

# Token $80 + index
KEYWORDS = [
    "end", "for", "next", "data", "input#", "input", "dim", "read", "let", "goto", "run", "if",
    "restore", "gosub", "return", "rem", "stop", "on", "wait", "load", "save", "verify", "def",
    "poke", "print#", "print", "cont", "list", "clr", "cmd", "sys", "open", "close", "get", "new",
    "tab(", "to", "fn", "spc(", "then", "not", "step", "+", "-", "*", "/", "^", "and", "or", ">",
    "=", "<", "sgn", "int", "abs", "usr", "fre", "pos", "sqr", "rnd", "log", "exp", "cos", "sin",
    "tan", "atn", "peek", "len", "str$", "val", "asc", "chr$", "left$", "right$", "mid$", "go",
]
TOKEN = {kw: 0x80 + i for i, kw in enumerate(KEYWORDS)}
PI = 0xFF
DATA, REM, PRINT = TOKEN["data"], TOKEN["rem"], TOKEN["print"]
# Keywords followed by line numbers (for renumbering and checks)
LINE_REF_TOKENS = {TOKEN["goto"], TOKEN["gosub"], TOKEN["then"], TOKEN["run"], TOKEN["list"]}

MAX_LINE_NUMBER = 63999
MAX_LINE_BYTES = 250  # the ROM's input buffer is 80 characters, but crunched lines up to ~250 bytes load fine


class BasicError(Exception):
    def __init__(self, message: str, line: int | None = None, file: str | None = None):
        super().__init__(message)
        self.message = message
        self.line = line  # 1-based source line
        self.file = file


@dataclass
class BasicLine:
    number: int
    data: bytes          # crunched bytes (without link, number or terminator)
    source_line: int     # 1-based line in the source file
    file: str | None = None


@dataclass
class TokenizeResult:
    lines: list[BasicLine]
    start: int
    program: bytes                 # the bytes that load at `start` (no load address)
    warnings: list[BasicError] = field(default_factory=list)

    def prg(self) -> bytes:
        return bytes([self.start & 0xFF, self.start >> 8]) + self.program

    @property
    def end(self) -> int:
        return self.start + len(self.program)


def _source_bytes(text: str, line_no: int) -> list[tuple[int, bool]]:
    """Convert source characters to PETSCII, tracking which bytes came from {codes}.

    Returns (byte, literal, shifted, start, end): literal bytes (from {codes}) are never part of a
    keyword; shifted is a capital letter outside a string (a keyword's abbreviation ends with
    one: pO); start and end are where it is in `text`.
    """
    out: list[tuple[int, bool, bool, int, int]] = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            close = text.find("}", i)
            if close == -1:
                raise BasicError("'{' without a closing '}'", line_no)
            try:
                out.extend((b, True, False, i, close + 1) for b in parse_control(text[i + 1:close]))
            except ControlCodeError as e:
                raise BasicError(str(e), line_no)
            i = close + 1
            continue
        if ch == '"':
            in_string = not in_string
        try:
            out.append((char_to_petscii(ch, in_string), False, not in_string and "A" <= ch <= "Z", i, i + 1))
        except ControlCodeError as e:
            raise BasicError(str(e), line_no)
        i += 1
    return out


_KW_BYTES = [(bytes(ord(c) - 32 if "a" <= c <= "z" else ord(c) for c in kw), 0x80 + i, kw)
             for i, kw in enumerate(KEYWORDS)]


def match_keyword(src, i: int, table=None) -> tuple[int | bytes, int, str] | None:
    """The keyword at src[i] as (token, how many bytes), as the ROM finds it: the first in its
    table that matches, written in full or abbreviated. An abbreviation is the start of the
    keyword ending in a shifted (capital) letter after a lower-case one, `pO` for POKE, `pR` for
    PRINT#. A word all in capitals is the keyword in full (PRINT), and `goTo` is GOTO, since the
    letters after the capital carry on spelling it.

    Returns (token, how many bytes, the keyword). `table` is a token file's (tokenfile.table);
    a token may be two bytes."""
    n = len(src)
    for kw, tok, name in (table or _KW_BYTES):
        k = len(kw)
        j = 0
        while j < k:
            if i + j >= n:
                break
            b, literal, shifted = src[i + j][0], src[i + j][1], src[i + j][2]
            if literal or b != kw[j]:
                break
            if shifted and j >= 1 and not src[i + j - 1][2]:
                rest = kw[j + 1:]
                carries_on = rest and i + j + len(rest) < n + 1 and all(
                    i + j + 1 + q < n and src[i + j + 1 + q][0] == rest[q] and not src[i + j + 1 + q][1]
                    for q in range(len(rest)))
                if not carries_on:
                    return tok, j + 1, name          # abbreviated
            j += 1
        if j == k:
            return tok, k, name
    return None


def crunch(text: str, line_no: int = 0, table=None) -> bytes:
    """Crunch the text of one line (after its line number), with BASIC V2's keywords or a token
    file's `table`."""
    src = _source_bytes(text, line_no)
    out = bytearray()
    i = 0
    in_quote = False
    in_data = False
    in_rem = False
    n = len(src)
    while i < n:
        b, literal = src[i][0], src[i][1]
        if in_rem:
            out.append(b)
            i += 1
            continue
        if b == 0x22:  # quote
            in_quote = not in_quote
            out.append(b)
            i += 1
            continue
        if in_quote or literal:
            out.append(b)
            i += 1
            continue
        if b == 0x20:
            out.append(b)
            i += 1
            continue
        if in_data:
            out.append(b)
            if b == 0x3A:  # ':' ends DATA
                in_data = False
            i += 1
            continue
        if b == 0x3F:  # '?'
            pr = next((tok for _kw, tok, name in table if name == "print"), PRINT) if table else PRINT
            out += pr if isinstance(pr, bytes) else bytes([pr])
            i += 1
            continue
        if 0x30 <= b <= 0x3B:
            out.append(b)
            i += 1
            continue
        token = match_keyword(src, i, table)
        if token:
            tok, k, name = token
            out += tok if isinstance(tok, bytes) else bytes([tok])
            i += k
            if name == "data":
                in_data = True
            elif name == "rem":
                in_rem = True
            continue
        out.append(b)
        i += 1
    return bytes(out)


# The ROM skips every space between the line number and the text (CHRGET skips spaces).
_LINE_RE = re.compile(r"^\s*(\d+)\s*(.*)$")
_REGION = re.compile(r"^\s*#(end)?region\b", re.I)
_TOKENFILE = re.compile(r"^\s*tokenfile\s+\S", re.I)      # names a token file (tokenfile.py), not a line


def parse_source(text: str) -> tuple[list[tuple[int, str, int]], list[BasicError]]:
    """Split source into (line number, text, source line) entries, sorted by line number."""
    entries: dict[int, tuple[str, int]] = {}
    warnings: list[BasicError] = []
    errors: list[BasicError] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r\n")
        if not line.strip() or _REGION.match(line) or _TOKENFILE.match(line):    # a fold, or the token file
            continue
        m = _LINE_RE.match(line)
        if not m:
            errors.append(BasicError("Line number missing", n))
            continue
        number = int(m.group(1))
        if number > MAX_LINE_NUMBER:
            errors.append(BasicError(f"Line number {number} is above {MAX_LINE_NUMBER}", n))
            continue
        if number in entries:
            errors.append(BasicError(f"Line {number} is used twice (also on source line {entries[number][1]})", n))
            continue
        entries[number] = (m.group(2), n)
    if errors:
        raise BasicErrors(errors)
    ordered = sorted(entries.items())
    prev_src = 0
    for number, (_text, src_line) in ordered:
        if src_line < prev_src:
            warnings.append(BasicError(f"Line {number} is out of order; it will be sorted into place", src_line))
        prev_src = max(prev_src, src_line)
    return [(num, t, s) for num, (t, s) in ordered], warnings


class BasicErrors(Exception):
    """Several BasicErrors at once."""

    def __init__(self, errors: list[BasicError]):
        super().__init__(f"{len(errors)} error(s)")
        self.errors = errors


def tokenize(text: str, start: int = 0x0801) -> TokenizeResult:
    """Tokenize a whole BASIC program. Raises BasicErrors with every error found."""
    return tokenize_files([(None, text)], start)


def tokenize_files(sources: list[tuple[str | None, str]], start: int = 0x0801) -> TokenizeResult:
    """Tokenize one program from several files (lines are merged by number)."""
    lines: list[BasicLine] = []
    warnings: list[BasicError] = []
    errors: list[BasicError] = []
    owner: dict[int, tuple[str | None, int]] = {}
    for fname, text in sources:
        try:
            got, warn = _tokenize_lines(text, _token_table(text, fname))
        except BasicError as e:
            e.file = e.file or fname
            errors.append(e)
            continue
        except BasicErrors as e:
            for err in e.errors:
                err.file = err.file or fname
            errors.extend(e.errors)
            continue
        for w in warn:
            w.file = fname
        warnings.extend(warn)
        for ln in got:
            ln.file = fname
            if ln.number in owner:
                other = owner[ln.number]
                errors.append(BasicError(f"Line {ln.number} is also in {other[0]} (source line {other[1]})",
                                         ln.source_line, fname))
                continue
            owner[ln.number] = (fname, ln.source_line)
            lines.append(ln)
    if errors:
        raise BasicErrors(errors)
    lines.sort(key=lambda ln: ln.number)
    return link_lines(lines, start, warnings)


def _token_table(text: str, fname: str | None):
    """The keyword table of a `tokenfile` line in the source (tokenfile.py), or None for BASIC V2's."""
    from . import tokenfile
    for n, line in enumerate(text.splitlines(), start=1):
        name = tokenfile.tokenfile_line(line)
        if name is None:
            continue
        folder = Path(fname).parent if fname else Path.cwd()
        path = tokenfile.find(name, folder)
        if not path.exists():
            raise BasicError(f"The token file {path.name} isn't there (looked in {path.parent})", n, fname)
        try:
            return tokenfile.table(tokenfile.load(path))
        except BasicError as e:
            raise BasicError(e.message, n, fname) from None
    return None


def _tokenize_lines(text: str, table=None) -> tuple[list[BasicLine], list[BasicError]]:
    entries, warnings = parse_source(text)
    errors: list[BasicError] = []
    lines: list[BasicLine] = []
    for number, body, src_line in entries:
        try:
            data = crunch(body, src_line, table)
        except BasicError as e:
            errors.append(e)
            continue
        if len(data) > MAX_LINE_BYTES:
            errors.append(BasicError(f"Line {number} is too long ({len(data)} bytes after tokenizing, "
                                     f"max {MAX_LINE_BYTES})", src_line))
            continue
        if len(body) > 80:
            warnings.append(BasicError(f"Line {number} is longer than 80 characters, so it can't be "
                                       f"edited on the C64 itself", src_line))
        lines.append(BasicLine(number, data, src_line))
    if errors:
        raise BasicErrors(errors)
    return lines, warnings


def link_lines(lines: list[BasicLine], start: int = 0x0801, warnings: list[BasicError] | None = None) -> TokenizeResult:
    """Lay out tokenized lines in memory with their link pointers."""
    program = bytearray()
    addr = start
    for ln in lines:
        nxt = addr + 2 + 2 + len(ln.data) + 1
        program += bytes([nxt & 0xFF, nxt >> 8, ln.number & 0xFF, ln.number >> 8]) + ln.data + b"\0"
        addr = nxt
    program += b"\0\0"
    if start + len(program) > 0xA000:
        raise BasicErrors([BasicError("Program is too big for BASIC memory (it would pass $9FFF)")])
    return TokenizeResult(lines, start, bytes(program), warnings or [])


# ---------------------------------------------------------------------- detokenizing

def detokenize(prg: bytes, has_load_address: bool = True, style: str = "standard", tokens=None) -> str:
    """Turn a tokenized BASIC program back into source text, writing control codes in strings and
    REMs in `style` (codestyles.STYLES). `tokens`: a BASIC extension's (tokenfile.load), whose
    keywords are listed too."""
    if has_load_address:
        if len(prg) < 2:
            raise BasicError("File is too short to be a program")
        start = prg[0] | (prg[1] << 8)
        mem = prg[2:]
    else:
        start, mem = 0x0801, prg
    out_lines = []
    off = 0
    guard = 0
    while off + 4 <= len(mem):
        link = mem[off] | (mem[off + 1] << 8)
        if link == 0:
            break
        number = mem[off + 2] | (mem[off + 3] << 8)
        end = mem.find(b"\0", off + 4)
        if end == -1:
            raise BasicError(f"Line {number} has no end marker; this doesn't look like a BASIC program")
        out_lines.append(f"{number} {list_line(mem[off + 4:end], style, tokens)}")
        nxt = link - start
        off = nxt if start <= link and nxt > off else end + 1
        guard += 1
        if guard > 10000:
            raise BasicError("Program lines loop back on themselves")
    return "\n".join(out_lines) + ("\n" if out_lines else "")


def _extension_tokens(tokens) -> tuple[dict[int, str], dict[tuple[int, int], str]]:
    """A token file's keywords by token: (one-byte, two-byte)."""
    one: dict[int, str] = {}
    two: dict[tuple[int, int], str] = {}
    for t in tokens or []:
        if len(t.value) == 1:
            one.setdefault(t.value[0], t.keyword.lower())
        else:
            two.setdefault((t.value[0], t.value[1]), t.keyword.lower())
    return one, two


def list_line(data: bytes, style: str = "standard", tokens=None) -> str:
    """LIST one crunched line (with a BASIC extension's `tokens` too, if given)."""
    from .codestyles import code_text
    parts = []
    in_quote = False
    in_rem = False
    ext1, ext2 = _extension_tokens(tokens)
    i = 0
    while i < len(data):
        b = data[i]
        i += 1
        if not in_quote and not in_rem and (ext1 or ext2):
            if i < len(data) and (b, data[i]) in ext2:          # a two-byte token: Simons' Basic's $64 xx
                parts.append(ext2[(b, data[i])])
                i += 1
                continue
            if b in ext1:
                parts.append(ext1[b])
                if ext1[b] == "rem":
                    in_rem = True
                continue
        if b == 0x22:
            in_quote = not in_quote
            parts.append('"')
            continue
        if not in_quote and not in_rem and 0x80 <= b <= 0xCB:
            kw = KEYWORDS[b - 0x80]
            parts.append(kw)
            if b == REM:
                in_rem = True
            continue
        if not in_quote and not in_rem and b == PI:
            parts.append("π")
            continue
        parts.append(code_text(b, style) if style != "standard" and (in_quote or in_rem)
                     else petscii_to_text(b, in_quote or in_rem))
    # Collapse runs of the same control code: {down}{down}{down} -> {3 down}
    out = []
    for p in parts:
        if out and p.startswith("{") and p.endswith("}") and out[-1][0] == p:
            out[-1][1] += 1
        else:
            out.append([p, 1])
    if style != "standard":                 # {down*3}, as CBM prg Studio writes runs
        return "".join(p if n == 1 else "{" + p[1:-1] + f"*{n}}}" for p, n in out)
    return "".join(p if n == 1 else f"{{{n} {p[1:-1]}}}" for p, n in out)
