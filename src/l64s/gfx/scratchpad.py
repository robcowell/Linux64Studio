"""The sprite scratch pad (CBM prg Studio's Sprite Editor → Scratch Pad): a grid where sprites are
put side by side, to see a graphic made of several sprites, or on top of each other, to see
layers. Each cell holds a stack of sprites, drawn in order (the last on top), each moved up to 20
pixels in its cell, and flipped or inverted. That changes only how the pad shows it: the sprites
themselves aren't touched.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .sprite import HEIGHT, Sprite

WIDTH = 24
MAX_OFFSET = 20


@dataclass
class Placement:
    sprite: int                 # index in the sprite set
    dx: int = 0                 # moved within the cell, -20..20 pixels
    dy: int = 0
    flip_x: bool = False
    flip_y: bool = False
    invert: bool = False

    def describe(self) -> str:
        bits = [f"Sprite {self.sprite}"]
        if self.dx or self.dy:
            bits.append(f"moved {self.dx:+d}, {self.dy:+d}")
        bits += [w for w, on in (("flipped across", self.flip_x), ("flipped down", self.flip_y),
                                 ("inverted", self.invert)) if on]
        return ", ".join(bits)


@dataclass
class ScratchPad:
    cols: int = 8
    rows: int = 4
    cells: dict[tuple[int, int], list[Placement]] = field(default_factory=dict)

    # ---------------------------------------------------------------- editing
    def stack(self, col: int, row: int) -> list[Placement]:
        return self.cells.get((col, row), [])

    def place(self, col: int, row: int, sprite: int) -> Placement:
        p = Placement(sprite)
        self.cells.setdefault((col, row), []).append(p)
        return p

    def remove(self, col: int, row: int, i: int):
        st = self.cells.get((col, row), [])
        if 0 <= i < len(st):
            del st[i]
        if not st:
            self.cells.pop((col, row), None)

    def raise_(self, col: int, row: int, i: int, by: int) -> int:
        """Move placement i up (by > 0, drawn later: more on top) or down the stack. Returns where it is."""
        st = self.cells.get((col, row), [])
        if not 0 <= i < len(st):
            return i
        j = max(0, min(len(st) - 1, i + by))
        st.insert(j, st.pop(i))
        return j

    def clear(self):
        self.cells.clear()

    def resize(self, cols: int, rows: int):
        self.cols, self.rows = max(1, cols), max(1, rows)
        self.cells = {k: v for k, v in self.cells.items() if k[0] < self.cols and k[1] < self.rows}

    # keep the pad pointing at the same sprites when the set changes
    def sprites_inserted(self, at: int, n: int = 1):
        for st in self.cells.values():
            for p in st:
                if p.sprite >= at:
                    p.sprite += n

    def sprite_removed(self, i: int):
        for k in list(self.cells):
            st = [p for p in self.cells[k] if p.sprite != i]
            for p in st:
                if p.sprite > i:
                    p.sprite -= 1
            if st:
                self.cells[k] = st
            else:
                del self.cells[k]

    # ---------------------------------------------------------------- drawing
    def render(self, sprites: list[Sprite], background: int, mc1: int, mc2: int) -> list[list[int]]:
        """The whole pad as rows of C64 colour numbers, (cols × 24) by (rows × 21). A sprite moved
        past its cell's edge carries on into the next cell, as on screen."""
        w, h = self.cols * WIDTH, self.rows * HEIGHT
        out = [[background] * w for _ in range(h)]
        for (c, r), st in sorted(self.cells.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            for p in st:
                if not 0 <= p.sprite < len(sprites):
                    continue
                s = sprites[p.sprite]
                ox, oy = c * WIDTH + p.dx, r * HEIGHT + p.dy
                for y in range(HEIGHT):
                    sy = HEIGHT - 1 - y if p.flip_y else y
                    py = oy + y
                    if not 0 <= py < h:
                        continue
                    for x in range(WIDTH):
                        sx = WIDTH - 1 - x if p.flip_x else x
                        if s.multi:
                            v = s.get(sx // 2, sy)          # each bit pair is two pixels wide
                            if p.invert:
                                v ^= 3
                            colour = (None, mc1, s.colour, mc2)[v]
                        else:
                            v = s.get(sx, sy) ^ int(p.invert)
                            colour = s.colour if v else None
                        px = ox + x
                        if colour is not None and 0 <= px < w:
                            out[py][px] = colour
        return out

    # ---------------------------------------------------------------- saving
    def to_dict(self) -> dict:
        return {"cols": self.cols, "rows": self.rows,
                "cells": [{"col": c, "row": r, "sprites": [asdict(p) for p in st]}
                          for (c, r), st in sorted(self.cells.items())]}

    @classmethod
    def from_dict(cls, d: dict) -> "ScratchPad":
        pad = cls(int(d.get("cols", 8)), int(d.get("rows", 4)))
        known = set(Placement.__dataclass_fields__)
        for cell in d.get("cells", []):
            st = [Placement(**{k: v for k, v in p.items() if k in known}) for p in cell.get("sprites", [])]
            if st:
                pad.cells[(int(cell["col"]), int(cell["row"]))] = st
        return pad
