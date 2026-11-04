"""PETSCII control codes and character mapping for BASIC source text.

Control codes are written in braces inside strings: {clear}, {white}, {down}. Several naming
styles are accepted (long names, CBM prg Studio-style, VICE petcat's abbreviations), plus
{$93} / {147} for any byte and repeat counts as {5 down} or {down*5}.
"""
from __future__ import annotations

import re

# Canonical name (used when listing a program) -> PETSCII code, then aliases.
CONTROL_CODES: list[tuple[str, int, tuple[str, ...]]] = [
    ("stop", 0x03, ()),
    ("white", 0x05, ("wht", "wh")),
    ("disable shift", 0x08, ("dish", "lock")),
    ("enable shift", 0x09, ("ensh", "unlock")),
    ("return", 0x0D, ("cr", "ret")),
    ("lower case", 0x0E, ("swlc", "lower", "text")),
    ("down", 0x11, ("crsr down", "cursor down", "dn")),
    ("reverse on", 0x12, ("rvon", "rvs on", "rvs", "reverse")),
    ("home", 0x13, ("hom",)),
    ("delete", 0x14, ("del", "dele")),
    ("red", 0x1C, ()),
    ("right", 0x1D, ("rght", "crsr right", "cursor right", "rt")),
    ("green", 0x1E, ("grn",)),
    ("blue", 0x1F, ("blu",)),
    ("orange", 0x81, ("orng",)),
    ("f1", 0x85, ()), ("f3", 0x86, ()), ("f5", 0x87, ()), ("f7", 0x88, ()),
    ("f2", 0x89, ()), ("f4", 0x8A, ()), ("f6", 0x8B, ()), ("f8", 0x8C, ()),
    ("shift return", 0x8D, ("sret", "shift cr")),
    ("upper case", 0x8E, ("swuc", "upper", "graphics")),
    ("black", 0x90, ("blk",)),
    ("up", 0x91, ("crsr up", "cursor up")),
    ("reverse off", 0x92, ("rvof", "rvs off")),
    ("clear", 0x93, ("clr", "cls", "clear screen")),
    ("insert", 0x94, ("inst", "ins")),
    ("brown", 0x95, ("brn",)),
    ("light red", 0x96, ("lred", "pink", "lt red")),
    ("dark grey", 0x97, ("gry1", "grey 1", "gray 1", "dark gray", "dgry")),
    ("grey", 0x98, ("gry2", "grey 2", "gray 2", "gray", "mgry", "medium grey")),
    ("light green", 0x99, ("lgrn", "lt green")),
    ("light blue", 0x9A, ("lblu", "lt blue")),
    ("light grey", 0x9B, ("gry3", "grey 3", "gray 3", "light gray", "lgry")),
    ("purple", 0x9C, ("pur", "magenta")),
    ("left", 0x9D, ("crsr left", "cursor left", "lf")),
    ("yellow", 0x9E, ("yel",)),
    ("cyan", 0x9F, ("cyn",)),
    ("shift space", 0xA0, ("sspc",)),
    ("pi", 0xFF, ("π",)),
]

NAME_TO_CODE: dict[str, int] = {}
CODE_TO_NAME: dict[int, str] = {}
for _name, _code, _aliases in CONTROL_CODES:
    CODE_TO_NAME[_code] = _name
    for n in (_name, *_aliases):
        NAME_TO_CODE[n] = _code


class ControlCodeError(ValueError):
    pass


_REPEAT_FRONT = re.compile(r"^(\d+)\s+(.+)$")
_REPEAT_BACK = re.compile(r"^(.+?)\s*\*\s*(\d+)$")


def parse_control(body: str) -> list[int]:
    """The bytes for the text between { and }."""
    text = " ".join(body.strip().lower().split())
    count = 1
    m = _REPEAT_BACK.match(text) or None
    if m:
        text, count = m.group(1), int(m.group(2))
    else:
        m = _REPEAT_FRONT.match(text)
        if m and not text.isdigit():
            count, text = int(m.group(1)), m.group(2)
    if text.startswith("$"):
        try:
            code = int(text[1:], 16)
        except ValueError:
            raise ControlCodeError(f"Bad control code {{{body}}}")
    elif text.isdigit():
        code = int(text)
    elif text in NAME_TO_CODE:
        code = NAME_TO_CODE[text]
    else:
        raise ControlCodeError(f"Unknown control code {{{body}}}")
    if not 0 <= code <= 255:
        raise ControlCodeError(f"Control code {{{body}}} is out of range")
    if not 1 <= count <= 255:
        raise ControlCodeError(f"Repeat count in {{{body}}} is out of range")
    return [code] * count


def char_to_petscii(ch: str, in_string: bool) -> int:
    """Map one source character.

    Outside strings, letters of either case are BASIC's normal (unshifted) letters, so
    `print` and `PRINT` are the same. Inside strings and REM, upper-case letters are the
    shifted ones (graphics in the default character set), as in VICE's petcat.
    """
    o = ord(ch)
    if "a" <= ch <= "z":
        return o - 32
    if "A" <= ch <= "Z":
        return o + 0x80 if in_string else o
    if ch == "£":
        return 0x5C
    if ch in "↑^":
        return 0x5E
    if ch in "←_":
        return 0x5F
    if ch == "π":
        return 0xFF
    if 0x20 <= o <= 0x40 or ch in "[]":
        return o
    raise ControlCodeError(f"Character {ch!r} has no PETSCII equivalent; use a {{$xx}} code")


def petscii_to_text(code: int, in_string: bool) -> str:
    """Inverse of char_to_petscii for listings ({name}/{$xx} for anything else)."""
    if 0x41 <= code <= 0x5A:
        return chr(code + 32)
    if 0xC1 <= code <= 0xDA and in_string:
        return chr(code - 0x80)
    if code == 0x5C:
        return "£"
    if code == 0x5E:
        return "^"
    if code == 0x5F:
        return "_"
    if 0x20 <= code <= 0x40 or code in (0x5B, 0x5D):
        return chr(code)
    name = CODE_TO_NAME.get(code)
    return f"{{{name}}}" if name else f"{{${code:02x}}}"
