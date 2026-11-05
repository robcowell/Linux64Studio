"""String Formatter: split a long string into lines of a set length, as BASIC string assignments
or assembler text directives (as CBM prg Studio's tool does), and change its case.

The text uses listing notation: control codes are written {white}, {clear}, {3 down}. Each one is
a single character on the C64 and is never split. Lower case letters are the C64's normal (upper
case) letters and capitals are the shifted ones, as in the BASIC editor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .basic.petscii import ControlCodeError, parse_control

_TOKEN = re.compile(r"\{[^}]*\}|.", re.S)


class FormatError(ValueError):
    pass


def tokens(text: str) -> list[str]:
    """The C64 characters of the text: single characters, and {codes} as one each."""
    out = _TOKEN.findall(text.replace("\r", "").replace("\n", " "))
    for t in out:
        if t == "{":
            raise FormatError("'{' without a closing '}'")
    return out


def length(text: str) -> int:
    """How many characters the text is on the C64 ({3 down} is 3)."""
    n = 0
    for t in tokens(text):
        n += len(_control(t)) if len(t) > 1 else 1
    return n


def _control(tok: str) -> bytes:
    try:
        return bytes(parse_control(tok[1:-1]))
    except ControlCodeError as e:
        raise FormatError(str(e)) from None


def split(text: str, width: int, words: bool = True) -> list[str]:
    """Pieces of at most `width` C64 characters that join back into the text. With `words`, a
    piece ends after a space where it can, so words aren't broken."""
    if not 1 <= width <= 200:
        raise FormatError("Characters per line must be 1 - 200")
    toks = tokens(text)
    sizes = [len(_control(t)) if len(t) > 1 else 1 for t in toks]
    pieces, i = [], 0
    while i < len(toks):
        n, j = 0, i
        while j < len(toks) and n + sizes[j] <= width:
            n += sizes[j]
            j += 1
        if j == i:                       # a single {code} wider than the line: it can't be split
            j = i + 1
        if words and j < len(toks):
            k = j
            while k > i and toks[k - 1] != " ":
                k -= 1
            if k > i:
                j = k
        pieces.append("".join(toks[i:j]))
        i = j
    return pieces


# ---------------------------------------------------------------------- case

def _map_letters(text: str, fn) -> str:
    return "".join(t if len(t) > 1 else fn(t) for t in tokens(text))


def upper(text: str) -> str:
    return _map_letters(text, str.upper)


def lower(text: str) -> str:
    return _map_letters(text, str.lower)


def mixed(text: str) -> str:
    """Sentence case: a capital at the start and after . ! ?, the rest lower case."""
    out, start = [], True
    for t in tokens(text):
        if len(t) > 1:
            out.append(t)
            continue
        if t.isalpha():
            out.append(t.upper() if start else t.lower())
            start = False
        else:
            out.append(t)
            if t in ".!?":
                start = True
    return "".join(out)


@dataclass
class Match:
    position: int
    text: str


def find(text: str, pattern: str) -> list[Match]:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise FormatError(f"Invalid regular expression: {e}") from None
    return [Match(m.start(), m.group(0)) for m in rx.finditer(text) if m.group(0)]


def replace(text: str, pattern: str, repl: str) -> tuple[str, int]:
    try:
        return re.subn(pattern, repl, text)
    except re.error as e:
        raise FormatError(f"Invalid regular expression: {e}") from None


# ---------------------------------------------------------------------- output

@dataclass
class Options:
    width: int = 30
    words: bool = True
    # BASIC
    start_line: int = 10
    step: int = 10
    variable: str = "a$"
    initialise: bool = True        # the first line sets the variable; the rest add to it
    # assembler
    petscii: bool = True           # text "..." (PETSCII) or text '...' (screen codes)
    label: str = ""
    kickass: bool = False
    syntax: str = ""               # "ca65" or "c" (syntax.py); otherwise kickass chooses Kick or CBM


def basic(text: str, opts: Options) -> tuple[str, list[str]]:
    """BASIC lines building the string in a variable; also any warnings."""
    var = opts.variable.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9]?\$", var):
        raise FormatError("The variable must be a string variable such as a$ or t1$")
    if '"' in text:
        raise FormatError('A BASIC string can\'t contain a " (use chr$(34) to add one)')
    warnings = []
    pieces = split(text, opts.width, opts.words)
    out, n = [], opts.start_line
    for i, p in enumerate(pieces):
        if n > 63999:
            raise FormatError("The line numbers run past 63999: start lower or use a smaller step")
        line = f'{n} {var}="{p}"' if i == 0 and opts.initialise else f'{n} {var}={var}+"{p}"'
        out.append(line)
        if len(line) > 80:
            warnings.append(f"Line {n} is {len(line)} characters: too long to type on a C64 (80), "
                            f"though it builds. Use fewer characters per line")
        n += opts.step
    total = length(text)
    if total > 255:
        warnings.append(f"The string is {total} characters, but a BASIC string can hold 255 at most")
    return "\n".join(out) + "\n", warnings


