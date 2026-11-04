"""SpritePad (.spd) and CharPad (.ctm) support, checked against Retro Game Dev Vol 2's own exports.

Point L64S_BOOK2 at the unzipped c64editionvol2-main folder, or unzip it into tests/book/.
"""
import os
from pathlib import Path

import pytest

from l64s.gfx.charpad import (COLOUR_PER_CHAR, COLOUR_PER_TILE, CharPadError, CharPadProject, load_ctm,
                              save_ctm)
from l64s.gfx.charset import Charset
from l64s.gfx.sprite import Sprite, SpriteSet
from l64s.gfx.spritepad import SpritePadError, load_spd, save_spd
from l64s.project.model import load_project

BOOK2 = Path(os.environ.get("L64S_BOOK2", Path(__file__).parent / "book" / "c64editionvol2-main"))
CONTENT = BOOK2 / "Chapters" / "Content"
needs_book2 = pytest.mark.skipif(not CONTENT.is_dir(), reason=f"Vol 2 sources not found at {BOOK2}")


# ------------------------------------------------------------------ synthetic

def test_spd_roundtrip(tmp_path):
    s = Sprite(multi=True, colour=14, attr_extra=0x10)
    s.set(0, 0, 3)
    ss = SpriteSet([s, Sprite(colour=2)], background=7, mcolour1=10, mcolour2=9, attribute_bytes=True)
    save_spd(ss, tmp_path / "a.spd")
    raw = (tmp_path / "a.spd").read_bytes()
    assert raw[:9] == b"SPD\x01\x01\x00\x07\x0a\x09"
    assert raw[9 + 63] == 0x80 | 0x10 | 14     # attribute byte: multicolour, kept bit, colour
    back = load_spd(tmp_path / "a.spd")
    assert back.to_bin() == ss.to_bin()
    assert back.sprites[0].multi and back.sprites[0].colour == 14 and not back.sprites[1].multi
    # SpritePad exports keep the attribute byte; CBM prg Studio-style exports pad with 0.
    assert back.to_bin()[63] == 0x9E and back.to_bin(attribute_bytes=False)[63] == 0


def test_spd_rejects_other_files(tmp_path):
    (tmp_path / "x.spd").write_bytes(b"NOPE" + bytes(100))
    with pytest.raises(SpritePadError):
        load_spd(tmp_path / "x.spd")
    (tmp_path / "y.spd").write_bytes(b"SPD\x03" + bytes(100))
    with pytest.raises(SpritePadError, match="version 3"):
        load_spd(tmp_path / "y.spd")


def _charpad(tiles=False, method=COLOUR_PER_CHAR) -> CharPadProject:
    cs = Charset(multicolour=True, background=6, mc1=0, mc2=9, char_colour=5, count=4)
    cs.chars[1] = [0xFF] * 8
    cs.attribs = [8 + (i % 8) for i in range(256)]
    if tiles:
        return CharPadProject(cs, colour_method=method, tiles_enabled=True, tile_count=2, tile_width=2,
                              tile_height=2, tile_data=[0, 1, 2, 3, 3, 2, 1, 0], tile_colours=bytes([3, 4]),
                              map_width=3, map_height=1, map_data=[0, 1, 0])
    return CharPadProject(cs, colour_method=method, map_width=4, map_height=2, map_data=[0, 1, 2, 3, 3, 2, 1, 0])


@pytest.mark.parametrize("tiles,method", [(False, COLOUR_PER_CHAR), (True, COLOUR_PER_TILE), (True, 0)])
def test_ctm_roundtrip(tmp_path, tiles, method):
    p = _charpad(tiles, method)
    save_ctm(p, tmp_path / "a.ctm")
    raw = (tmp_path / "a.ctm").read_bytes()
    back = load_ctm(tmp_path / "a.ctm")
    save_ctm(back, tmp_path / "b.ctm")
    assert (tmp_path / "b.ctm").read_bytes() == raw
    assert back.export_charset() == p.export_charset()
    assert back.export_map() == p.export_map()


