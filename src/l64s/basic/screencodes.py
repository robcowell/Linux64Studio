"""The screen code builder's engine: text with {control codes} -> PETSCII, a simulation of what
PRINTing it does on a C64 screen, and the outputs (BASIC string, PETSCII bytes, screen codes).

The text uses the BASIC listing notation: letters as typed (upper case = shifted graphics in
the default character set), {white}, {down}, {reverse on}, {cbm-a}, {shift-+}, {$93} and so on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .petscii import CODE_TO_NAME, ControlCodeError, char_to_petscii, parse_control

COLS, ROWS = 40, 25

# PETSCII colour codes -> C64 colour numbers
COLOUR_CODES = {0x90: 0, 0x05: 1, 0x1C: 2, 0x9F: 3, 0x9C: 4, 0x1E: 5, 0x1F: 6, 0x9E: 7,
                0x81: 8, 0x95: 9, 0x96: 10, 0x97: 11, 0x98: 12, 0x99: 13, 0x9A: 14, 0x9B: 15}
COLOUR_TO_CODE = {v: k for k, v in COLOUR_CODES.items()}


class BuildError(ValueError):
    pass


def text_to_petscii(text: str) -> bytes:
    """The builder's text as PETSCII, the way the characters would sit in a BASIC string."""
    out = bytearray()
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            close = text.find("}", i)
            if close == -1:
                raise BuildError("'{' without a closing '}'")
            try:
                out += bytes(parse_control(text[i + 1:close]))
            except ControlCodeError as e:
                raise BuildError(str(e))
            i = close + 1
            continue
        if ch == "\n":
            out.append(0x0D)
        elif ch != "\r":
            try:
                out.append(char_to_petscii(ch, in_string=True))
            except ControlCodeError as e:
                raise BuildError(str(e))
        i += 1
    return bytes(out)


def petscii_to_screencode(p: int) -> int | None:
    """The screen code a printable PETSCII character shows as (None for control codes)."""
    if 0x20 <= p <= 0x3F:
        return p
    if 0x40 <= p <= 0x5F:
        return p - 0x40
    if 0x60 <= p <= 0x7F:
        return p - 0x20
    if 0xA0 <= p <= 0xBF:
        return p - 0x40
    if 0xC0 <= p <= 0xFE:
        return p - 0x80
    if p == 0xFF:
        return 0x5E
    return None


@dataclass
class Screen:
    """The result of PRINTing: characters, colours, where the cursor ended and the case set."""
    chars: list[list[int]] = field(default_factory=lambda: [[0x20] * COLS for _ in range(ROWS)])
    colours: list[list[int]] = field(default_factory=lambda: [[14] * COLS for _ in range(ROWS)])
    row: int = 0
    col: int = 0
    colour: int = 14
    reverse: bool = False
    lowercase: bool = False
    used: set[tuple[int, int]] = field(default_factory=set)


def simulate_print(petscii: bytes, colour: int = 14, lowercase: bool = False, screen: Screen | None = None) -> Screen:
    """What PRINTing these characters (with a trailing ;) does, as the KERNAL's screen editor
    handles them: colours, cursor movement, reverse, CLR/HOME, RETURN, DEL/INST and case."""
    s = screen or Screen(colour=colour, lowercase=lowercase)

    def scroll():
        s.chars.pop(0)
        s.colours.pop(0)
        s.chars.append([0x20] * COLS)
        s.colours.append([s.colour] * COLS)
        s.used = {(r - 1, c) for r, c in s.used if r > 0}
        s.row = ROWS - 1

    for p in petscii:
        if p in COLOUR_CODES:
            s.colour = COLOUR_CODES[p]
        elif p == 0x93:                     # clear
            s.chars = [[0x20] * COLS for _ in range(ROWS)]
            s.colours = [[s.colour] * COLS for _ in range(ROWS)]
            s.row = s.col = 0
            s.used.clear()
        elif p == 0x13:                     # home
            s.row = s.col = 0
        elif p == 0x12:
            s.reverse = True
        elif p == 0x92:
            s.reverse = False
        elif p in (0x0D, 0x8D):             # return / shift-return: next line, reverse off
            s.col = 0
            s.row += 1
            s.reverse = False
            if s.row >= ROWS:
                scroll()
        elif p == 0x11:                     # down
            s.row += 1
            if s.row >= ROWS:
                scroll()
        elif p == 0x91:                     # up
            s.row = max(0, s.row - 1)
        elif p == 0x1D:                     # right
            s.col += 1
            if s.col >= COLS:
                s.col = 0
                s.row += 1
                if s.row >= ROWS:
                    scroll()
        elif p == 0x9D:                     # left
            if s.col > 0:
                s.col -= 1
            elif s.row > 0:
                s.row, s.col = s.row - 1, COLS - 1
        elif p == 0x14:                     # delete: pull the rest of the line left
            if s.col > 0:
                s.col -= 1
                line, cols = s.chars[s.row], s.colours[s.row]
                del line[s.col]
                del cols[s.col]
                line.append(0x20)
                cols.append(s.colour)
        elif p == 0x94:                     # insert: push the rest of the line right
            line, cols = s.chars[s.row], s.colours[s.row]
            line.insert(s.col, 0x20)
            cols.insert(s.col, s.colour)
            line.pop()
            cols.pop()
        elif p == 0x0E:
            s.lowercase = True
        elif p == 0x8E:
            s.lowercase = False
        else:
            code = petscii_to_screencode(p)
            if code is None:
                continue                    # other control codes (F-keys, stop...) do nothing
            s.chars[s.row][s.col] = code | (0x80 if s.reverse else 0)
            s.colours[s.row][s.col] = s.colour
            s.used.add((s.row, s.col))
            s.col += 1
            if s.col >= COLS:
                s.col = 0
                s.row += 1
                if s.row >= ROWS:
                    scroll()
    return s


