import pytest

from l64s.gfx.charpad import CharPadError, from_binaries, load_ctm, save_ctm
from l64s.ui.charpad_import import guess_files

CHARS = bytes(range(256)) * 8                  # 256 characters
ATTRIBS = bytes([0x10 | 5] * 128 + [0x23] * 128)  # material 1 colour 5, then material 2 colour 3
TILES = bytes([32, 32, 32, 32, 128, 129, 130, 131, 200, 200, 201, 201])   # 3 tiles of 2x2
MAP = bytes([0, 1, 2, 1] * 6)                 # 4 x 6 tiles


def project():
    return from_binaries(CHARS, ATTRIBS, TILES, MAP, map_width=4)


def test_from_binaries():
    p = project()
    assert (p.charset.count, p.tile_count, p.map_width, p.map_height) == (256, 3, 4, 6)
    assert p.tiles_enabled and not p.char_expanded
    assert p.tile_cells(1) == [128, 129, 130, 131]
    assert p.charset.colour_of(0) == 5 and p.charset.material_of(0) == 1 and p.charset.material_of(200) == 2


def test_exports_are_the_files(tmp_path):
    p = project()
    save_ctm(p, tmp_path / "rooms.ctm")
    q = load_ctm(tmp_path / "rooms.ctm")
    assert q.export_charset() == CHARS and q.export_attribs() == ATTRIBS
    assert q.export_tiles() == TILES and q.export_map() == MAP


def test_editing():
    p = project()
    p.set_tile_at(3, 5, 2)
    assert p.tile_at(3, 5) == 2 and p.export_map()[23] == 2
    p.set_tile_cell(0, 3, 65)
    assert p.tile_cells(0) == [32, 32, 32, 65]
    t = p.add_tile(1)
    assert t == 3 and p.tile_cells(3) == [128, 129, 130, 131] and len(p.export_tiles()) == 16
    assert p.tile_uses()[:3] == [6, 11, 7] and p.tile_uses()[3] == 0     # one 1 became a 2 above
    with pytest.raises(CharPadError):
        p.set_tile_at(0, 0, 9)


def test_material_keeps_colour():
    p = project()
    p.charset.set_material_of(0, 4)
    assert p.charset.material_of(0) == 4 and p.charset.colour_of(0) == 5
    p.charset.set_colour_of(0, 7)
    assert p.charset.material_of(0) == 4 and p.export_attribs()[0] == 0x47


@pytest.mark.parametrize("args, match", [
    ((CHARS[:-1], ATTRIBS, TILES, MAP, 4), "8 bytes"),
    ((CHARS, ATTRIBS[:-1], TILES, MAP, 4), "one byte a character"),
    ((CHARS, ATTRIBS, TILES[:-1], MAP, 4), "whole 2x2 tiles"),
    ((CHARS, ATTRIBS, TILES, MAP, 5), "whole rows"),
    ((CHARS, ATTRIBS, TILES, bytes([0, 3, 0, 0]), 4), "tile 3"),
])
def test_bad_binaries(args, match):
    with pytest.raises(CharPadError, match=match):
        from_binaries(*args)


def test_guess_files(tmp_path):
    for name in ("chars.bin", "attribs.bin", "tiles.bin", "map.bin", "sprites.bin"):
        (tmp_path / name).write_bytes(b"x")
    g = guess_files(tmp_path)
    assert {k: v.name for k, v in g.items()} == {"charset": "chars.bin", "attribs": "attribs.bin",
                                                 "tiles": "tiles.bin", "map": "map.bin"}
    (tmp_path / "attribs.bin").unlink()
    (tmp_path / "levelColours.bin").write_bytes(b"x")
    assert guess_files(tmp_path)["attribs"].name == "levelColours.bin"
