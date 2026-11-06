"""The simulated C64's screen (emu.sim), drawn from its memory as the VIC-II would show it at the end
of a frame: the text and bitmap modes, the border, and the sprites. It's a picture of memory, not an
emulated VIC-II: there are no raster effects (a change made halfway down the screen shows on all of
it), no smooth scrolling, and sprites are drawn in front of everything.
"""
from __future__ import annotations

from ..gfx.palette import PALETTE_HEX

BORDER_X, BORDER_Y = 32, 32
WIDTH, HEIGHT = 320 + 2 * BORDER_X, 200 + 2 * BORDER_Y
RGB = [bytes(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in PALETTE_HEX]


class _Vic:
    """What the VIC-II sees: its 16K bank of RAM, with the character ROM in banks 0 and 2."""

    def __init__(self, ram, io, chargen):
        self.ram, self.io, self.chargen = ram, io, chargen
        self.bank = (3 - (io[0xD00] & 3)) * 0x4000

    def byte(self, offset: int) -> int:
        offset &= 0x3FFF
        if self.chargen is not None and self.bank in (0x0000, 0x8000) and 0x1000 <= offset < 0x2000:
            return self.chargen[offset - 0x1000]
        return self.ram[self.bank + offset]


def render(ram, io, chargen) -> bytes:
    """The screen as WIDTH x HEIGHT RGB bytes. ``ram``: the 64K of RAM; ``io``: $D000-$DFFF (colour
    RAM at $D800); ``chargen``: the character ROM (or None)."""
    v = _Vic(ram, io, chargen)
    reg = lambda r: io[r]                                   # noqa: E731
    border = reg(0x20) & 15
    pixels = [[border] * WIDTH for _ in range(HEIGHT)]
    d011, d016, d018 = reg(0x11), reg(0x16), reg(0x18)
    if d011 & 0x10:                                         # the screen is on
        _draw_screen(v, pixels, d011, d016, d018)
        _draw_sprites(v, pixels, d018)
    out = bytearray()
    for row in pixels:
        out += b"".join(RGB[c] for c in row)
    return bytes(out)


def _draw_screen(v: _Vic, pixels, d011: int, d016: int, d018: int) -> None:
    io = v.io
    screen = (d018 >> 4) * 0x400
    bitmap, ecm, mcm = bool(d011 & 0x20), bool(d011 & 0x40), bool(d016 & 0x10)
    bg = [io[0x21 + i] & 15 for i in range(4)]
    chars = ((d018 >> 1) & 7) * 0x800
    bits = (d018 & 8) * 0x400
    for row in range(25):
        for col in range(40):
            i = row * 40 + col
            code = v.byte(screen + i)
            colour = io[0x800 + i] & 15
            for line in range(8):
                if bitmap:
                    data = v.byte(bits + i * 8 + line)
                    if mcm:
                        four = (bg[0], code >> 4, code & 15, colour)
                        cells = _multi(data, four)
                    else:
                        cells = _hires(data, code >> 4, code & 15)
                elif ecm:
                    data = v.byte(chars + (code & 0x3F) * 8 + line)
                    cells = _hires(data, colour, bg[code >> 6])
                else:
                    data = v.byte(chars + code * 8 + line)
                    if mcm and colour & 8:
                        cells = _multi(data, (bg[0], bg[1], bg[2], colour & 7))
                    else:
                        cells = _hires(data, colour, bg[0])
                y = BORDER_Y + row * 8 + line
                x = BORDER_X + col * 8
                pixels[y][x:x + 8] = cells


def _hires(data: int, fg: int, bg: int) -> list[int]:
    return [fg if data & (0x80 >> b) else bg for b in range(8)]


def _multi(data: int, four) -> list[int]:
    out = []
    for b in range(4):
        c = four[(data >> (6 - 2 * b)) & 3]
        out += (c, c)
    return out


def _draw_sprites(v: _Vic, pixels, d018: int) -> None:
    io = v.io
    on, high, multi = io[0x15], io[0x10], io[0x1C]
    wide, tall = io[0x1D], io[0x17]
    mc = (io[0x25] & 15, io[0x26] & 15)
    pointers = (d018 >> 4) * 0x400 + 0x3F8
    for n in range(7, -1, -1):                              # sprite 0 in front
        bit = 1 << n
        if not on & bit:
            continue
        x = io[2 * n] | (0x100 if high & bit else 0)
        y = io[2 * n + 1]
        data = v.byte(pointers + n) * 64
        colour = io[0x27 + n] & 15
        sx, sy = (2 if wide & bit else 1), (2 if tall & bit else 1)
        for line in range(21):
            row = [v.byte(data + line * 3 + k) for k in range(3)]
            word = row[0] << 16 | row[1] << 8 | row[2]
            if multi & bit:
                cols = []
                for p in range(12):
                    pair = (word >> (22 - 2 * p)) & 3
                    c = None if pair == 0 else (mc[0], colour, mc[1])[pair - 1]
                    cols += (c, c)
            else:
                cols = [colour if word & (1 << (23 - p)) else None for p in range(24)]
            for dy in range(sy):
                py = BORDER_Y + y - 50 + line * sy + dy
                if not 0 <= py < HEIGHT:
                    continue
                target = pixels[py]
                for p, c in enumerate(cols):
                    if c is None:
                        continue
                    for dx in range(sx):
                        px = BORDER_X + x - 24 + p * sx + dx
                        if 0 <= px < WIDTH:
                            target[px] = c


# ---------------------------------------------------------------------- collisions
# What the VIC-II's collision registers would have: $D01E, the sprites that touched another sprite,
# and $D01F, those that touched the background's foreground (a set pixel of a hires character or
# bitmap, a 10 or 11 pair of a multicolour one), over a frame as memory has it now. Each line is a
# Python int, a bit a pixel, bit x being the sprite coordinate x.

_REV = [int(f"{b:08b}"[::-1], 2) for b in range(256)]       # a byte's bits the other way round
_patterns: dict = {}


def _sprite_row(data: bytes, multi: bool, wide: bool) -> int:
    """A sprite row's pixels (bit 0 its leftmost), from its 3 bytes."""
    key = (data, multi, wide)
    p = _patterns.get(key)
    if p is None:
        word = data[0] << 16 | data[1] << 8 | data[2]
        p = 0
        if multi:
            for i in range(12):
                if (word >> (22 - 2 * i)) & 3:
                    p |= 3 << (2 * i)
        else:
            for i in range(24):
                if word >> (23 - i) & 1:
                    p |= 1 << i
        if wide:
            q = 0
            for i in range(48 if multi else 24):
                if p >> i & 1:
                    q |= 3 << (2 * i)
            p = q
        _patterns[key] = p
    return p


def _background_line(v: _Vic, io, y: int) -> int:
    """The foreground pixels of display line y (0-199), shifted to sprite coordinates (x + 24)."""
    d011, d016, d018 = io[0x11], io[0x16], io[0x18]
    row, line = divmod(y, 8)
    screen = (d018 >> 4) * 0x400
    bitmap, ecm, mcm = bool(d011 & 0x20), bool(d011 & 0x40), bool(d016 & 0x10)
    out = bytearray(40)
    for col in range(40):
        i = row * 40 + col
        code = v.byte(screen + i)
        if bitmap:
            b = v.byte((d018 & 8) * 0x400 + i * 8 + line)
            multi = mcm
        else:
            ch = code & 0x3F if ecm else code
            b = v.byte(((d018 >> 1) & 7) * 0x800 + ch * 8 + line)
            multi = mcm and not ecm and io[0x800 + i] & 8
        if multi:
            b &= 0xAA                                   # a pair is foreground if its high bit's set
            b |= b >> 1
        out[col] = _REV[b]
    return int.from_bytes(out, "little") << 24


def collisions(ram, io, chargen) -> tuple[int, int]:
    """($D01E, $D01F) bits for the sprites as memory has them now."""
    on = io[0x15]
    if not on:
        return 0, 0
    v = _Vic(ram, io, chargen)
    pointers = (io[0x18] >> 4) * 0x400 + 0x3F8
    rows: dict[int, list[tuple[int, int]]] = {}             # sprite y line -> [(sprite, pixels)]
    for n in range(8):
        bit = 1 << n
        if not on & bit:
            continue
        x = io[2 * n] | (0x100 if io[0x10] & bit else 0)
        y = io[2 * n + 1]
        data = v.byte(pointers + n) * 64
        tall = 2 if io[0x17] & bit else 1
        for r in range(21):
            row = bytes(v.byte(data + r * 3 + k) for k in range(3))
            pixels = _sprite_row(row, bool(io[0x1C] & bit), bool(io[0x1D] & bit)) << x
            if pixels:
                for dy in range(tall):
                    rows.setdefault((y + r * tall + dy) % 312, []).append((n, pixels))
    ss = sb = 0
    display = bool(io[0x11] & 0x10)
    for line, sprites in rows.items():
        if len(sprites) > 1:
            for i, (a, pa) in enumerate(sprites):
                for b, pb in sprites[i + 1:]:
                    if pa & pb:
                        ss |= 1 << a | 1 << b
        if display and 50 <= line < 250:
            bg = _background_line(v, io, line - 50)
            for n, p in sprites:
                if p & bg:
                    sb |= 1 << n
    return ss, sb