# ---------------------------------------------------------------------- outputs

def to_basic(petscii: bytes, line_number: int | None = None) -> str:
    """A PRINT string in BASIC listing notation ({names} for codes that can't be typed)."""
    parts = []
    for p in petscii:
        if p == 0x22:
            parts.append("{$22}")           # a quote would end the string
        elif 0x41 <= p <= 0x5A:
            parts.append(chr(p + 32))       # unshifted letters are written lower case
        elif 0xC1 <= p <= 0xDA:
            parts.append(chr(p - 0x80))     # shifted letters are written upper case
        elif 0x20 <= p <= 0x40 or p in (0x5B, 0x5D):
            parts.append(chr(p))
        elif p == 0x5C:
            parts.append("£")
        elif p == 0x5E:
            parts.append("^")
        elif p == 0x5F:
            parts.append("_")
        elif p in CODE_TO_NAME:
            parts.append(f"{{{CODE_TO_NAME[p]}}}")
        else:
            parts.append(f"{{${p:02x}}}")
    # collapse repeats: {down}{down}{down} -> {3 down}
    out: list[list] = []
    for p in parts:
        if out and p.startswith("{") and out[-1][0] == p:
            out[-1][1] += 1
        else:
            out.append([p, 1])
    body = "".join(p if n == 1 else f"{{{n} {p[1:-1]}}}" for p, n in out)
    stmt = f'print "{body}";'
    return f"{line_number} {stmt}" if line_number is not None else stmt


def _byte_lines(data: bytes, label: str, kickass: bool, comment: str) -> str:
    c = "//" if kickass else ";"
    directive = ".byte" if kickass else "byte"
    lines = [f"{c} {comment}"]
    if label:
        lines.append(f"{label}:" if kickass else label)
    for i in range(0, len(data), 16):
        lines.append(f"        {directive} " + ", ".join(f"${b:02X}" for b in data[i:i + 16]))
    return "\n".join(lines) + "\n"


def to_petscii_bytes(petscii: bytes, label: str = "", kickass: bool = False, terminator: bool = True) -> str:
    """PETSCII bytes to print with the KERNAL's CHROUT ($FFD2), ending in 0 if terminator."""
    data = petscii + (b"\0" if terminator else b"")
    return _byte_lines(data, label, kickass, f"PETSCII for CHROUT ($FFD2){', ends with 0' if terminator else ''}")


def to_screen_codes(screen: Screen, label: str = "", kickass: bool = False, colours: bool = False) -> str:
    """The printed rows as screen codes (and colours), to copy straight into screen memory.

    Only the rows something was printed on are included, each a full 40 bytes.
    """
    rows = sorted({r for r, _ in screen.used})
    if not rows:
        raise BuildError("Nothing is printed, so there are no screen codes")
    first, last = rows[0], rows[-1]
    chars = bytes(b for r in range(first, last + 1) for b in screen.chars[r])
    text = _byte_lines(chars, label, kickass,
                       f"Screen codes for rows {first}-{last} ({len(chars)} bytes, from ${0x0400 + first * 40:04X})")
    if colours:
        cols = bytes(b for r in range(first, last + 1) for b in screen.colours[r])
        text += _byte_lines(cols, f"{label}Colours" if label else "", kickass,
                            f"Colour RAM for the same rows (from ${0xD800 + first * 40:04X})")
    return text
