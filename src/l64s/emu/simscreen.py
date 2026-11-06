"""The simulated C64's screen (emu.sim), drawn from its memory as the VIC-II shows it, a raster line at
a time: the text and bitmap modes, the border, fine scrolling both ways, the sprites and their
priority.

Each line is drawn with the VIC-II's registers as they were on that line (``frame_lines``: the
registers at the frame's start, and the writes the simulator recorded during it, with the line each
happened on). So a raster split works: a border or background colour changed halfway down, a mode
or character set changed for the bottom of the screen, sprites moved down the screen to be shown
again (multiplexed). Each character row's screen and colour memory are as the VIC-II read them, on
the row's badline (``fetched``: the simulator keeps them as it runs), so a program changing the
screen as it's drawn shows as it would on a C64.

As on a C64: rows start on the badlines, the lines whose low three bits are $D011's vertical scroll
(``Rows``), so the screen scrolls a pixel at a time both ways; the border covers the 38-column and
24-row modes' edges and is in front of the sprites (``vertical_border``: switching to 24 rows at the
right line opens the top and bottom border); a sprite starts the line after its Y; sprite 0 is in
front of sprite 1 and so on, and a sprite with its $D01B bit set is behind the characters' (or
bitmap's) foreground; outside the rows the VIC-II shows the byte at $3FFF of its bank ($39FF in ECM).
What's still simpler than a VIC-II: a register written partway along a line counts from that line;
the character set and bitmap are read as they are when drawn, not as on each line; the side border
can't be opened; and tricks that make the VIC-II's counters go wrong (FLI, line crunch, sprite
stretching) aren't drawn as on a C64.

``collisions`` works out the sprite collision registers from the same lines.
"""
from __future__ import annotations

from ..gfx.palette import PALETTE_HEX

