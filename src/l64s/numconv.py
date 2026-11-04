"""Base conversion for numbers in assembler source, as CBM prg Studio's editor does: hovering
over a number shows it in other bases, and a selected number can be rewritten in another base.

Numbers are written as in CBM prg Studio (and Kick Assembler): $hex, %binary or decimal. A
number inside quotes, or part of a name (label2, /1), isn't a number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

BASES = ("hex", "dec", "bin")
_NUMBER = re.compile(r"(?<![\w$%.@/])(\$[0-9A-Fa-f]+|%[01]+|\d+)(?![\w])")


@dataclass
class Number:
    start: int          # column of the first character
    end: int            # column after the last
    text: str
    value: int
    base: str           # "hex", "dec" or "bin"

    @property
    def digits(self) -> int:
        return len(self.text) - (0 if self.base == "dec" else 1)


def parse(text: str) -> Number | None:
    """A literal on its own (surrounding spaces allowed)."""
    t = text.strip()
    if _NUMBER.fullmatch(t):
        return _number(t, 0)
    return None


def _number(t: str, start: int) -> Number:
    if t[0] == "$":
        return Number(start, start + len(t), t, int(t[1:], 16), "hex")
    if t[0] == "%":
        return Number(start, start + len(t), t, int(t[1:], 2), "bin")
    return Number(start, start + len(t), t, int(t), "dec")


def _code_spans(line: str) -> list[tuple[int, int]]:
    """The parts of a line outside quotes (strings in ' or ")."""
    spans, start, quote = [], 0, None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote, start = None, i + 1
        elif ch in "\"'":
            spans.append((start, i))
            quote = ch
    if quote is None:
        spans.append((start, len(line)))
    return spans


def numbers(line: str) -> list[Number]:
    out = []
    for a, b in _code_spans(line):
        for m in _NUMBER.finditer(line, a, b):
            out.append(_number(m.group(1), m.start(1)))
    return out


def number_at(line: str, col: int) -> Number | None:
    """The number under a column (or just after it, as when the pointer is on its last character)."""
    for n in numbers(line):
        if n.start <= col <= n.end:
            return n
    return None


def to_base(value: int, base: str, width_from: Number | None = None) -> str:
    """value written in a base. Hex has 2 or 4 digits (or as many as the original had); binary 8
    or 16 (or the original's width)."""
    if value < 0:
        raise ValueError("Negative numbers can't be converted")
    if base == "dec":
        return str(value)
    if base == "hex":
        digits = 2 if value <= 0xFF else 4 if value <= 0xFFFF else len(f"{value:X}")
        if width_from and width_from.base == "hex":
            digits = max(digits, width_from.digits)
        return f"${value:0{digits}X}"
    if base == "bin":
        digits = 8 if value <= 0xFF else 16 if value <= 0xFFFF else len(f"{value:b}")
        if width_from and width_from.base == "bin":
            digits = max(digits, width_from.digits)
        return f"%{value:0{digits}b}"
    raise ValueError(f"Unknown base {base!r}")


def describe(n: Number) -> str:
    """The hover text: the number in each base, and what it is as a byte or word."""
    v = n.value
    lines = [f"{to_base(v, 'hex', n)}   {v}   {to_base(v, 'bin', n)}"]
    if v <= 0xFF:
        if v >= 0x80:
            lines.append(f"signed byte: {v - 256}")
    elif v <= 0xFFFF:
        lines.append(f"high byte ${v >> 8:02X} ({v >> 8}), low byte ${v & 0xFF:02X} ({v & 0xFF})")
        if v >= 0x8000:
            lines.append(f"signed word: {v - 65536}")
    return "\n".join(lines)
