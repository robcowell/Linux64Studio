"""Read CBM prg Studio .cbmprj project files."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# <FileType> values seen in CBM prg Studio projects.
FILE_TYPES = {2: "asm", 6: "charset", 7: "sprites", 9: "screen"}


@dataclass
class CbmSourceFile:
    name: str
    file_type: int
    include_in_build: bool

    @property
    def kind(self) -> str:
        return FILE_TYPES.get(self.file_type, "other")


@dataclass
class CbmProject:
    path: Path
    executable: str
    start_address: int
    build_list: list[str]
    files: list[CbmSourceFile] = field(default_factory=list)
    padding_byte: int = 0
    target: int = 2
    cart_type: str = ""   # from the <Cartridge> section, when CrtBuildingCartridge is True
    cart_name: str = ""

    @property
    def directory(self) -> Path:
        return self.path.parent

    def build_paths(self) -> list[Path]:
        return [self.directory / n for n in self.build_list]


def _text(root: ET.Element, tag: str, default: str = "") -> str:
    el = root.find(tag)
    return (el.text or default).strip() if el is not None and el.text else default


def load_cbmprj(path: str | Path) -> CbmProject:
    path = Path(path)
    root = ET.fromstring(path.read_bytes().decode("utf-8-sig"))
    build_list = [el.text.strip() for el in root.findall("./BuildList/FileName") if el.text]
    files = []
    for sf in root.findall("./SourceFiles/SourceFile"):
        files.append(CbmSourceFile(
            name=_text(sf, "Name"),
            file_type=int(_text(sf, "FileType", "0") or 0),
            include_in_build=_text(sf, "IncludeInBuild", "True").lower() == "true",
        ))
    if not build_list:
        build_list = [f.name for f in files if f.kind == "asm" and f.include_in_build]
    cart_type, cart_name = "", ""
    cart = root.find("Cartridge")
    if cart is not None and _text(cart, "CrtBuildingCartridge").lower() == "true":
        # Generic cartridges: the EXROM/GAME lines say which kind (active = pulled low).
        if (_text(cart, "CrtCartType", "0") or "0") == "0":
            exrom = _text(cart, "CrtEXROMActive").lower() == "true"
            game = _text(cart, "CrtGAMEActive").lower() == "true"
            cart_type = {(True, False): "normal8", (True, True): "normal16", (False, True): "ultimax"}.get(
                (exrom, game), "")
        cart_name = _text(cart, "CrtName")
    return CbmProject(
        path=path,
        executable=_text(root, "Executable", path.stem + ".prg"),
        start_address=int(_text(root, "StartAddress", "2049") or 2049),
        build_list=build_list,
        files=files,
        padding_byte=int(_text(root, "PaddingByte", "0") or 0),
        target=int(_text(root, "Target", "2") or 2),
        cart_type=cart_type, cart_name=cart_name,
    )