def test_ctm_map_editing_and_tile_expansion():
    p = _charpad()
    ss = p.to_screenset()
    assert (ss.cols, ss.rows) == (4, 2)
    ss.screens[0].chars[1][3] = 2
    p.update_map_from(ss)
    assert p.map_data[-1] == 2
    t = _charpad(tiles=True, method=COLOUR_PER_TILE)
    ts = t.to_screenset()
    assert (ts.cols, ts.rows) == (6, 2)              # 3 tiles of 2x2
    assert ts.screens[0].chars[0][:4] == [0, 1, 3, 2]
    assert ts.screens[0].colours[0][2] == 4          # colour of tile 1
    assert not t.map_editable


def test_ctm_rejects_old_versions(tmp_path):
    (tmp_path / "x.ctm").write_bytes(b"CTM\x04" + bytes(40))
    with pytest.raises(CharPadError, match="version 4"):
        load_ctm(tmp_path / "x.ctm")


# ------------------------------------------------------------------ the book's files

@needs_book2
@pytest.mark.parametrize("n", range(1, 7))
def test_book_spd_exports_match(n, tmp_path):
    spd = CONTENT / f"BeachBarSprites{n}.spd"
    ss = load_spd(spd)
    assert ss.to_bin() == (CONTENT / f"BeachBarSprites{n}.bin").read_bytes()
    save_spd(ss, tmp_path / "x.spd")
    assert (tmp_path / "x.spd").read_bytes() == spd.read_bytes()


@needs_book2
def test_book_ctm_exports_match(tmp_path):
    p = load_ctm(CONTENT / "BeachBarScreens.ctm")
    assert p.export_charset() == (CONTENT / "BeachBarScreensCharset.bin").read_bytes()
    assert p.export_attribs() == (CONTENT / "BeachBarScreensColors.bin").read_bytes()
    assert p.export_map() == (CONTENT / "BeachBarScreenTopLeft.bin").read_bytes()
    save_ctm(p, tmp_path / "x.ctm")
    assert (tmp_path / "x.ctm").read_bytes() == (CONTENT / "BeachBarScreens.ctm").read_bytes()


@needs_book2
def test_every_ctm_and_spd_in_the_download_roundtrips(tmp_path):
    count = 0
    for f in sorted(BOOK2.rglob("*")):
        sfx = f.suffix.lower()
        if sfx == ".ctm":
            save_ctm(load_ctm(f), tmp_path / "x")
        elif sfx == ".spd":
            save_spd(load_spd(f), tmp_path / "x")
        else:
            continue
        assert (tmp_path / "x").read_bytes() == f.read_bytes(), f
        count += 1
    assert count > 200


@needs_book2
def test_workspace_project_lists_content_folder():
    proj = load_project(BOOK2 / "Chapters" / "Chapter13" / "Ch13.code-workspace")
    names = {f.name for f in proj.all_files()}
    assert {"BeachBarScreens.ctm", "BeachBarSprites1.spd", "BeachBarSprites1.bin"} <= names
    assert not any(n.startswith(".") for n in names)


@needs_book2
def test_linked_export_detection():
    from l64s.ui.exports import detect_link
    p = load_ctm(CONTENT / "BeachBarScreens.ctm")
    src = CONTENT / "BeachBarScreens.ctm"
    assert detect_link(src, "BeachBarScreensCharset.bin", p.export_charset()).name == "BeachBarScreensCharset.bin"
    # The map has no default-named export, but its bytes match BeachBarScreenTopLeft.bin.
    assert detect_link(src, "BeachBarScreensMap.bin", p.export_map()).name == "BeachBarScreenTopLeft.bin"
    # Nothing matches changed data, so nothing would be overwritten by default.
    assert detect_link(src, "BeachBarScreensMap.bin", bytes(1000 * [7])) is None
