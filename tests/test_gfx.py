import os
from pathlib import Path

import pytest

from l64s.gfx.charset import Charset
from l64s.gfx.screen import ScreenSet
from l64s.gfx.sprite import Sprite, SpriteSet

BOOK = Path(os.environ.get("L64S_BOOK", Path(__file__).parent / "book" / "c64edition-main"))
CH17 = BOOK / "Chapters" / "chapter17"
needs_book = pytest.mark.skipif(not CH17.is_dir(), reason="book sources not present")


def test_sprite_pixels_hires_and_multicolour():
    s = Sprite()
    s.set(0, 0, 1)
    s.set(23, 20, 1)
    assert s.rows[0] == 0x800000 and s.rows[20] == 1
    m = Sprite(multi=True)
    m.set(0, 0, 3)
    m.set(11, 1, 2)
    assert m.rows[0] == 0xC00000 and m.rows[1] == 0b10
    assert m.get(0, 0) == 3 and m.get(11, 1) == 2


def test_sprite_flip_and_shift():
    s = Sprite()
    s.set(0, 0, 1)
    s.flip_x()
    assert s.get(23, 0) == 1
    s.flip_y()
    assert s.get(23, 20) == 1
    s.shift(1, 1)
    assert s.get(0, 0) == 1


def test_charset_pixels():
    c = Charset()
    c.set(1, 0, 0, 1)
    assert c.chars[1][0] == 0x80
    c.multicolour = True
    c.set(1, 3, 1, 2)
    assert c.chars[1][1] == 0b10


@needs_book
def test_spt_matches_books_sprites_bin(tmp_path):
    ss = SpriteSet.load_spt(CH17 / "sprites.spt")
    assert ss.to_bin() == (CH17 / "sprites.bin").read_bytes()
    ss.save_spt(tmp_path / "s.spt")
    assert SpriteSet.load_spt(tmp_path / "s.spt").to_bin() == ss.to_bin()


@needs_book
def test_cst_matches_books_characters_bin(tmp_path):
    cs = Charset.load_cst(CH17 / "characters.cst")
    gold = (CH17 / "characters.bin").read_bytes()
    assert cs.to_bin(len(gold) // 8) == gold
    # Chapter 17 sets multicolour 1 = Black, multicolour 2 = Brown; the grass characters are green.
    assert (cs.mc1, cs.mc2, cs.char_colour) == (0, 9, 5)
    cs.save_cst(tmp_path / "c.cst")
    again = Charset.load_cst(tmp_path / "c.cst")
    assert again.to_bin(len(gold) // 8) == gold
    assert (again.mc1, again.mc2, again.char_colour) == (0, 9, 5)


@needs_book
def test_sdd_roundtrip(tmp_path):
    ss = ScreenSet.load_sdd(CH17 / "screens.sdd")
    assert len(ss.screens) == 6
    ss.save_sdd(tmp_path / "s.sdd")
    again = ScreenSet.load_sdd(tmp_path / "s.sdd")
    assert again.export_chars() == ss.export_chars()
    assert again.export_colours() == ss.export_colours()
    # The book's map is 6 screens side by side, 16 rows (3840 bytes).
    assert len(ss.export_chars(2, 17, side_by_side=True)) == len((CH17 / "screens.bin").read_bytes())
