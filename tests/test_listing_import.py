"""Reading character and sprite data out of listings (Import → From Listing)."""
import pytest

from l64s.gfx.listing import Block, ListingError, basic_blocks, basic_values, blocks, chars, find, sprites, values

BASIC = """10 print "chars"
20 for i=0 to 15: read a: next
100 data 60,102,110,110,96,98,60,0
110 data 24,60,102,126,102,102,102,0: rem b
120 end
200 data 1,2,3
"""

ASM = """*=$3000
; the font
font    byte %00111100,%01100110,$6e,$6e,$60,$62,$3c,0
        byte 24,60,102,126,102,102,102,0
blank   dcb 8,0
square  bits ..@@@@..
        bits .@....@.
        bits .@....@.
        bits .@....@.
        bits .@....@.
        bits .@....@.
        bits ..@@@@..
        bits ........
        rts
"""


def test_basic():
    assert [(b.name, b.line, b.count) for b in basic_blocks(BASIC)] == [("line 100", 3, 16), ("line 200", 6, 3)]
    v = basic_values(BASIC, 100)
    assert chars(v) == [[60, 102, 110, 110, 96, 98, 60, 0], [24, 60, 102, 126, 102, 102, 102, 0]]
    assert basic_values(BASIC, 105)[:2] == [24, 60]            # from the next line with DATA
    assert basic_values("10 data ,1,0.0\n", 10) == [0, 1, 0]     # empty reads as 0
    with pytest.raises(ListingError):
        basic_values("10 data 300\n", 10)
    assert find(BASIC, True, 8).name == "line 100"


def test_assembler_is_assembled():
    found = {b.name: b.count for b in blocks(ASM, False)}
    assert found["font"] >= 16 and found["square"] == 8 and found["blank"] >= 8
    font = chars(values(ASM, False, Block("font", 3, 16)), 2)
    assert font[0] == [0x3C, 0x66, 0x6E, 0x6E, 0x60, 0x62, 0x3C, 0]
    assert chars(values(ASM, False, Block("square", 6, 8)))[0] == [0x3C, 0x42, 0x42, 0x42, 0x42, 0x42, 0x3C, 0]
    assert chars(values(ASM, False, Block("blank", 5, 8)), 1) == [[0] * 8]


def test_assembler_that_doesnt_assemble_alone():
    kick = "font: .byte $3c,$66,$6e,$6e,$60,$62,$3c,$00\n      .byte $18,$3c,$66,$7e,$66,$66,$66,$00\n" \
           "      lda #EXTERNAL\n"
    assert [(b.name, b.count) for b in blocks(kick, False)] == [("font", 16)]
    assert chars(values(kick, False, Block("font", 1, 16)))[1][0] == 0x18


def test_sprites():
    v63 = list(range(63)) * 2
    assert [len(s) for s in sprites(v63)] == [63, 63] and sprites(v63)[1][0] == 0
    v64 = (list(range(63)) + [0x81]) * 3
    assert len(sprites(v64)) == 3 and sprites(v64)[2] == bytes(range(63))
    assert len(sprites(v64, 2)) == 2
