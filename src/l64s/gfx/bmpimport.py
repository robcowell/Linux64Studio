"""Import sprites from an image (CBM prg Studio's Sprite Editor → Import → From Bitmap).

The image is cut into 24×21-pixel cells (times a scale, for an image saved zoomed in), from a
starting point and with an optional gap between cells, taken row by row or column by column.

* Hires: a pixel is set when it's darker than the threshold (CBM prg Studio's rule), or lighter,
  for art drawn on a dark background. Transparent pixels are never set.
* Multicolour: each sprite pixel is two image pixels wide. Each takes the bit pair of the nearest
  of four colours (background, multicolour 1, sprite colour, multicolour 2) if it's within the
  tolerance, otherwise background. `guess_colours` finds the four in the image.

Unlike CBM prg Studio, the sprite colours can be set from the image too (the nearest C64 colours).
Besides .bmp, any image GdkPixbuf reads (PNG, GIF, ...) works.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .palette import PALETTE_HEX
from .sprite import HEIGHT, Sprite

WIDTH = 24
RGB = tuple[int, int, int]
PALETTE = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in PALETTE_HEX]
_MAX_DIST = (3 * 255 ** 2) ** 0.5


class ImageError(ValueError):
    pass


@dataclass
class Image:
    width: int
    height: int
    pixels: bytes          # RGBA, row by row
    kind: str = ""         # "BMP, 24 bits per pixel" etc., for the dialog

    def rgba(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        p = self.pixels
        return p[i], p[i + 1], p[i + 2], p[i + 3]

    @classmethod
    def from_rows(cls, rows: list[list[RGB | None]]) -> "Image":
        """For tests: rows of (r, g, b), with None for transparent."""
        h, w = len(rows), len(rows[0]) if rows else 0
        data = bytearray()
        for row in rows:
            for px in row:
                data += bytes([*px, 255]) if px is not None else bytes(4)
        return cls(w, h, bytes(data))


def load_image(path: Path) -> Image:
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    try:
        fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(str(path))
        pb = GdkPixbuf.Pixbuf.new_from_file(str(path))
    except (GLib.Error, TypeError) as e:
        raise ImageError(f"Can't read {Path(path).name} as an image: {getattr(e, 'message', e)}") from None
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, stride = pb.get_width(), pb.get_height(), pb.get_rowstride()
    raw = pb.get_pixels()
    data = b"".join(raw[y * stride:y * stride + w * 4] for y in range(h))
    kind = (fmt.get_name().upper() if fmt else "image")
    return Image(w, h, data, f"{kind}, {w}×{h} pixels")


@dataclass
class Options:
    x: int = 0                     # where the first cell starts, in image pixels
    y: int = 0
    gap_x: int = 0                 # pixels between cells (a sheet's grid lines or spacing)
    gap_y: int = 0
    scale: int = 1                 # image pixels per sprite pixel (an image saved zoomed in)
    count: int = 0                 # how many sprites; 0 = as many as fit
    column_first: bool = False     # scan down each column first
    multi: bool = False
    threshold: int = 50            # hires: % dark (or light) for a pixel to be set
    light_on: bool = False         # hires: light pixels are set, not dark ones
    # multicolour: the image colour for each bit pair (0 background, 1 MC1, 2 sprite colour, 3 MC2)
    colours: list[RGB | None] = field(default_factory=lambda: [(0, 0, 0), (255, 255, 255), (136, 136, 136),
                                                               (68, 68, 68)])
    tolerance: int = 30            # multicolour: % distance a pixel may be from its colour
    skip_empty: bool = False       # leave out cells with nothing in them


@dataclass
class Result:
    sprites: list[Sprite]
    cells: list[tuple[int, int]]   # each sprite's cell, top left, in image pixels
    colour: int                    # the nearest C64 colours, for the sprite colour and multicolours
    mcolour1: int
    mcolour2: int


def cell_size(o: Options) -> tuple[int, int]:
    return WIDTH * o.scale, HEIGHT * o.scale


def cells(img: Image, o: Options) -> list[tuple[int, int]]:
    """The top-left corner of each whole cell in the image, in scan order."""
    cw, ch = cell_size(o)
    xs = list(range(o.x, img.width - cw + 1, cw + o.gap_x)) if o.x >= 0 else []
    ys = list(range(o.y, img.height - ch + 1, ch + o.gap_y)) if o.y >= 0 else []
    if o.column_first:
        return [(x, y) for x in xs for y in ys]
    return [(x, y) for y in ys for x in xs]


def nearest_c64(rgb: RGB) -> int:
    return min(range(16), key=lambda i: sum((a - b) ** 2 for a, b in zip(rgb, PALETTE[i])))


def _dist(a: RGB, b: RGB) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _darkness(r: int, g: int, b: int) -> float:
    return 100 - (0.299 * r + 0.587 * g + 0.114 * b) / 2.55


class _Classifier:
    def __init__(self, o: Options):
        self.o = o
        self.cache: dict[tuple[int, int, int, int], int] = {}

    def __call__(self, px: tuple[int, int, int, int]) -> int:
        v = self.cache.get(px)
        if v is None:
            v = self.cache[px] = self._classify(px)
        return v

    def _classify(self, px) -> int:
        r, g, b, a = px
        if a < 128:
            return 0
        o = self.o
        if not o.multi:
            d = _darkness(r, g, b)
            return int((100 - d if o.light_on else d) > o.threshold)
        best, best_d = 0, None
        for v, c in enumerate(o.colours):
            if c is None:
                continue
            d = _dist((r, g, b), c)
            if best_d is None or d < best_d:
                best, best_d = v, d
        if best_d is None or best_d * 100 / _MAX_DIST > o.tolerance:
            return 0
        return best


def _sample(img: Image, x: int, y: int, scale: int) -> tuple[int, int, int, int]:
    """The pixel in the middle of a scaled-up pixel."""
    return img.rgba(min(img.width - 1, x + scale // 2), min(img.height - 1, y + scale // 2))


def cut(img: Image, at: tuple[int, int], o: Options, classify=None) -> Sprite:
    """One sprite from the cell at `at`."""
    classify = classify or _Classifier(o)
    s = Sprite(multi=o.multi)
    cx, cy = at
    sc = o.scale
    for y in range(HEIGHT):
        iy = cy + y * sc
        if o.multi:
            for x in range(12):
                left = classify(_sample(img, cx + 2 * x * sc, iy, sc))
                right = classify(_sample(img, cx + (2 * x + 1) * sc, iy, sc))
                s.set(x, y, left if left or not right else right)   # a half-drawn pair isn't lost
        else:
            for x in range(WIDTH):
                s.set(x, y, classify(_sample(img, cx + x * sc, iy, sc)))
    return s


def import_sprites(img: Image, o: Options) -> Result:
    classify = _Classifier(o)
    sprites, used = [], []
    for at in cells(img, o):
        s = cut(img, at, o, classify)
        if o.skip_empty and not any(s.rows):
            continue
        sprites.append(s)
        used.append(at)
        if o.count and len(sprites) >= o.count:
            break
    colour, mc1, mc2 = _colours(img, o, used)
    for s in sprites:
        s.colour = colour
    return Result(sprites, used, colour, mc1, mc2)


def _colours(img: Image, o: Options, used: list[tuple[int, int]]) -> tuple[int, int, int]:
    """The C64 colours to give the sprites: in multicolour, the nearest to the chosen colours; in
    hires, the nearest to the most common colour of the set pixels."""
    if o.multi:
        pick = [nearest_c64(c) if c is not None else d for c, d in zip(o.colours, (0, 1, 2, 3))]
        return pick[2], pick[1], pick[3]
    classify = _Classifier(o)
    seen: Counter = Counter()
    cw, ch = cell_size(o)
    for cx, cy in used[:16]:
        for y in range(cy, cy + ch, o.scale):
            for x in range(cx, cx + cw, o.scale):
                px = _sample(img, x, y, o.scale)
                if classify(px):
                    seen[px[:3]] += 1
    colour = nearest_c64(seen.most_common(1)[0][0]) if seen else 1
    return colour, 1, 2


def guess_colours(img: Image, o: Options, hints: tuple[int, int, int] | None = None) -> list[RGB | None]:
    """The four colours of a multicolour image. The commonest (or a transparent area) is the
    background. Which of the others is which can't be told from the image, so `hints` (the C64
    colours the sprite set already uses: sprite colour, multicolour 1, multicolour 2) are matched
    first, then the rest go by how often they appear: sprite colour, multicolour 1, multicolour 2."""
    counts: Counter = Counter()
    transparent = 0
    cw, ch = cell_size(o)
    for cx, cy in cells(img, o)[:64]:
        for y in range(cy, cy + ch, o.scale):
            for x in range(cx, cx + cw, o.scale):
                r, g, b, a = _sample(img, x, y, o.scale)
                if a < 128:
                    transparent += 1
                else:
                    counts[(r, g, b)] += 1
    common = [c for c, _n in counts.most_common()]
    if transparent and (not common or transparent >= counts[common[0]]):
        bg: RGB | None = None
    else:
        bg = common.pop(0) if common else (0, 0, 0)
    # merge colours that are nearly the same (anti-aliasing, JPEG noise) into the first one seen
    distinct: list[RGB] = []
    for c in common:
        if all(_dist(c, d) > 24 for d in distinct):
            distinct.append(c)
    slots: dict[int, RGB] = {}                  # bit pair -> colour
    if hints:
        for pair, c64 in zip((2, 1, 3), hints):
            near = [c for c in distinct if c not in slots.values() and _dist(c, PALETTE[c64]) < 40]
            if near:
                slots[pair] = min(near, key=lambda c: _dist(c, PALETTE[c64]))
    rest = [c for c in distinct if c not in slots.values()]
    for pair in (2, 1, 3):
        if pair not in slots and rest:
            slots[pair] = rest.pop(0)
    sprite, mc1, mc2 = slots.get(2), slots.get(1), slots.get(3)
    return [bg, mc1, sprite, mc2]               # bg None: the background is the transparent part
