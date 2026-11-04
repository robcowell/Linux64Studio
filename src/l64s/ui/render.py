"""Rendering C64 graphics into cairo image surfaces (fast enough in pure Python)."""
from __future__ import annotations

import cairo

from ..gfx.palette import PALETTE_HEX

_BGRX = [bytes((int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16), 255)) for h in PALETTE_HEX]


class Bitmap:
    """A width x height image of palette indices, convertible to a cairo surface."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.pixels = bytearray(width * height)

    def surface(self) -> cairo.ImageSurface:
        data = bytearray(b"".join(_BGRX[p & 0x0F] for p in self.pixels))
        return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, self.width, self.height, self.width * 4)


def paint_scaled(cr, surface: cairo.ImageSurface, x: float, y: float, sx: float, sy: float):
    cr.save()
    cr.translate(x, y)
    cr.scale(sx, sy)
    cr.set_source_surface(surface, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint()
    cr.restore()


def draw_char_into(bm: Bitmap, px: int, py: int, rows: list[int], fg: int, bg: int,
                   multicolour: bool = False, mc1: int = 0, mc2: int = 0):
    """Draw one 8x8 character at pixel (px, py).

    In multicolour mode (colour RAM value >= 8) bit pairs select: 00 bg, 01 mc1, 10 mc2, 11 fg & 7.
    """
    w = bm.width
    pix = bm.pixels
    if multicolour and fg >= 8:
        cols = (bg, mc1, mc2, fg & 7)
        for y in range(8):
            r = rows[y]
            base = (py + y) * w + px
            for x in range(4):
                c = cols[(r >> (6 - 2 * x)) & 3]
                pix[base + 2 * x] = c
                pix[base + 2 * x + 1] = c
    else:
        for y in range(8):
            r = rows[y]
            base = (py + y) * w + px
            for x in range(8):
                pix[base + x] = fg if (r >> (7 - x)) & 1 else bg


def render_charset_grid(chars: list[list[int]], fg: int, bg: int, multicolour: bool, mc1: int, mc2: int,
                        per_row: int = 16) -> Bitmap:
    rows = (len(chars) + per_row - 1) // per_row
    bm = Bitmap(per_row * 8, rows * 8)
    for i, c in enumerate(chars):
        draw_char_into(bm, (i % per_row) * 8, (i // per_row) * 8, c, fg, bg, multicolour, mc1, mc2)
    return bm


def render_sprite(rows: list[int], multi: bool, colour: int, bg: int, mc1: int, mc2: int) -> Bitmap:
    bm = Bitmap(24, 21)
    pix = bm.pixels
    for y in range(21):
        r = rows[y]
        if multi:
            cols = (bg, mc1, colour, mc2)
            for x in range(12):
                c = cols[(r >> (22 - 2 * x)) & 3]
                pix[y * 24 + 2 * x] = c
                pix[y * 24 + 2 * x + 1] = c
        else:
            for x in range(24):
                pix[y * 24 + x] = colour if (r >> (23 - x)) & 1 else bg
    return bm
