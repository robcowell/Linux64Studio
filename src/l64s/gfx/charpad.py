"""CharPad .ctm projects (format version 5, CharPad 2.0-2.3), following CharPad's own format notes.

Header (20 bytes): "CTM", version 5, screen colour, multicolour 1, multicolour 2, char colour,
colouring method (0 global, 1 per tile, 2 per char), flags (b0 tiles, b1 char-expanded, b2
multicolour), char count - 1 (16-bit), tile count - 1 (16-bit), tile width, tile height,
map width (16-bit), map height (16-bit). Then: char data (8 bytes each), char attributes
(MMMMCCCC, one per char), tile data (16-bit cells, absent if no tiles or char-expanded),
tile colours (only for per-tile colouring), map data (16-bit cells). Little-endian throughout.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from .charset import Charset
from .screen import Screen, ScreenSet

COLOUR_GLOBAL, COLOUR_PER_TILE, COLOUR_PER_CHAR = 0, 1, 2
FLAG_TILES, FLAG_CHAREX, FLAG_MULTICOLOUR = 1, 2, 4


class CharPadError(ValueError):
    pass


@dataclass
class CharPadProject:
    charset: Charset
    colour_method: int = COLOUR_PER_CHAR
    tiles_enabled: bool = False
    char_expanded: bool = False
    tile_count: int = 0
    tile_width: int = 1
    tile_height: int = 1
    tile_data: list[int] = field(default_factory=list)   # tile_count * w * h cells
    tile_colours: bytes = b""
    map_width: int = 40
    map_height: int = 25
    map_data: list[int] = field(default_factory=lambda: [0] * 1000)

    @property
    def map_editable(self) -> bool:
        """Map cells are characters (not tiles), so the screen editor can edit them directly."""
        return not self.tiles_enabled

    def cell_colour(self, ch: int, tile: int | None = None) -> int:
        cs = self.charset
        if self.colour_method == COLOUR_PER_CHAR:
            return cs.colour_of(ch)
        if self.colour_method == COLOUR_PER_TILE and tile is not None and tile < len(self.tile_colours):
            return self.tile_colours[tile] & 0x0F
        return cs.char_colour

    # -------------------------------------------------------------- map <-> screen
    def _tile_cells(self, tile: int) -> list[int]:
        n = self.tile_width * self.tile_height
        if self.char_expanded:
            return list(range(tile * n, tile * n + n))
        return self.tile_data[tile * n:(tile + 1) * n]

    def to_screenset(self) -> ScreenSet:
        """The map as a screen (tiles expanded into characters)."""
        if self.tiles_enabled:
            tw, th = self.tile_width, self.tile_height
            cols, rows = self.map_width * tw, self.map_height * th
        else:
            tw = th = 1
            cols, rows = self.map_width, self.map_height
        chars = [[0] * cols for _ in range(rows)]
        colours = [[0] * cols for _ in range(rows)]
        for my in range(self.map_height):
            for mx in range(self.map_width):
                cell = self.map_data[my * self.map_width + mx]
                if self.tiles_enabled:
                    tc = self._tile_cells(cell)
                    for ty in range(th):
                        for tx in range(tw):
                            ch = tc[ty * tw + tx] if ty * tw + tx < len(tc) else 0
                            chars[my * th + ty][mx * tw + tx] = ch & 0xFF
                            colours[my * th + ty][mx * tw + tx] = self.cell_colour(ch & 0xFF, cell)
                else:
                    chars[my][mx] = cell & 0xFF
                    colours[my][mx] = self.cell_colour(cell & 0xFF)
        cs = self.charset
        scr = Screen(chars=chars, colours=colours, flags=[[0] * cols for _ in range(rows)],
                     background=cs.background, border=cs.background, bk1=cs.mc1, bk2=cs.mc2)
        return ScreenSet(screens=[scr], rows=rows, cols=cols, multicolour=cs.multicolour)

    def update_map_from(self, screens: ScreenSet) -> None:
        if not self.map_editable:
            return
        s = screens.screens[0]
        self.map_data = [s.chars[r][c] for r in range(self.map_height) for c in range(self.map_width)]

    # -------------------------------------------------------------- tile map editing
    def tile_cells(self, tile: int) -> list[int]:
        """The characters of a tile, row by row."""
        return self._tile_cells(tile)

    def tile_at(self, x: int, y: int) -> int:
        return self.map_data[y * self.map_width + x]

    def set_tile_at(self, x: int, y: int, tile: int) -> None:
        if not 0 <= tile < max(1, self.tile_count):
            raise CharPadError(f"There's no tile {tile}")
        self.map_data[y * self.map_width + x] = tile

    def set_tile_cell(self, tile: int, cell: int, ch: int) -> None:
        """Set one character of a tile (cells are row by row)."""
        if self.char_expanded:
            raise CharPadError("In a char-expanded project each tile's characters are fixed")
        n = self.tile_width * self.tile_height
        self.tile_data[tile * n + cell] = ch & 0xFF

    def add_tile(self, copy_of: int | None = None) -> int:
        """A new tile at the end (a copy of another, or blank); returns its number."""
        if self.char_expanded:
            raise CharPadError("A char-expanded project can't have more tiles than characters allow")
        if self.tile_count >= 256:
            raise CharPadError("There are already 256 tiles: an 8-bit map can't use more")
        n = self.tile_width * self.tile_height
        cells = self.tile_cells(copy_of) if copy_of is not None else [0] * n
        self.tile_data += list(cells)
        self.tile_count += 1
        return self.tile_count - 1

    def tile_uses(self) -> list[int]:
        """How many map cells use each tile."""
        uses = [0] * max(1, self.tile_count)
        for t in self.map_data:
            if t < len(uses):
                uses[t] += 1
        return uses

    # -------------------------------------------------------------- exports (CharPad's binary formats)
    def export_charset(self) -> bytes:
        return self.charset.to_bin(self.charset.count)

    def export_attribs(self) -> bytes:
        attrs = self.charset.attribs or [self.charset.char_colour] * 256
        return bytes(a & 0xFF for a in attrs[:self.charset.count])

    def export_map(self) -> bytes:
        return bytes(c & 0xFF for c in self.map_data)

    def export_tiles(self) -> bytes:
        return bytes(c & 0xFF for t in range(self.tile_count) for c in self._tile_cells(t))


def load_ctm(path: str | Path) -> CharPadProject:
    data = Path(path).read_bytes()
    name = Path(path).name
    if len(data) < 20 or data[:3] != b"CTM":
        raise CharPadError(f"{name} isn't a CharPad file")
    if data[3] != 5:
        raise CharPadError(f"CharPad format version {data[3]} isn't supported (only version 5, CharPad 2.x)")
    (screen, mc1, mc2, charcol, method, flags, n_chars, n_tiles, tw, th, mw, mh) = \
        struct.unpack_from("<4BBBHHBBHH", data, 4)
    n_chars += 1
    n_tiles += 1
    if n_chars > 256:
        raise CharPadError(f"{name} has {n_chars} characters; only up to 256 are supported")
    tiles = bool(flags & FLAG_TILES)
    charex = bool(flags & FLAG_CHAREX)
    off = 20

    def take(n: int) -> bytes:
        nonlocal off
        if off + n > len(data):
            raise CharPadError(f"{name} is truncated")
        chunk = data[off:off + n]
        off += n
        return chunk

    raw_chars = take(n_chars * 8)
    attribs = list(take(n_chars))
    tile_data: list[int] = []
    tile_colours = b""
    if tiles and not charex:
        td = take(n_tiles * tw * th * 2)
        tile_data = list(struct.unpack(f"<{n_tiles * tw * th}H", td))
    if tiles and method == COLOUR_PER_TILE:
        tile_colours = take(n_tiles)
    md = take(mw * mh * 2)
    map_data = list(struct.unpack(f"<{mw * mh}H", md))

    cs = Charset(multicolour=bool(flags & FLAG_MULTICOLOUR), background=screen & 0x0F, mc1=mc1 & 0x0F,
                 mc2=mc2 & 0x0F, char_colour=charcol & 0x0F, count=n_chars)
    cs.chars = [list(raw_chars[i * 8:i * 8 + 8]) for i in range(n_chars)] + [[0] * 8] * (256 - n_chars)
    cs.chars = [list(c) for c in cs.chars]
    cs.attribs = attribs + [charcol & 0x0F] * (256 - n_chars)
    return CharPadProject(charset=cs, colour_method=method, tiles_enabled=tiles, char_expanded=charex,
                          tile_count=n_tiles if tiles else 0, tile_width=tw, tile_height=th,
                          tile_data=tile_data, tile_colours=tile_colours, map_width=mw, map_height=mh,
                          map_data=map_data)


def save_ctm(p: CharPadProject, path: str | Path) -> None:
    cs = p.charset
    n_chars = max(1, min(256, cs.count))
    flags = (FLAG_TILES if p.tiles_enabled else 0) | (FLAG_CHAREX if p.char_expanded else 0) | \
            (FLAG_MULTICOLOUR if cs.multicolour else 0)
    n_tiles = max(1, p.tile_count)
    out = bytearray(b"CTM\x05")
    out += struct.pack("<4BBBHHBBHH", cs.background & 15, cs.mc1 & 15, cs.mc2 & 15, cs.char_colour & 15,
                       p.colour_method, flags, n_chars - 1, n_tiles - 1, p.tile_width, p.tile_height,
                       p.map_width, p.map_height)
    out += bytes(b & 0xFF for c in cs.chars[:n_chars] for b in c)
    attrs = cs.attribs or [cs.char_colour] * 256
    out += bytes(a & 0xFF for a in attrs[:n_chars])
    if p.tiles_enabled and not p.char_expanded:
        out += struct.pack(f"<{len(p.tile_data)}H", *p.tile_data)
    if p.tiles_enabled and p.colour_method == COLOUR_PER_TILE:
        out += p.tile_colours
    out += struct.pack(f"<{len(p.map_data)}H", *p.map_data)
    Path(path).write_bytes(bytes(out))


def from_binaries(chars: bytes, attribs: bytes, tiles: bytes, map_data: bytes, map_width: int,
                  tile_width: int = 2, tile_height: int = 2, multicolour: bool = False,
                  background: int = 0, mc1: int = 1, mc2: int = 2) -> CharPadProject:
    """A project from CharPad's binary exports (characters, attributes with colour in the low
    nibble and material in the high one, 8-bit tiles row by row, 8-bit map row by row), so a
    game whose data is those files can be edited and exported back exactly."""
    if not chars or len(chars) % 8:
        raise CharPadError(f"The character data should be 8 bytes a character ({len(chars)} bytes)")
    n_chars = len(chars) // 8
    if n_chars > 256:
        raise CharPadError(f"{n_chars} characters: only up to 256 are supported")
    if len(attribs) != n_chars:
        raise CharPadError(f"The attributes should be one byte a character: {n_chars} characters but "
                           f"{len(attribs)} attribute bytes")
    cells = tile_width * tile_height
    if tile_width < 1 or tile_height < 1 or not tiles or len(tiles) % cells:
        raise CharPadError(f"The tile data ({len(tiles)} bytes) isn't whole {tile_width}x{tile_height} tiles")
    n_tiles = len(tiles) // cells
    if n_tiles > 256:
        raise CharPadError(f"{n_tiles} tiles: an 8-bit map can use 256 at most")
    if map_width < 1 or not map_data or len(map_data) % map_width:
        raise CharPadError(f"The map ({len(map_data)} bytes) isn't whole rows of {map_width} tiles")
    bad = sorted({t for t in map_data if t >= n_tiles})
    if bad:
        raise CharPadError(f"The map uses tile {bad[0]}, but there are only {n_tiles} tiles")
    cs = Charset(multicolour=multicolour, background=background & 15, mc1=mc1 & 15, mc2=mc2 & 15,
                 char_colour=attribs[0] & 15 if attribs else 1, count=n_chars)
    cs.chars = [list(chars[i * 8:i * 8 + 8]) for i in range(n_chars)] + [[0] * 8 for _ in range(256 - n_chars)]
    cs.attribs = list(attribs) + [cs.char_colour] * (256 - n_chars)
    return CharPadProject(charset=cs, colour_method=COLOUR_PER_CHAR, tiles_enabled=True, char_expanded=False,
                          tile_count=n_tiles, tile_width=tile_width, tile_height=tile_height,
                          tile_data=list(tiles), map_width=map_width, map_height=len(map_data) // map_width,
                          map_data=list(map_data))