BORDER_X, BORDER_Y = 32, 32
WIDTH, HEIGHT = 320 + 2 * BORDER_X, 200 + 2 * BORDER_Y
RGB = [bytes(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in PALETTE_HEX]
LINES = 312                     # PAL
TOP_LINE = 51                   # the raster line where 25 rows start (the display window's top)
FIRST_LINE = TOP_LINE - BORDER_Y    # the raster line at the picture's top
LEFT_X = 24                     # the sprite X of the display window's left edge (40 columns)
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


# ---------------------------------------------------------------------- rows and the border

class Rows:
    """The VIC-II's counting of character rows, a raster line at a time (``line``): a row starts on a
    badline (a line from 48 to 247 whose low three bits are $D011's vertical scroll, in a frame whose
    line 48 had the screen on), and has eight lines; after the eighth, until the next badline, the
    VIC-II is idle."""

    def __init__(self):
        self.row, self.rc, self.display, self.den = -1, 7, False, False

    def line(self, line: int, d011: int) -> tuple[tuple[int, int] | None, bool]:
        """Line ``line``'s (row, line in the row), or None (idle); and whether it's a badline, where the
        row's screen and colour memory are read."""
        if line == 0:
            self.row, self.rc, self.display = -1, 7, False
        if line == 48:
            self.den = bool(d011 & 0x10)
        bad = self.den and 48 <= line <= 247 and (line & 7) == (d011 & 7)
        if bad:
            if not self.display or self.rc == 7:
                self.row += 1
            self.display, self.rc = True, 0
        elif self.display:
            if self.rc == 7:
                self.display = False
            else:
                self.rc += 1
        if self.display and self.row < 25:
            return (self.row, self.rc), bad
        return None, False


def row_lines(lines: list[bytes]) -> list[tuple[int, int] | None]:
    """Each raster line's (row, line in the row), or None where the VIC-II is idle."""
    rows = Rows()
    return [rows.line(n, r[0x11])[0] for n, r in enumerate(lines)]


def vertical_border(lines: list[bytes]) -> list[bool]:
    """Whether each raster line is all border: from line 251 (247 with 24 rows) to line 51 (55), if
    the screen's on then. A frame that misses the bottom line (24 rows switched to 25 between them)
    has an open border; it stays open into the next frame, as here, where the frame's lines are gone
    round twice."""
    out = [True] * LINES
    border = True
    for _ in range(2):
        for n, r in enumerate(lines):
            top, bottom = (51, 251) if r[0x11] & 8 else (55, 247)
            if n == bottom:
                border = True
            elif n == top and r[0x11] & 0x10:
                border = False
            out[n] = border
    return out


def fetch_row(ram, io, chargen, r: bytes, row: int) -> tuple[bytes, bytes]:
    """A row's 40 screen codes and colours, as the VIC-II reads them on its badline (``r``: its
    registers then)."""
    v = _Vic(ram, r[BANK], chargen)
    screen = (r[0x18] >> 4) * 0x400 + row * 40
    return (bytes(v.byte(screen + i) for i in range(40)),
            bytes(io[0x800 + row * 40 + i] & 15 for i in range(40)))


# ---------------------------------------------------------------------- the graphics

def _cells(v: _Vic, io, r: bytes, where: tuple[int, int] | None, fetched):
    """A line's 40 cells: (the 8 pixels' byte, its colours (for 0/1 or the 4 pairs), multicolour).
    ``where``: (row, line in the row), or None for the idle state's byte."""
    d011, d016, d018 = r[0x11], r[0x16], r[0x18]
    bitmap, ecm, mcm = bool(d011 & 0x20), bool(d011 & 0x40), bool(d016 & 0x10)
    bg = [r[0x21 + i] & 15 for i in range(4)]
    if where is None:
        idle = v.byte(0x39FF if ecm else 0x3FFF)
        codes = colours = bytes(40)
    else:
        row, line = where
        idle = None
        got = fetched.get(row) if fetched else None
        codes, colours = got if got is not None else fetch_row(v.ram, io, v.chargen, r, row)
    for col in range(40):
        code, colour = codes[col], colours[col]
        if bitmap:
            data = idle if idle is not None else v.byte((d018 & 8) * 0x400 + (row * 40 + col) * 8 + line)
            if mcm:
                out = data, (bg[0], code >> 4, code & 15, colour), True
            else:
                out = data, (code & 15, code >> 4), False
        else:
            if idle is not None:
                data = idle
            else:
                data = v.byte(((d018 >> 1) & 7) * 0x800 + ((code & 0x3F) if ecm else code) * 8 + line)
            if ecm and not mcm:
                out = data, (bg[code >> 6], colour), False
            elif mcm and colour & 8:
                out = data, (bg[0], bg[1], bg[2], colour & 7), True
            else:
                out = data, (bg[0], colour), False
        if ecm and (mcm or bitmap):                     # the invalid modes: all black
            out = out[0], (0, 0, 0, 0), out[2]
        yield out


_REV = [int(f"{b:08b}"[::-1], 2) for b in range(256)]       # a byte's bits the other way round
_MASK = (1 << 320) - 1


def _graphics(v: _Vic, io, r: bytes, where, fetched) -> tuple[list[int], int]:
    """A line's 320 pixels (from the display window's left), scrolled right by $D016's fine X scroll,
    and its foreground (bit x for pixel x: a set pixel of a hires character or bitmap, a 10 or 11
    pair of a multicolour one), for sprite priority and collisions."""
    out: list[int] = []
    fg = bytearray(40)
    for i, (data, colours, multi) in enumerate(_cells(v, io, r, where, fetched)):
        if multi:
            for b in range(4):
                c = colours[(data >> (6 - 2 * b)) & 3]
                out += (c, c)
            hi = data & 0xAA
            fg[i] = _REV[hi | hi >> 1]
        else:
            out += [colours[1] if data & (0x80 >> b) else colours[0] for b in range(8)]
            fg[i] = _REV[data]
    scroll = r[0x16] & 7
    mask = int.from_bytes(fg, "little")
    if scroll:
        out = [r[0x21] & 15] * scroll + out[:320 - scroll]
        mask = (mask << scroll) & _MASK
    return out, mask


def _foreground(v: _Vic, io, r: bytes, where, fetched) -> int:
    """Only the foreground of _graphics (for collisions, every frame)."""
    fg = bytearray(40)
    for i, (data, _colours, multi) in enumerate(_cells(v, io, r, where, fetched)):
        if multi:
            data &= 0xAA
            data |= data >> 1
        fg[i] = _REV[data]
    return (int.from_bytes(fg, "little") << (r[0x16] & 7)) & _MASK


def _window(r: bytes) -> tuple[int, int]:
    """The display window across, in sprite X: 40 columns, or 38."""
    return (24, 344) if r[0x16] & 8 else (31, 335)


def render(ram, io, chargen, lines: list[bytes] | None = None, fetched: dict | None = None) -> bytes:
    """The screen as WIDTH x HEIGHT RGB bytes. ``ram``: the 64K of RAM; ``io``: $D000-$DFFF (colour
    RAM at $D800); ``chargen``: the character ROM (or None); ``lines``: the registers on each raster
    line (frame_lines), or None for the registers as ``io`` has them, all the way down; ``fetched``:
    {row: (screen codes, colours)} as the VIC-II read them (rows not in it are read from memory)."""
    return b"".join(RGB[c] for row in indices(ram, io, chargen, lines, fetched) for c in row)


def indices(ram, io, chargen, lines: list[bytes] | None = None, fetched: dict | None = None) -> list[list[int]]:
    """``render``'s picture as rows of colour numbers (0-15)."""
    if lines is None:
        lines = [registers_now(io)] * LINES
    vic = _vics(ram, chargen)
    rows = row_lines(lines)
    border = vertical_border(lines)
    sprites = _sprite_lines(lines, vic)
    shift = BORDER_X - LEFT_X                           # picture x = sprite X + shift
    pixels = []
    for py in range(HEIGHT):
        line = FIRST_LINE + py
        r = lines[line]
        row = [r[0x20] & 15] * WIDTH
        if not border[line]:
            left, right = _window(r)
            gfx, fg = _graphics(vic(r), io, r, rows[line], fetched)
            row[left + shift:right + shift] = gfx[left - LEFT_X:right - LEFT_X]
            taken = 0                                   # pixels a sprite in front has
            behind = r[0x1B]
            for n, x, cols in sprites.get(line, ()):
                for p, c in enumerate(cols):
                    sx = x + p
                    if c is None or not left <= sx < right or taken >> sx & 1:
                        continue
                    taken |= 1 << sx
                    if not (behind >> n & 1 and fg >> (sx - LEFT_X) & 1):
                        row[sx + shift] = c
        pixels.append(row)
    return pixels


# ---------------------------------------------------------------------- sprites

def _sprite_lines(lines: list[bytes], vic) -> dict[int, list[tuple[int, int, list]]]:
    """Each raster line's sprites, sprite 0 first: [(sprite, x, its 24 or 48 pixels' colours (None:
    clear))]. A sprite starts on the line after the one its Y says (if it's on then), and each of its
    lines has that line's registers, so one moved further down the screen once it's drawn is drawn
    again there."""
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
            if state is not None:
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
            if n not in drawing and r[2 * n + 1] == line & 0xFF:
                drawing[n] = [0, 0]                       # (from the next line)
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
# and $D01F, those that touched the foreground (as for priority) inside the display window. Each
# line is a Python int, a bit a pixel, bit x being the sprite coordinate x.

def collisions(ram, io, chargen, lines: list[bytes] | None = None, fetched: dict | None = None) -> tuple[int, int]:
    """($D01E, $D01F) bits for a frame: its lines' registers (frame_lines), or None for the
    registers as ``io`` has them, all the way down; ``fetched`` as for ``render``."""
    if lines is None:
        if not io[0x15]:
            return 0, 0
        lines = [registers_now(io)] * LINES
    vic = _vics(ram, chargen)
    sprites = _sprite_lines(lines, vic)
    if not sprites:
        return 0, 0
    rows = row_lines(lines)
    border = vertical_border(lines)
    ss = sb = 0
    for line, drawn in sprites.items():
        r = lines[line]
        masks = [(n, _pattern(x, cols)) for n, x, cols in drawn]
        if len(masks) > 1:
            for i, (a, pa) in enumerate(masks):
                for b, pb in masks[i + 1:]:
                    if pa & pb:
                        ss |= 1 << a | 1 << b
        if not border[line]:
            bg = _foreground(vic(r), io, r, rows[line], fetched) << LEFT_X
            for n, p in masks:
                if p & bg:
                    sb |= 1 << n
    return ss, sb


_patterns: dict = {}


def _pattern(x: int, cols: list) -> int:
    """A sprite line's pixels as bits at their sprite X."""
    key = tuple(c is not None for c in cols)
    p = _patterns.get(key)
    if p is None:
        p = sum(1 << i for i, set_ in enumerate(key) if set_)
        _patterns[key] = p
    return p << x
