"""The character scratch pad (CBM prg Studio's Character Editor → Scratch Pad): a grid for
designing graphics made of several characters. Cells hold character codes (or nothing); the pad
shows them with the character set being edited, so edits to a character show straight away.

As in CBM prg Studio, the pad isn't tied to a project or a character set: it's kept in the
settings folder, and the screen designer can stamp it (or part of it) onto a screen.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

Rect = tuple[int, int, int, int]       # col, row, width, height


class ListError(ValueError):
    pass


def parse_list(text: str) -> list[int]:
    """Character codes from a list such as `1,2,3,4-10,11,12` ($hex and %binary allowed)."""
    def num(s: str) -> int:
        s = s.strip()
        try:
            if s.startswith("$"):
                return int(s[1:], 16)
            if s.startswith("%"):
                return int(s[1:], 2)
            return int(s)
        except ValueError:
            raise ListError(f"{s!r} isn't a character number") from None
    out: list[int] = []
    for part in text.split(","):
        if not part.strip():
            continue
        m = re.fullmatch(r"\s*([$%]?\w+)\s*-\s*([$%]?\w+)\s*", part)
        a, b = (num(m.group(1)), num(m.group(2))) if m else (num(part), num(part))
        for v in (a, b):
            if not 0 <= v <= 255:
                raise ListError(f"{v} isn't a character number (0-255)")
        out += list(range(a, b + 1)) if a <= b else list(range(a, b - 1, -1))
    if not out:
        raise ListError("Give some character numbers, such as 1,2,3,4-10")
    return out


@dataclass
class CharScratchPad:
    cols: int = 16
    rows: int = 10
    cells: list[list[int | None]] = field(default_factory=list)

    def __post_init__(self):
        if not self.cells:
            self.cells = [[None] * self.cols for _ in range(self.rows)]

    def get(self, c: int, r: int) -> int | None:
        return self.cells[r][c] if 0 <= r < self.rows and 0 <= c < self.cols else None

    def set(self, c: int, r: int, ch: int | None):
        if 0 <= r < self.rows and 0 <= c < self.cols:
            self.cells[r][c] = ch

    def used(self) -> set[int]:
        return {ch for row in self.cells for ch in row if ch is not None}

    def resize(self, cols: int, rows: int):
        cols, rows = max(1, cols), max(1, rows)
        self.cells = [[(self.cells[r][c] if r < self.rows and c < self.cols else None) for c in range(cols)]
                      for r in range(rows)]
        self.cols, self.rows = cols, rows

    def clear(self):
        self.cells = [[None] * self.cols for _ in range(self.rows)]

    def place_list(self, codes: list[int], col: int, row: int, across: bool = True) -> int:
        """Put characters in order from (col, row), along the row (then the next row) or down the
        column (then the next). Returns how many didn't fit."""
        c, r = col, row
        for n, ch in enumerate(codes):
            if not (0 <= c < self.cols and 0 <= r < self.rows):
                return len(codes) - n
            self.cells[r][c] = ch
            if across:
                c += 1
                if c >= self.cols:
                    c, r = 0, r + 1
            else:
                r += 1
                if r >= self.rows:
                    r, c = 0, c + 1
        return 0

    def shift(self, dx: int, dy: int):
        """Move everything, wrapping round the edges."""
        self.cells = [[self.cells[(r - dy) % self.rows][(c - dx) % self.cols] for c in range(self.cols)]
                      for r in range(self.rows)]

    # ---------------------------------------------------------------- blocks
    def copy(self, rect: Rect | None = None) -> list[list[int | None]]:
        c0, r0, w, h = rect or (0, 0, self.cols, self.rows)
        return [[self.get(c, r) for c in range(c0, c0 + w)] for r in range(r0, r0 + h)]

    def erase(self, rect: Rect):
        c0, r0, w, h = rect
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                self.set(c, r, None)

    def paste(self, block: list[list[int | None]], col: int, row: int):
        for dr, line in enumerate(block):
            for dc, ch in enumerate(line):
                if ch is not None:
                    self.set(col + dc, row + dr, ch)

    def bounds(self) -> Rect | None:
        """The smallest rectangle holding every character on the pad."""
        cs = [c for r in range(self.rows) for c in range(self.cols) if self.cells[r][c] is not None]
        rs = [r for r in range(self.rows) for c in range(self.cols) if self.cells[r][c] is not None]
        if not cs:
            return None
        return min(cs), min(rs), max(cs) - min(cs) + 1, max(rs) - min(rs) + 1

    # ---------------------------------------------------------------- saving
    def to_dict(self) -> dict:
        return {"cols": self.cols, "rows": self.rows, "cells": self.cells}

    @classmethod
    def from_dict(cls, d: dict) -> "CharScratchPad":
        cols, rows = int(d.get("cols", 16)), int(d.get("rows", 10))
        cells = d.get("cells") or []
        grid = [[(cells[r][c] if r < len(cells) and c < len(cells[r]) else None) for c in range(cols)]
                for r in range(rows)]
        return cls(cols, rows, grid)


def pad_file() -> Path:
    from ..settings import config_dir
    return config_dir() / "char_scratchpad.json"


_shared: CharScratchPad | None = None
selection: Rect | None = None          # the part of the pad selected in its window (the screen designer stamps it)


def shared() -> CharScratchPad:
    """The one scratch pad, as CBM prg Studio has, loaded from the settings folder."""
    global _shared
    if _shared is None:
        try:
            _shared = CharScratchPad.from_dict(json.loads(pad_file().read_text()))
        except (OSError, ValueError, TypeError, KeyError):
            _shared = CharScratchPad()
    return _shared


def save_shared():
    if _shared is None:
        return
    p = pad_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_shared.to_dict()) + "\n")
    except OSError:
        pass


def stamp_block() -> list[list[int | None]]:
    """What the screen designer stamps: the selection in the pad's window, else the whole drawing."""
    pad = shared()
    rect = selection or pad.bounds()
    return pad.copy(rect) if rect else []
