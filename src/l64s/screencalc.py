"""Screen Calculator: the screen and colour memory addresses of a row and column, the cell at an
address, and where a cell is in sprite coordinates.

The text screen is 40 columns by 25 rows, one byte per cell, row by row: screen memory at the
VIC-II's screen address ($0400 at power-on) and colour RAM, which never moves, at $D800. A
sprite at X=24, Y=50 has its top-left corner on the top-left of the screen (cell 0,0), so
column c starts at X = 24 + 8c and row r at Y = 50 + 8r. X above 255 needs the sprite's bit in
$D010 (the X high bits).
"""
from __future__ import annotations

from dataclasses import dataclass

COLUMNS = 40
ROWS = 25
SCREEN_BASE = 0x0400
COLOUR_BASE = 0xD800
SPRITE_X0 = 24
SPRITE_Y0 = 50


def check_cell(row: int, col: int) -> None:
    if not 0 <= row < ROWS:
        raise ValueError(f"The row must be 0-{ROWS - 1}")
    if not 0 <= col < COLUMNS:
        raise ValueError(f"The column must be 0-{COLUMNS - 1}")


def offset(row: int, col: int) -> int:
    check_cell(row, col)
    return row * COLUMNS + col


def screen_address(row: int, col: int, base: int = SCREEN_BASE) -> int:
    return base + offset(row, col)


def colour_address(row: int, col: int, base: int = COLOUR_BASE) -> int:
    return base + offset(row, col)


@dataclass
class Located:
    area: str          # "screen" or "colour"
    row: int
    col: int


def locate(address: int, screen_base: int = SCREEN_BASE, colour_base: int = COLOUR_BASE) -> Located | None:
    """The cell an address belongs to, in screen memory or colour RAM (None if neither)."""
    for area, base in (("screen", screen_base), ("colour", colour_base)):
        off = address - base
        if 0 <= off < COLUMNS * ROWS:
            return Located(area, off // COLUMNS, off % COLUMNS)
    return None


def sprite_xy(row: int, col: int) -> tuple[int, int]:
    """The sprite X, Y that puts a sprite's top-left corner on a cell's top-left corner."""
    check_cell(row, col)
    return SPRITE_X0 + 8 * col, SPRITE_Y0 + 8 * row


def sprite_cell(x: int, y: int) -> tuple[int, int] | None:
    """The cell under sprite coordinates (None if they're in the border)."""
    col, row = (x - SPRITE_X0) // 8, (y - SPRITE_Y0) // 8
    if 0 <= col < COLUMNS and 0 <= row < ROWS:
        return row, col
    return None


def _hex(v: int) -> str:
    return f"${v:04X}"


@dataclass
class Result:
    label: str
    text: str


def results(row: int, col: int, screen_base: int = SCREEN_BASE, colour_base: int = COLOUR_BASE,
            char: int = 1, colour: int = 1, kickass: bool = False, syntax: str | None = None) -> list[Result]:
    """Everything worth copying for a cell, each line ready to paste. For C ("c"), C replaces the
    assembler, and the expression is C's."""
    off = offset(row, col)
    scr, clr = screen_base + off, colour_base + off
    x, y = sprite_xy(row, col)
    c = "//" if kickass else ";"
    ind = "    " if kickass else "        "
    msb = "  (above 255: set the sprite's bit in $D010)" if x > 255 else ""
    if syntax == "c":
        return [
            Result("Screen address", f"{_hex(scr)}  ({scr})"),
            Result("Colour address", f"{_hex(clr)}  ({clr})"),
            Result("Offset", f"{off}  (row {row} × 40 + column {col}, {_hex(off)})"),
            Result("Expression", f"0x{screen_base:04X} + {row} * 40 + {col}"),
            Result("C", f"*(unsigned char *)0x{scr:04X} = {char};    /* row {row}, column {col} */\n"
                        f"*(unsigned char *)0x{clr:04X} = {colour};    /* its colour */"),
            Result("BASIC", f"poke {scr},{char} : poke {clr},{colour}"),
            Result("Sprite X, Y", f"{x}, {y}{msb}"),
        ]
    return [
        Result("Screen address", f"{_hex(scr)}  ({scr})"),
        Result("Colour address", f"{_hex(clr)}  ({clr})"),
        Result("Offset", f"{off}  (row {row} × 40 + column {col}, {_hex(off)})"),
        Result("Expression", f"{_hex(screen_base)} + {row}*40 + {col}"),
        Result("BASIC", f"poke {scr},{char} : poke {clr},{colour}"),
        Result("Assembler", f"{ind}lda #{char}\n{ind}sta {_hex(scr)}{'':6}{c} row {row}, column {col}\n"
                            f"{ind}lda #{colour}\n{ind}sta {_hex(clr)}{'':6}{c} its colour"),
        Result("Sprite X, Y", f"{x}, {y}{msb}"),
    ]