def _asm_items(piece: str, quote: str, petscii: bool) -> list[str]:
    """A line's items: quoted runs, with control codes as numbers between them."""
    items, run = [], ""
    for t in tokens(piece):
        if len(t) == 1 and t != quote:
            run += t
            continue
        if run:
            items.append(f"{quote}{run}{quote}")
            run = ""
        if len(t) == 1:                       # the quote character itself
            items.append(str(ord(t)) if petscii else "$27")
        else:
            if not petscii:
                raise FormatError(f"{t} is a PETSCII control code: it has no screen code (choose PETSCII)")
            items.extend(f"${b:02X}" for b in _control(t))
    if run:
        items.append(f"{quote}{run}{quote}")
    return items


def _bytes_ca65_c(pieces: list[str], opts: Options, sx: str) -> str:
    """For ca65 and C: the text as its bytes (PETSCII, or screen codes), a row a line of text, the
    line's text beside it. (C's own strings don't take the {control} codes.)"""
    from .basic.screencodes import BuildError, petscii_to_screencode, text_to_petscii
    data, rows, notes = bytearray(), [], []
    for p in pieces:
        try:
            pet = text_to_petscii(p)
        except BuildError as e:
            raise FormatError(str(e)) from None
        row = pet if opts.petscii else bytes(petscii_to_screencode(b) or 0x20 for b in pet)
        data += row
        rows.append(len(row))
        notes.append(p.replace("*/", "* /"))
    return _rows_by_line(sx, opts, bytes(data), rows, notes)


def _rows_by_line(sx: str, opts: Options, data: bytes, rows: list[int], notes: list[str]) -> str:
    from .syntax import comment, directive, indent, label_line, number
    out = [comment(sx, "PETSCII, for CHROUT" if opts.petscii else "screen codes, for screen memory")]
    at = 0
    if sx == "c":
        out.append(f"const unsigned char {opts.label or 'text'}[{len(data)}] = {{")
        for n, size in enumerate(rows):
            row = data[at:at + size]
            at += size
            end = "," if n < len(rows) - 1 else ""
            out.append("    " + ", ".join(number(b, 1, "hex", sx) for b in row) + end + f"    /* {notes[n]} */")
        out.append("};")
    else:
        lab = label_line(sx, opts.label)
        if lab:
            out.append(lab)
        for n, size in enumerate(rows):
            row = data[at:at + size]
            at += size
            out.append(f"{indent(sx)}{directive(sx)} " + ", ".join(number(b, 1, "hex", sx) for b in row)
                       + " " + comment(sx, notes[n]))
    return "\n".join(out) + "\n"


def assembler(text: str, opts: Options) -> str:
    pieces = split(text, opts.width, opts.words)
    from .syntax import CA65, C, resolve
    sx = resolve(opts.syntax or None, opts.kickass)
    if sx in (CA65, C):
        return _bytes_ca65_c(pieces, opts, sx)
    c = "//" if opts.kickass else ";"
    ind = "    " if opts.kickass else "        "
    out = []
    if opts.label:
        out.append(f"{opts.label}:" if opts.kickass else opts.label)
    if opts.kickass:
        # Kick Assembler's .text uses the current .encoding; its default is screen codes
        out.append(f'{ind}.encoding "{"petscii_mixed" if opts.petscii else "screencode_mixed"}"')
        quote = '"'
    else:
        quote = '"' if opts.petscii else "'"
    directive = ".text" if opts.kickass else "text"
    for p in pieces:
        items = _asm_items(p, quote, opts.petscii)
        if opts.kickass:
            # Kick Assembler takes numbers in .text only through .byte
            text_items = [x for x in items if x.startswith(quote)]
            if len(text_items) != len(items):
                for x in items:
                    out.append(f"{ind}{directive} {x}" if x.startswith(quote) else f"{ind}.byte {x}")
                continue
        out.append(f"{ind}{directive} " + ", ".join(items))
    if opts.kickass and opts.petscii:
        out.append(f'{ind}.encoding "screencode_mixed"    {c} back to the default')
    return "\n".join(out) + "\n"
