"""Sprite sets: 24x21 sprites, hires or multicolour, stored like CBM prg Studio's .spt files.

A sprite is 63 bytes (21 rows x 3 bytes). Exported .bin files pad each sprite to 64 bytes,
which is how the book's sprites.bin is laid out (192 * 64 = $3000).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

WIDTH, HEIGHT = 24, 21
OVERLAY = 0x10      # attribute bit: the next sprite is drawn over this one


@dataclass
class Sprite:
    rows: list[int] = field(default_factory=lambda: [0] * HEIGHT)  # 24-bit row values
    multi: bool = False
    colour: int = 1          # sprite's own colour ($D027+n)
    expand_x: bool = False
    expand_y: bool = False
    description: str = ""
    # SpritePad keeps an attribute byte in byte 63 of each sprite: bit 7 multicolour, bits 0-3 colour.
    # Any other bits (e.g. SpritePad's overlay flag) are kept here so files round-trip unchanged.
    attr_extra: int = 0

    @property
    def overlay(self) -> bool:
        """SpritePad's "overlay next": the next sprite is drawn over this one (bit 4 of the attribute)."""
        return bool(self.attr_extra & OVERLAY)

    @overlay.setter
    def overlay(self, on: bool) -> None:
        self.attr_extra = (self.attr_extra | OVERLAY) if on else (self.attr_extra & ~OVERLAY)

    def colours(self, bg: int, mc1: int, mc2: int) -> list[int | None]:
        """24 x 21 palette indices, one per hires pixel, None where the sprite is transparent."""
        out: list[int | None] = []
        for r in self.rows:
            if self.multi:
                cols = (None, mc1, self.colour, mc2)
                for x in range(12):
                    c = cols[(r >> (22 - 2 * x)) & 3]
                    out += (c, c)
            else:
                out += [self.colour if (r >> (23 - x)) & 1 else None for x in range(24)]
        return out

    @property
    def attribute(self) -> int:
        return (0x80 if self.multi else 0) | (self.attr_extra & 0x70) | (self.colour & 0x0F)

    # -- pixel access. In multicolour mode x is 0-11 and values are 0-3 (bit pairs).
    def get(self, x: int, y: int) -> int:
        r = self.rows[y]
        if self.multi:
            return (r >> (22 - 2 * x)) & 3
        return (r >> (23 - x)) & 1

    def set(self, x: int, y: int, v: int) -> None:
        if self.multi:
            shift = 22 - 2 * x
            self.rows[y] = (self.rows[y] & ~(3 << shift)) | ((v & 3) << shift)
        else:
            shift = 23 - x
            self.rows[y] = (self.rows[y] & ~(1 << shift)) | ((v & 1) << shift)

    @property
    def pixel_width(self) -> int:
        return 12 if self.multi else 24

    def to_bytes(self) -> bytes:
        out = bytearray()
        for r in self.rows:
            out += bytes([(r >> 16) & 0xFF, (r >> 8) & 0xFF, r & 0xFF])
        return bytes(out)

    @classmethod
    def from_bytes(cls, data: bytes, **kw) -> "Sprite":
        data = data[:63].ljust(63, b"\0")
        rows = [(data[i * 3] << 16) | (data[i * 3 + 1] << 8) | data[i * 3 + 2] for i in range(HEIGHT)]
        return cls(rows=rows, **kw)

    # -- editing helpers
    def clear(self):
        self.rows = [0] * HEIGHT

    def flip_x(self):
        w = self.pixel_width
        px = [[self.get(x, y) for x in range(w)] for y in range(HEIGHT)]
        for y in range(HEIGHT):
            for x in range(w):
                self.set(x, y, px[y][w - 1 - x])

    def flip_y(self):
        self.rows.reverse()

    def shift(self, dx: int, dy: int):
        w = self.pixel_width
        px = [[self.get(x, y) for x in range(w)] for y in range(HEIGHT)]
        for y in range(HEIGHT):
            for x in range(w):
                sx, sy = (x - dx) % w, (y - dy) % HEIGHT
                self.set(x, y, px[sy][sx])

    def copy(self) -> "Sprite":
        return Sprite(list(self.rows), self.multi, self.colour, self.expand_x, self.expand_y, self.description,
                      self.attr_extra)


