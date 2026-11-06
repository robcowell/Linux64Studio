"""Reading the values typed into the debugger: addresses, register values and byte lists."""
from __future__ import annotations

import re

from ..asm.charset import char_to_petscii, char_to_screencode

FLAG_NAMES = "NV-BDIZC"   # bit 7 to bit 0 of the status register
REGISTER_BITS = {"PC": 16, "A": 8, "X": 8, "Y": 8, "SP": 8, "FL": 8}


class ValueError_(ValueError):
    pass


def parse_number(text: str, symbols: dict[str, int] | None = None) -> int:
    """A number or label: $FF or FF (hex), %1010 (binary), #12 or 12. (decimal), or a label name.

    Bare digits are hex, as in VICE's monitor, since that's what the debugger shows, unless
    they're a label's name (add16, beef): a label wins, and $ always means hex. A label may be
    followed by +n/-n.
    """
    t = text.strip()
    if not t:
        raise ValueError_("Nothing entered")
    m = re.fullmatch(r"(.+?)\s*([+-])\s*(\$?[0-9A-Fa-f]+|#\d+)", t)
    if m and not re.fullmatch(r"\$?[0-9A-Fa-f]+", t):
        base = parse_number(m.group(1), symbols)
        off = parse_number(m.group(3), symbols)
        return base + off if m.group(2) == "+" else base - off
    if t.startswith("$"):
        return _int(t[1:], 16, text)
    if t.startswith("%"):
        return _int(t[1:], 2, text)
    if t.startswith("#"):
        return _int(t[1:], 10, text)
    if t.endswith(".") and t[:-1].isdigit():
        return int(t[:-1])
    if t.lower().startswith("0x"):
        return _int(t[2:], 16, text)
    if symbols and re.fullmatch(r"[0-9A-Fa-f]+", t) and not t.isdigit():
        found = _symbol(t, symbols)               # a label spelt in hex digits (add16, beef)
        if found is not None:
            return found
    if re.fullmatch(r"[0-9A-Fa-f]+", t):
        return int(t, 16)
    if symbols:
        for name in (t, t.lower()):
            if name in symbols:
                return symbols[name]
        low = {k.lower(): v for k, v in symbols.items()}
        if t.lower() in low:
            return low[t.lower()]
    raise ValueError_(f"'{text}' isn't a number or a known label")


def _symbol(name: str, symbols: dict[str, int]) -> int | None:
    if name in symbols:
        return symbols[name]
    low = name.lower()
    return next((v for k, v in symbols.items() if k.lower() == low), None)


def _int(digits: str, base: int, original: str) -> int:
    try:
        return int(digits, base)
    except ValueError:
        raise ValueError_(f"'{original}' isn't a valid number")


def parse_register(name: str, text: str, symbols: dict[str, int] | None = None) -> int:
    """A value for register `name`, range-checked."""
    v = parse_number(text, symbols)
    bits = REGISTER_BITS.get(name, 8)
    if not 0 <= v < (1 << bits):
        raise ValueError_(f"{name} takes {'$0000-$FFFF' if bits == 16 else '$00-$FF'}, not {text.strip()}")
    return v


def parse_address(text: str, symbols: dict[str, int] | None = None) -> int:
    v = parse_number(text, symbols)
    if not 0 <= v <= 0xFFFF:
        raise ValueError_(f"Address {text.strip()} is outside $0000-$FFFF")
    return v


def parse_bytes(text: str, symbols: dict[str, int] | None = None) -> bytes:
    """Bytes to write: hex bytes (`a9 00 8d`), `$xx`/`%bits`/`#dec`, labels' low bytes with `<label`
    or high bytes with `>label`, and text: "hi" as screen codes (for screen memory), 'hi' as PETSCII."""
    out = bytearray()
    for tok in re.findall(r'"[^"]*"|\'[^\']*\'|[^\s,]+', text):
        if tok[0] in "\"'":
            conv = char_to_screencode if tok[0] == '"' else char_to_petscii
            out += bytes(conv(c) for c in tok[1:-1])
            continue
        if tok[0] in "<>":
            v = parse_number(tok[1:], symbols)
            out.append(v & 0xFF if tok[0] == "<" else (v >> 8) & 0xFF)
            continue
        v = parse_number(tok, symbols)
        if not 0 <= v <= 0xFF:
            raise ValueError_(f"{tok} doesn't fit in a byte (use <{tok} or >{tok} for an address)")
        out.append(v)
    if not out:
        raise ValueError_("Nothing to write")
    return bytes(out)


def flags_text(fl: int) -> str:
    return "".join(c if fl & (0x80 >> i) else "." for i, c in enumerate(FLAG_NAMES))


def is_io(address: int, length: int = 1) -> bool:
    """Whether a write touches the I/O area, where it must reach the chips (VIC, SID, CIAs)."""
    return address <= 0xDFFF and address + length - 1 >= 0xD000
