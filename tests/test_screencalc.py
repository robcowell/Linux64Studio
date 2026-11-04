import pytest

from l64s.asm.assembler import Assembler, Options
from l64s.screencalc import (Located, colour_address, locate, offset, results, screen_address, sprite_cell,
                             sprite_xy)


def test_addresses():
    assert screen_address(0, 0) == 0x0400
    assert screen_address(12, 20) == 0x0400 + 500
    assert screen_address(24, 39) == 0x07E7
    assert colour_address(24, 39) == 0xDBE7
    assert screen_address(1, 0, base=0xC000) == 0xC028
    with pytest.raises(ValueError):
        offset(25, 0)
    with pytest.raises(ValueError):
        offset(0, 40)


def test_locate():
    assert locate(0x0428) == Located("screen", 1, 0)
    assert locate(0xDBE7) == Located("colour", 24, 39)
    assert locate(0x07E8) is None                     # the byte after the screen (sprite pointers start at $07F8)
    assert locate(0x4400, screen_base=0x4400) == Located("screen", 0, 0)


def test_sprite_coordinates():
    assert sprite_xy(0, 0) == (24, 50)
    assert sprite_xy(24, 39) == (24 + 312, 50 + 192)
    assert sprite_cell(24, 50) == (0, 0)
    assert sprite_cell(31, 57) == (0, 0)
    assert sprite_cell(32, 58) == (1, 1)
    assert sprite_cell(23, 100) is None and sprite_cell(100, 250) is None
    for r, c in ((3, 7), (24, 39), (10, 0)):
        assert sprite_cell(*sprite_xy(r, c)) == (r, c)


def test_results():
    res = {r.label: r.text for r in results(1, 2, char=8, colour=7)}
    assert res["Screen address"] == "$042A  (1066)"
    assert res["Colour address"] == "$D82A  (55338)"
    assert res["BASIC"] == "poke 1066,8 : poke 55338,7"
    assert res["Expression"] == "$0400 + 1*40 + 2"
    assert "$D010" not in res["Sprite X, Y"]
    assert "$D010" in {r.label: r.text for r in results(0, 39)}["Sprite X, Y"]


@pytest.mark.parametrize("kickass", [False, True])
def test_assembler_lines_assemble(kickass):
    asm = {r.label: r.text for r in results(2, 3, char=0x51, colour=2, kickass=kickass)}["Assembler"]
    if kickass:
        assert "//" in asm
        return
    res = Assembler(Options()).assemble_text("*=$c000\n" + asm + "\n")
    assert res.ok, res.diagnostics
    assert bytes(res.memory[0xC000:0xC00A]) == bytes([0xA9, 0x51, 0x8D, 0x53, 0x04, 0xA9, 0x02, 0x8D, 0x53, 0xD8])


def test_expression_evaluates_to_the_address():
    expr = {r.label: r.text for r in results(7, 11, screen_base=0x4800)}["Expression"]
    res = Assembler(Options()).assemble_text(f"*=$c000\n        word {expr}\n")
    assert res.ok
    assert res.memory[0xC000] | res.memory[0xC001] << 8 == screen_address(7, 11, 0x4800)