@dataclass
class SpriteSet:
    sprites: list[Sprite] = field(default_factory=lambda: [Sprite()])
    background: int = 0     # spbkgnd
    mcolour1: int = 1       # $D025
    mcolour2: int = 2       # $D026
    # Set when loaded from SpritePad: its exports put the attribute byte in byte 63 of each sprite,
    # where CBM prg Studio's exports put 0.
    attribute_bytes: bool = False
    animations: bytes = b""  # SpritePad animation table, kept verbatim
    # The .spd format the set came from (spritepad.py: 0 is SpritePad 1.8's headerless one), so saving
    # keeps it; for SPD V2 to V5, spd_extra is the header and everything after the sprites (tiles,
    # animations), written back unchanged.
    spd_version: int = 1
    spd_extra: bytes = b""

    def overlay_of(self, i: int) -> Sprite | None:
        """The sprite drawn over sprite i: the next one, when i has "overlay next" set."""
        if self.sprites[i].overlay and i + 1 < len(self.sprites):
            return self.sprites[i + 1]
        return None

    def composite(self, i: int) -> list[int]:
        """Sprite i as it looks on screen over the background, 24 x 21 palette indices, with the next
        sprite drawn over it when i overlays it."""
        cols = [self.background if c is None else c
                for c in self.sprites[i].colours(self.background, self.mcolour1, self.mcolour2)]
        top = self.overlay_of(i)
        if top is not None:
            for k, c in enumerate(top.colours(self.background, self.mcolour1, self.mcolour2)):
                if c is not None:
                    cols[k] = c
        return cols

    def to_bin(self, pad_to_64: bool = True, attribute_bytes: bool | None = None) -> bytes:
        attrs = self.attribute_bytes if attribute_bytes is None else attribute_bytes
        out = bytearray()
        for s in self.sprites:
            out += s.to_bytes()
            if pad_to_64:
                out.append(s.attribute if attrs else 0)
        return bytes(out)

    def to_source(self, label: str = "sprites", syntax: str = "cbm") -> str:
        """The sprites as data: CBM prg Studio BYTE statements, or ca65, Kick or C (syntax.py), 64 bytes
        a sprite (the 64th as the export writes it)."""
        if syntax != "cbm":
            from ..syntax import table
            data = self.to_bin()
            notes = [f"sprite {n}{' (multicolour)' if s.multi else ''}{': ' + s.description if s.description else ''}"
                     if i == 0 else "" for n, s in enumerate(self.sprites) for i in range(4)]
            return table(syntax, label, data, 1, 16, comment_text=f"{len(self.sprites)} sprites, 64 bytes each",
                         row_comments=notes)
        lines = [f"{label}"]
        for n, s in enumerate(self.sprites):
            lines.append(f"; sprite {n}{' (multicolour)' if s.multi else ''}")
            data = s.to_bytes() + b"\0"
            for i in range(0, 64, 16):
                lines.append("        byte " + ", ".join(f"${b:02X}" for b in data[i:i + 16]))
        return "\n".join(lines) + "\n"

    @classmethod
    def from_bin(cls, data: bytes, multi: bool = False) -> "SpriteSet":
        n = max(1, len(data) // 64)
        return cls([Sprite.from_bytes(data[i * 64:i * 64 + 63], multi=multi) for i in range(n)])

    # -- CBM prg Studio .spt (XML)
    @classmethod
    def load_spt(cls, path: str | Path) -> "SpriteSet":
        root = ET.fromstring(Path(path).read_bytes().decode("utf-8-sig"))
        sprites, ss = [], cls(sprites=[])
        for el in root.findall("sprite"):
            def t(tag, d=""):
                e = el.find(tag)
                return (e.text or d).strip() if e is not None and e.text else d
            rows = [int(d.text) for d in el.findall("./sdata/data")]
            rows = (rows + [0] * HEIGHT)[:HEIGHT]
            sprites.append(Sprite(rows=rows, multi=t("multi") == "True", colour=int(t("spcolour", "1")),
                                  expand_x=t("expandx") == "True", expand_y=t("expandy") == "True",
                                  description=t("description")))
            ss.background = int(t("spbkgnd", "0"))
            ss.mcolour1 = int(t("mcolour1", "1"))
            ss.mcolour2 = int(t("mcolour2", "2"))
        ss.sprites = sprites or [Sprite()]
        return ss

    def save_spt(self, path: str | Path) -> None:
        root = ET.Element("sprites")
        for s in self.sprites:
            el = ET.SubElement(root, "sprite")
            ET.SubElement(el, "description").text = s.description
            ET.SubElement(el, "links").text = ""
            ET.SubElement(el, "include").text = "True"
            ET.SubElement(el, "multi").text = str(s.multi)
            ET.SubElement(el, "spbkgnd").text = str(self.background)
            ET.SubElement(el, "spcolour").text = str(s.colour)
            ET.SubElement(el, "mcolour1").text = str(self.mcolour1)
            ET.SubElement(el, "mcolour2").text = str(self.mcolour2)
            ET.SubElement(el, "expandx").text = str(s.expand_x)
            ET.SubElement(el, "expandy").text = str(s.expand_y)
            sd = ET.SubElement(el, "sdata")
            for r in s.rows:
                ET.SubElement(sd, "data").text = str(r)
        ET.indent(root)
        Path(path).write_bytes(b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8"))
