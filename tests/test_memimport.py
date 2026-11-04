"""Importing characters and sprites from memory or a file."""
import pytest

from l64s.gfx import memimport as mi


def test_addresses():
    assert mi.charset_address(1, 1) == 0x4800 and mi.charset_address(3, 7) == 0xF800
    assert mi.sprite_address(1, 0x40) == 0x5000 and mi.sprite_address(0, 13) == 13 * 64
    assert mi.rom_shadow(0, 2) and mi.rom_shadow(2, 3) and not mi.rom_shadow(1, 2)


def test_build_memory():
    data = bytearray(0x10000)
    data[0x4800:0x4810] = bytes(range(16))
    data[0x5000:0x5040] = bytes(range(63)) + b"\x81"
    data[0x5040:0x5080] = bytes(range(100, 163)) + b"\x00"
    mem = mi.from_bytes(data, "the build")
    assert mi.chars(mem, 0x4800, 2) == [list(range(8)), list(range(8, 16))]
    s = mi.sprites(mem, 0x5000, 2)
    assert s == [bytes(range(63)), bytes(range(100, 163))]        # 64 apart, the 64th byte left out
    assert len(mi.chars(mem, 0xFFF8, 5)) == 1                      # stops at the end of memory


def test_files(tmp_path):
    prg = tmp_path / "font.prg"
    prg.write_bytes(b"\x00\x30" + bytes(range(16)))
    mem = mi.from_file(prg)
    assert mi.chars(mem, 0x3008, 1) == [list(range(8, 16))] and "$3000-$300F" in mem.what
    with pytest.raises(mi.MemoryImportError, match="Nothing is at"):
        mi.chars(mem, 0x4000, 1)
    assert len(mi.chars(mem, 0x3000, 128)) == 2                   # only as far as the file goes
    raw = tmp_path / "font.bin"
    raw.write_bytes(bytes(range(16)))
    assert mi.chars(mi.from_file(raw), 8, 1) == [list(range(8, 16))]
    assert mi.chars(mi.from_file(raw, load_address=True), 0x0100, 1) == [list(range(2, 10))]


def test_rom():
    try:
        mem = mi.rom_charset(True)
    except mi.MemoryImportError:
        pytest.skip("no character ROM")
    at = mi.chars(mem, 1 * 8, 1)[0]                               # 'A' in the upper-case set
    assert at[0] == 0x18 and mem.what.endswith("(upper case)")
