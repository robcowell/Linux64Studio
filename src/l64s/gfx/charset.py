"""Character sets: 256 8x8 characters, hires or multicolour, stored like CBM prg Studio's .cst."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Characters a .cst file doesn't list are the C64's ROM characters. We read VICE's copy of
# the character ROM at runtime (it isn't redistributable, so it isn't bundled).
ROM_SEARCH = [
    Path.home() / ".local/share/vice/C64/chargen-901225-01.bin",
    Path("/usr/share/vice/C64/chargen-901225-01.bin"),
    Path("/usr/lib/vice/C64/chargen-901225-01.bin"),
    Path("/usr/local/share/vice/C64/chargen-901225-01.bin"),
]


def rom_charset(uppercase: bool = True) -> list[list[int]] | None:
    """The 256 characters of the C64 ROM (upper-case/graphics or lower/upper set), if available."""
    for p in ROM_SEARCH:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if len(data) >= 4096:
            base = 0 if uppercase else 2048
            return [list(data[base + i * 8: base + i * 8 + 8]) for i in range(256)]
    return None


@dataclass
class Charset:
    chars: list[list[int]] = field(default_factory=lambda: [[0] * 8 for _ in range(256)])
    multicolour: bool = False
    background: int = 0   # $D021 (not stored in .cst files)
    mc1: int = 1          # $D022 multicolour 1      (.cst <BK1>)
    mc2: int = 2          # $D023 multicolour 2      (.cst <BK2>)
    char_colour: int = 1  # colour RAM, pen 3 in multicolour mode (.cst <Col3>)
    uppercase: bool = True
    count: int = 256   # number of characters exported

    def get(self, ch: int, x: int, y: int) -> int:
        row = self.chars[ch][y]
        if self.multicolour:
            return (row >> (6 - 2 * x)) & 3
        return (row >> (7 - x)) & 1

    def set(self, ch: int, x: int, y: int, v: int) -> None:
        row = self.chars[ch][y]
        if self.multicolour:
            s = 6 - 2 * x
            row = (row & ~(3 << s)) | ((v & 3) << s)
        else:
            s = 7 - x
            row = (row & ~(1 << s)) | ((v & 1) << s)
        self.chars[ch][y] = row & 0xFF

    @property
    def pixel_width(self) -> int:
        return 4 if self.multicolour else 8

    def to_bin(self, count: int | None = None) -> bytes:
        n = count if count is not None else self.count
        return bytes(b for c in self.chars[:n] for b in c)

    def to_source(self, label: str = "characters", count: int | None = None) -> str:
        n = count if count is not None else self.count
        lines = [label]
        for i, c in enumerate(self.chars[:n]):
            lines.append(f"        byte " + ", ".join(f"${b:02X}" for b in c) + f" ; char {i}")
        return "\n".join(lines) + "\n"

    @classmethod
    def from_bin(cls, data: bytes, multicolour: bool = False) -> "Charset":
        cs = cls(multicolour=multicolour)
        n = min(256, len(data) // 8)
        for i in range(n):
            cs.chars[i] = list(data[i * 8:i * 8 + 8])
        cs.count = max(1, n)
        return cs

    @classmethod
    def load_cst(cls, path: str | Path) -> "Charset":
        root = ET.fromstring(Path(path).read_bytes().decode("utf-8-sig"))

        def t(tag, d=""):
            e = root.find(tag)
            return (e.text or d).strip() if e is not None and e.text else d
        cs = cls(multicolour=t("Multicolour") == "True", uppercase=t("Uppercase", "True") == "True")
        rom = rom_charset(cs.uppercase)
        if rom:
            cs.chars = rom
        # Colours are two hex digits: the high digit is the colour, the low one a luminance used by the
        # CBM prg Studio UI (always 7 in the book's files).
        cs.mc1 = int(t("BK1", "07"), 16) >> 4
        cs.mc2 = int(t("BK2", "17"), 16) >> 4
        cs.char_colour = int(t("Col3", "27"), 16) >> 4
        highest = -1
        for ch in root.findall("character"):
            code = int(ch.findtext("charcode", "0"))
            data = [int(d.text) & 0xFF for d in ch.findall("./chardata/data")]
            if 0 <= code < 256:
                cs.chars[code] = (data + [0] * 8)[:8]
                highest = max(highest, code)
        cs.count = highest + 1 if highest >= 0 else 256
        return cs

    def save_cst(self, path: str | Path) -> None:
        root = ET.Element("charset")
        ET.SubElement(root, "FileVersion").text = "2"
        ET.SubElement(root, "BK1").text = f"{self.mc1 & 15:X}7"
        ET.SubElement(root, "BK2").text = f"{self.mc2 & 15:X}7"
        ET.SubElement(root, "Col3").text = f"{self.char_colour & 15:X}7"
        ET.SubElement(root, "Reversed").text = "False"
        ET.SubElement(root, "Multicolour").text = str(self.multicolour)
        ET.SubElement(root, "Uppercase").text = str(self.uppercase)
        rom = rom_charset(self.uppercase)
        for i, c in enumerate(self.chars):
            if (rom and c == rom[i]) or (not rom and i >= self.count and not any(c)):
                continue  # unchanged ROM characters aren't stored, matching CBM prg Studio
            el = ET.SubElement(root, "character")
            ET.SubElement(el, "charcode").text = str(i)
            cd = ET.SubElement(el, "chardata")
            for b in c:
                ET.SubElement(cd, "data").text = str(b)
        ET.indent(root)
        Path(path).write_bytes(b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8"))
