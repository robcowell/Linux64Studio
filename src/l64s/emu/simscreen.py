"""The simulated C64's screen (emu.sim), drawn from its memory as the VIC-II shows it: the text and
bitmap modes, the border, fine scrolling across, and the sprites, a raster line at a time.

Each line is drawn with the VIC-II's registers as they were on that line (``frame_lines``: the
registers at the frame's start, and the writes the simulator recorded during it, with the line each
happened on). So a raster split works: a border or background colour changed halfway down, a mode
or character set changed for the bottom of the screen, sprites moved down the screen to be shown
again (multiplexed). What's still a picture of memory: the screen and colour memory are read as they
are now, not as each line was drawn; a register written partway along a line counts from that line;
vertical fine scrolling, the 38-column and 24-row modes and sprite priority aren't drawn (sprites
are in front of everything).

``collisions`` works out the sprite collision registers from the same lines.
"""
from __future__ import annotations

from ..gfx.palette import PALETTE_HEX

BORDER_X, BORDER_Y = 32, 32
WIDTH, HEIGHT = 320 + 2 * BORDER_X, 200 + 2 * BORDER_Y
RGB = [bytes(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in PALETTE_HEX]
LINES = 312                     # PAL
FIRST_LINE = 50 - BORDER_Y      # the raster line at the picture's top
REGS = 0x2F                     # the VIC-II's registers, $D000-$D02E; one more byte: $DD00 (the bank)
BANK = REGS


def registers_now(io) -> bytes:
    """The VIC-II's registers (and the bank, from $DD00) as ``io`` ($D000-$DFFF) has them."""
    return bytes(io[:REGS]) + bytes([io[0xD00]])


def frame_lines(start: bytes, log, now: bytes | None = None, upto: int | None = None) -> list[bytes]:
    """The registers on each raster line of a frame: ``start``, the frame's at its first line, with
    ``log``'s writes [(line, register, value)] applied from their lines on. With ``upto``, lines past
    it (not reached yet) have ``now``, the registers as they are."""
    regs = bytearray(start)
    out = []
    i = 0
    for line in range(LINES):
        while i < len(log) and log[i][0] <= line:
            regs[log[i][1]] = log[i][2]
            i += 1
        out.append(now if upto is not None and line > upto else bytes(regs))
    return out


class _Vic:
    """What the VIC-II sees: its 16K bank of RAM, with the character ROM in banks 0 and 2."""

    def __init__(self, ram, bank_bits: int, chargen):
        self.ram, self.chargen = ram, chargen
        self.bank = (3 - (bank_bits & 3)) * 0x4000

    def byte(self, offset: int) -> int:
        offset &= 0x3FFF
        if self.chargen is not None and self.bank in (0x0000, 0x8000) and 0x1000 <= offset < 0x2000:
            return self.chargen[offset - 0x1000]
        return self.ram[self.bank + offset]


def _vics(ram, chargen):
    cache: dict[int, _Vic] = {}

    def vic(r: bytes) -> _Vic:
        bits = r[BANK] & 3
        if bits not in cache:
            cache[bits] = _Vic(ram, bits, chargen)
        return cache[bits]
    return vic


def render(ram, io, chargen, lines: list[bytes] | None = None) -> bytes:
    """The screen as WIDTH x HEIGHT RGB bytes. ``ram``: the 64K of RAM; ``io``: $D000-$DFFF (colour
    RAM at $D800); ``chargen``: the character ROM (or None); ``lines``: the registers on each raster
    line (frame_lines), or None for the registers as ``io`` has them, all the way down."""
    if lines is None:
        lines = [registers_now(io)] * LINES
    vic = _vics(ram, chargen)
    pixels = []
    for py in range(HEIGHT):
        raster = FIRST_LINE + py
        r = lines[raster]
        row = [r[0x20] & 15] * WIDTH
        if r[0x11] & 0x10 and 50 <= raster < 250:
            row[BORDER_X:BORDER_X + 320] = _display_line(vic(r), io, r, raster - 50)
        pixels.append(row)
    for line, sprites in _sprite_lines(lines, vic).items():
        py = line - FIRST_LINE
        if not 0 <= py < HEIGHT:
            continue
        target = pixels[py]
        for _n, x, cols in reversed(sprites):              # sprite 0 in front
            for p, c in enumerate(cols):
                px = BORDER_X + x - 24 + p
                if c is not None and 0 <= px < WIDTH:
                    target[px] = c
    out = bytearray()
    for row in pixels:
        out += b"".join(RGB[c] for c in row)
    return bytes(out)


def _cells(v: _Vic, io, r: bytes, y: int):
    """Each of display line y's 40 cells: (the 8 pixels' byte, its colours (for 0/1 or the 4 pairs),
    multicolour)."""
    d011, d016, d018 = r[0x11], r[0x16], r[0x18]
    row, line = divmod(y, 8)
    screen = (d018 >> 4) * 0x400
    bitmap, ecm, mcm = bool(d011 & 0x20), bool(d011 & 0x40), bool(d016 & 0x10)
    bg = [r[0x21 + i] & 15 for i in range(4)]
    for col in range(40):
        i = row * 40 + col
        code = v.byte(screen + i)
        colour = io[0x800 + i] & 15
        if bitmap:
            data = v.byte((d018 & 8) * 0x400 + i * 8 + line)
            if mcm:
                yield data, (bg[0], code >> 4, code & 15, colour), True
            else:
                yield data, (code & 15, code >> 4), False
        elif ecm:
            yield v.byte(((d018 >> 1) & 7) * 0x800 + (code & 0x3F) * 8 + line), (bg[code >> 6], colour), False
        else:
            data = v.byte(((d018 >> 1) & 7) * 0x800 + code * 8 + line)
            if mcm and colour & 8:
                yield data, (bg[0], bg[1], bg[2], colour & 7), True
            else:
                yield data, (bg[0], colour), False


def _display_line(v: _Vic, io, r: bytes, y: int) -> list[int]:
    """Display line y's 320 pixels, scrolled right by $D016's fine X scroll."""
    out: list[int] = []
    for data, colours, multi in _cells(v, io, r, y):
        if multi:
            for b in range(4):
                c = colours[(data >> (6 - 2 * b)) & 3]
                out += (c, c)
        else:
            out += [colours[1] if data & (0x80 >> b) else colours[0] for b in range(8)]
    scroll = r[0x16] & 7
    if scroll:
        out = [r[0x21] & 15] * scroll + out[:320 - scroll]
    return out


# ---------------------------------------------------------------------- sprites

def _sprite_lines(lines: list[bytes], vic) -> dict[int, list[tuple[int, int, list]]]:
    """Each raster line's sprites: [(sprite, x, its 24 or 48 pixels' colours (None: clear))]. A sprite
    starts on the line its Y says (if it's on then), with the registers of each line it's drawn on,
    so one moved further down the screen once it's drawn is drawn again there."""
    out: dict[int, list] = {}
    drawing: dict[int, list[int]] = {}                    # sprite -> [row, line in the row]
    for line in range(LINES):
        r = lines[line]
        for n in range(8):
            bit = 1 << n
            if not r[0x15] & bit:
                drawing.pop(n, None)
                continue
            state = drawing.get(n)
            if state is None:
                if r[2 * n + 1] != line & 0xFF:
                    continue
                state = drawing[n] = [0, 0]
            v = vic(r)
            pointer = v.byte((r[0x18] >> 4) * 0x400 + 0x3F8 + n) * 64
            data = bytes(v.byte(pointer + state[0] * 3 + k) for k in range(3))
            x = r[2 * n] | (0x100 if r[0x10] & bit else 0)
            multi, wide = bool(r[0x1C] & bit), bool(r[0x1D] & bit)
            cols = _sprite_colours(data, multi, wide, r[0x27 + n] & 15, r[0x25] & 15, r[0x26] & 15)
            out.setdefault(line, []).append((n, x, cols))
            state[1] += 1
            if state[1] >= (2 if r[0x17] & bit else 1):
                state[0], state[1] = state[0] + 1, 0
                if state[0] == 21:
                    del drawing[n]
    return out


def _sprite_colours(data: bytes, multi: bool, wide: bool, colour: int, mc0: int, mc1: int) -> list:
    word = data[0] << 16 | data[1] << 8 | data[2]
    if multi:
        cols = []
        for p in range(12):
            pair = (word >> (22 - 2 * p)) & 3
            c = None if pair == 0 else (mc0, colour, mc1)[pair - 1]
            cols += (c, c)
    else:
        cols = [colour if word & (1 << (23 - p)) else None for p in range(24)]
    if wide:
        cols = [c for c in cols for _ in (0, 1)]
    return cols


# ---------------------------------------------------------------------- collisions
# What the VIC-II's collision registers would have: $D01E, the sprites that touched another sprite,
# and $D01F, those that touched the background's foreground (a set pixel of a hires character or
# bitmap, a 10 or 11 pair of a multicolour one). Each line is a Python int, a bit a pixel, bit x
# being the sprite coordinate x.

_REV = [int(f"{b:08b}"[::-1], 2) for b in range(256)]       # a byte's bits the other way round
_patterns: dict = {}


def _sprite_row(data: bytes, multi: bool, wide: bool) -> int:
    """A sprite row's pixels (bit 0 its leftmost), from its 3 bytes."""
    key = (data, multi, wide)
    p = _patterns.get(key)
    if p is None:
        p = 0
        for i, c in enumerate(_sprite_colours(data, multi, wide, 1, 1, 1)):
            if c is not None:
                p |= 1 << i
        _patterns[key] = p
    return p


def _background_line(v: _Vic, io, r: bytes, y: int) -> int:
    """The foreground pixels of display line y (0-199), at their sprite coordinates (x + 24)."""
    out = bytearray(40)
    for col, (data, _colours, multi) in enumerate(_cells(v, io, r, y)):
        if multi:
            data &= 0xAA                                # a pair is foreground if its high bit's set
            data |= data >> 1
        out[col] = _REV[data]
    return int.from_bytes(out, "little") << (24 + (r[0x16] & 7))


def collisions(ram, io, chargen, lines: list[bytes] | None = None) -> tuple[int, int]:
    """($D01E, $D01F) bits for a frame: its lines' registers (frame_lines), or None for the
    registers as ``io`` has them, all the way down."""
    if lines is None:
        if not io[0x15]:
            return 0, 0
        lines = [registers_now(io)] * LINES
    vic = _vics(ram, chargen)
    ss = sb = 0
    for line, sprites in _sprite_lines(lines, vic).items():
        r = lines[line]
        masks = [(n, sum(1 << (x + i) for i, c in enumerate(cols) if c is not None)) for n, x, cols in sprites]
        if len(masks) > 1:
            for i, (a, pa) in enumerate(masks):
                for b, pb in masks[i + 1:]:
                    if pa & pb:
                        ss |= 1 << a | 1 << b
        if r[0x11] & 0x10 and 50 <= line < 250:
            bg = _background_line(vic(r), io, r, line - 50)
            for n, p in masks:
                if p & bg:
                    sb |= 1 << n
    return ss, sb
