"""The screen designer's digitiser, as in CBM prg Studio: the sprite coordinates of a point on the
screen, in a format of your choosing.

The X and Y offsets are added to the point's pixel position on the screen (0,0 is the top-left of
the 40x25 text area). With the usual 24 and 50 they give sprite coordinates: a sprite at those X,
Y has its top-left corner at that point. MSB takes 256 off X, for the part that goes in the
sprite's X register when its bit in $D010 is set.

The format is any text with {x} and {y} in it; {$x} / {$y} give hex (lower case), {$X} / {$Y}
upper case hex.
"""
from __future__ import annotations

import re

X_OFFSET, Y_OFFSET = 24, 50
FORMAT = "{x}, {y}"
PRESETS = ["{x}, {y}", "byte {x}, {y}", "byte ${$X}, ${$Y}", "word {x}\\nbyte {y}", "poke v,{x} : poke v+1,{y}"]
_FIELD = re.compile(r"\{(\$?)([xXyY])\}")


class FormatError(ValueError):
    pass


def check_format(fmt: str) -> None:
    names = {m.group(2).lower() for m in _FIELD.finditer(fmt)}
    if names != {"x", "y"}:
        raise FormatError("The format needs an x and a y: {x} and {y} (or {$x} and {$y} for hex)")


def coords(px: int, py: int, x_offset: int = X_OFFSET, y_offset: int = Y_OFFSET, msb: bool = False) -> tuple[int, int]:
    """Sprite coordinates for a pixel on the screen."""
    x = px + x_offset
    if msb:
        x -= 256
    return x, py + y_offset


def format_point(fmt: str, x: int, y: int) -> str:
    check_format(fmt)

    def sub(m):
        v = x if m.group(2).lower() == "x" else y
        if m.group(1):
            h = f"{v & 0xFFFF:X}" if v >= 0 else f"-{-v:X}"
            h = h.rjust(2, "0") if v >= 0 else h
            return h if m.group(2).isupper() else h.lower()
        return str(v)
    return _FIELD.sub(sub, fmt).replace("\\n", "\n")
