import pytest

from l64s.emu.values import ValueError_, flags_text, is_io, parse_address, parse_bytes, parse_number, parse_register

SYMS = {"gMLoop": 0x0888, "SCREENRAM": 0x0400, "@local__m3": 0x1234}


@pytest.mark.parametrize("text,value", [
    ("$FF", 255), ("ff", 255), ("0400", 0x400), ("0x10", 16), ("%101", 5), ("#12", 12), ("12.", 12),
    ("gMLoop", 0x888), ("gmloop", 0x888), ("SCREENRAM+$28", 0x428), ("screenram + 40", 0x440),
    ("gMLoop-#2", 0x886), ("  $d020 ", 0xD020),
])
def test_parse_number(text, value):
    assert parse_number(text, SYMS) == value


@pytest.mark.parametrize("bad", ["", "nothere", "$zz", "%102", "#1a"])
def test_parse_number_errors(bad):
    with pytest.raises(ValueError_):
        parse_number(bad, SYMS)


def test_registers_and_addresses():
    assert parse_register("PC", "gMLoop", SYMS) == 0x888
    assert parse_register("A", "$7f") == 0x7F
    with pytest.raises(ValueError_, match=r"\$00-\$FF"):
        parse_register("X", "100")
    with pytest.raises(ValueError_):
        parse_register("PC", "10000")
    with pytest.raises(ValueError_):
        parse_address("SCREENRAM+$FFFF", SYMS)


def test_parse_bytes():
    assert parse_bytes("a9 00 8d 20 d0") == bytes([0xA9, 0, 0x8D, 0x20, 0xD0])
    assert parse_bytes("$01,%10,#3") == b"\x01\x02\x03"
    assert parse_bytes("<gMLoop >gMLoop", SYMS) == b"\x88\x08"
    assert parse_bytes('"hi" 0') == b"\x08\x09\x00"          # screen codes
    assert parse_bytes("'hi'") == b"\x48\x49"                 # PETSCII
    with pytest.raises(ValueError_, match="fit in a byte"):
        parse_bytes("gMLoop", SYMS)
    with pytest.raises(ValueError_):
        parse_bytes("   ")


def test_flags_and_io():
    assert flags_text(0b10100011) == "N.-...ZC"
    assert is_io(0xD020) and not is_io(0xC000) and is_io(0xCFFF, 2) and not is_io(0xE000)
