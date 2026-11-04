"""Screen designs: one or more 40x25 screens of characters + colours, like CBM prg Studio's .sdd.

Each .sdd cell is a hex number: bits 20-27 are the character, bits 12-19 the colour
(low nibble used), and the low bits hold editor-only flags we preserve verbatim.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

COLS, ROWS = 40, 25


@dataclass
class Screen:
    chars: list[list[int]] = field(default_factory=lambda: [[32] * COLS for _ in range(ROWS)])
    colours: list[list[int]] = field(default_factory=lambda: [[14] * COLS for _ in range(ROWS)])
    flags: list[list[int]] = field(default_factory=lambda: [[0] * COLS for _ in range(ROWS)])
    background: int = 6
    border: int = 14
    bk1: int = 0
    bk2: int = 0
    m3: int = 0


@dataclass
class ScreenSet:
    screens: list[Screen] = field(default_factory=lambda: [Screen()])
    rows: int = ROWS
    cols: int = COLS
    multicolour: bool = False

    def export_chars(self, first_row: int = 0, last_row: int | None = None,
                     side_by_side: bool = False) -> bytes:
        """Character data for INCBIN.

        side_by_side=True writes all screens next to each other as one wide map, row by row
        (the book's MAPRAM layout: 6 screens x 40 = 240 bytes per row).
        """
        last = self.rows - 1 if last_row is None else last_row
        out = bytearray()
        if side_by_side:
            for r in range(first_row, last + 1):
                for s in self.screens:
                    out += bytes(s.chars[r])
        else:
            for s in self.screens:
                for r in range(first_row, last + 1):
                    out += bytes(s.chars[r])
        return bytes(out)

    def export_colours(self, first_row: int = 0, last_row: int | None = None,
                       side_by_side: bool = False) -> bytes:
        last = self.rows - 1 if last_row is None else last_row
        out = bytearray()
        order = ([(r, s) for r in range(first_row, last + 1) for s in self.screens] if side_by_side
                 else [(r, s) for s in self.screens for r in range(first_row, last + 1)])
        for r, s in order:
            out += bytes(c & 0x0F for c in s.colours[r])
        return bytes(out)

    @classmethod
    def load_sdd(cls, path: str | Path) -> "ScreenSet":
        text = Path(path).read_bytes().decode("utf-8-sig")
        root = ET.fromstring(text)
        rows = int(root.findtext("Rows", "25"))
        cols = int(root.findtext("Columns", "40"))
        ss = cls(screens=[], rows=rows, cols=cols, multicolour=root.findtext("ScreenMode", "0") == "1")
        for sel in root.findall("./Screens/Screen"):
            scr = Screen(chars=[[32] * cols for _ in range(rows)], colours=[[14] * cols for _ in range(rows)],
                         flags=[[0] * cols for _ in range(rows)])
            for r, rd in enumerate(sel.findall("RowData")[:rows]):
                for c, cell in enumerate((rd.text or "").split(",")[:cols]):
                    v = int(cell, 16) if cell.strip() else 0x2000E00
                    scr.chars[r][c] = (v >> 20) & 0xFF
                    scr.colours[r][c] = (v >> 12) & 0xFF
                    scr.flags[r][c] = v & 0xFFF
            scr.background = int(sel.findtext("BackgroundColour", "6"))
            scr.border = int(sel.findtext("BorderColour", "14"))
            scr.bk1 = int(sel.findtext("BK1Colour", "0"))
            scr.bk2 = int(sel.findtext("BK2Colour", "0"))
            scr.m3 = int(sel.findtext("M3Colour", "0"))
            ss.screens.append(scr)
        if not ss.screens:
            ss.screens.append(Screen())
        return ss

    def save_sdd(self, path: str | Path) -> None:
        root = ET.Element("ScreenDesignerData")
        for tag, val in (("FileVersion", "3"), ("Rows", self.rows), ("Columns", self.cols), ("Mode", "0"),
                         ("ScreenMode", "1" if self.multicolour else "0")):
            ET.SubElement(root, tag).text = str(val)
        ET.SubElement(root, "CharacterSet")
        scs = ET.SubElement(root, "Screens")
        for s in self.screens:
            el = ET.SubElement(scs, "Screen")
            for tag, val in (("BK1Colour", s.bk1), ("BK2Colour", s.bk2), ("M3Colour", s.m3),
                             ("BackgroundColour", s.background), ("BorderColour", s.border)):
                ET.SubElement(el, tag).text = str(val)
            for r in range(self.rows):
                cells = [f"{(s.chars[r][c] << 20) | ((s.colours[r][c] & 0xFF) << 12) | (s.flags[r][c] & 0xFFF):07X}"
                         for c in range(self.cols)]
                ET.SubElement(el, "RowData").text = ",".join(cells)
            ET.SubElement(el, "Description")
        ET.indent(root)
        Path(path).write_bytes(b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
                               + ET.tostring(root, encoding="utf-8"))
