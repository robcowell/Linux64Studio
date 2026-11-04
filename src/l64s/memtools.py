"""Finding bytes in memory, and exporting a block of memory as formatted text, as CBM prg Studio's
Memory window does.

Find: values in hex ($A9, 0xA9) or decimal (169), or binary (%10101001), separated by spaces or
commas, and strings in quotes, all mixed if you like: `$A9 1 "hi"`. A string is PETSCII (as
CHROUT prints it) or screen codes (as in screen memory).

Export: each value written in a base with a prefix ("$", "0x"…), separated by a separator, so
many to a row, with text before and after each row, and a header and footer that can use
%start%, %end%, %size% and %date% (CBM prg Studio's keywords; case-sensitive).
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

from .asm.charset import char_to_petscii, char_to_screencode


class MemToolError(ValueError):
    pass


_TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|[^\s,]+')


def parse_find(text: str, strings: str = "petscii") -> bytes:
    """The bytes to look for."""
    if not text.strip():
        raise MemToolError("Enter a string or byte sequence to find")
    conv = char_to_petscii if strings == "petscii" else char_to_screencode
    out = bytearray()
    for tok in _TOKEN.findall(text):
        if tok[0] in "\"'":
            if len(tok) < 2 or tok[-1] != tok[0]:
                raise MemToolError(f"A string needs a closing quote: {tok}")
            if len(tok) == 2:
                raise MemToolError("An empty string can't be found")
            out += bytes(conv(c) for c in tok[1:-1])
            continue
        try:
            if tok.startswith("$"):
                v = int(tok[1:], 16)
            elif tok.lower().startswith("0x"):
                v = int(tok[2:], 16)
            elif tok.startswith("%"):
                v = int(tok[1:], 2)
            else:
                v = int(tok, 10)
        except ValueError:
            raise MemToolError(f"Invalid search value ({tok}): use $hex, decimal or a \"string\"") from None
        if not 0 <= v <= 255:
            raise MemToolError(f"Invalid search value ({tok}): bytes are 0-255")
        out.append(v)
    return bytes(out)


def find(memory: bytes, pattern: bytes, start: int = 0, wrap: bool = True) -> int | None:
    """The first address at or after `start` where the pattern is; with `wrap`, carry on from $0000."""
    if not pattern:
        return None
    i = bytes(memory).find(pattern, start)
    if i < 0 and wrap and start > 0:
        i = bytes(memory).find(pattern, 0, start + len(pattern) - 1)
    return None if i < 0 else i


def count(memory: bytes, pattern: bytes) -> int:
    n, i, mem = 0, 0, bytes(memory)
    while pattern:
        i = mem.find(pattern, i)
        if i < 0:
            break
        n += 1
        i += 1
    return n


# ---------------------------------------------------------------------- export

BASES = {16: "Hexadecimal (16)", 10: "Decimal (10)", 8: "Octal (8)", 2: "Binary (2)"}
_DIGITS = {16: 2, 8: 3, 2: 8}


@dataclass
class ExportOptions:
    start: int = 0x0400
    end: int = 0x04FF                  # included
    prefix: str = "$"                  # CBM prg Studio's "format specifier"
    separator: str = ", "
    base: int = 16
    per_row: int = 16
    header: str = ""
    footer: str = ""
    row_lead: str = ""
    row_trail: str = ""
    pad: bool = True                   # hex as 2 digits, binary as 8, octal as 3


def _value(v: int, opts: ExportOptions) -> str:
    if opts.base == 16:
        s = f"{v:X}"
    elif opts.base == 8:
        s = f"{v:o}"
    elif opts.base == 2:
        s = f"{v:b}"
    elif opts.base == 10:
        return opts.prefix + str(v)
    else:
        raise MemToolError(f"Unknown number base {opts.base}")
    if opts.pad:
        s = s.rjust(_DIGITS[opts.base], "0")
    return opts.prefix + s


def keywords(text: str, start: int, end: int, now: _dt.datetime | None = None) -> str:
    """%start%, %end%, %size% and %date% in a header or footer."""
    when = (now or _dt.datetime.now()).strftime("%d/%m/%Y %H:%M:%S")
    return (text.replace("%start%", f"${start:04X}").replace("%end%", f"${end:04X}")
            .replace("%size%", str(end - start + 1)).replace("%date%", when))


def export(memory: bytes, opts: ExportOptions, now: _dt.datetime | None = None) -> str:
    if not 0 <= opts.start <= 0xFFFF or not 0 <= opts.end <= 0xFFFF:
        raise MemToolError("The block must be within $0000-$FFFF")
    if opts.end < opts.start:
        raise MemToolError("The block's start address must be before its end address")
    if opts.per_row < 1:
        raise MemToolError("There must be at least one value a row")
    out = []
    if opts.header:
        out.append(keywords(opts.header, opts.start, opts.end, now))
    data = bytes(memory[opts.start:opts.end + 1])
    for i in range(0, len(data), opts.per_row):
        row = opts.separator.join(_value(v, opts) for v in data[i:i + opts.per_row])
        out.append(opts.row_lead + row + opts.row_trail)
    if opts.footer:
        out.append(keywords(opts.footer, opts.start, opts.end, now))
    return "\n".join(out) + "\n"
