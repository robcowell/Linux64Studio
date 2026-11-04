import os
import shutil
import time
from pathlib import Path

import pytest

from l64s import memmap
from l64s.asm.assembler import Assembler
from l64s.vicmem import Layout, check, setup_code


def test_book_chapter17_layout():
    lay = Layout(bank=0, screen=1, charset=7, sprites=[192])
    assert (lay.screen_addr, lay.charset_addr, lay.sprite_pointers_addr) == (0x0400, 0x3800, 0x07F8)
    assert lay.d018 == 0x1E and lay.dd00_bits == 3
    assert lay.book_charmemory_value == 14            # LIBSCREEN_SETCHARMEMORY 14
    assert lay.sprite_addr(192) == 0x3000 and lay.pointer_for(0x3000) == 192


def test_from_registers():
    lay = Layout.from_registers(0x97, 0x1F, 0x1B, [192, 204, 207, 0, 0, 0, 0, 0], 0x07)
    assert (lay.bank, lay.screen_addr, lay.charset_addr, lay.sprites) == (0, 0x0400, 0x3800, [192, 204, 207])
    bm = Layout.from_registers(0x94, 0x38, 0x3B)
    assert bm.bitmap_mode and bm.bank == 3 and bm.bitmap_addr == 0xE000 and bm.screen_addr == 0xCC00


def test_pointer_errors():
    lay = Layout(bank=1)
    with pytest.raises(ValueError, match="bank 1"):
        lay.pointer_for(0x3000)
    with pytest.raises(ValueError, match="64-byte"):
        lay.pointer_for(0x4010)


def test_rom_charset_and_shadow_warnings():
    assert Layout(bank=0, charset=2).uses_rom_charset()            # $1000: the ROM's upper case
    assert not Layout(bank=1, charset=2).uses_rom_charset()
    issues = check(Layout(bank=0, screen=4, charset=7, sprites=[70]))   # screen $1000, sprite $1180
    msgs = " ".join(i.message for i in issues)
    assert "Screen ($1000)" in msgs and "Sprite 70" in msgs and "character ROM" in msgs
    assert any("has no character ROM" in i.message for i in check(Layout(bank=1, charset=2)))


def test_overlaps_and_io_note():
    msgs = [i.message for i in check(Layout(bank=0, screen=14, charset=7))]   # screen $3800 = charset
    assert any("overlaps Character set" in m for m in msgs)
    assert any("I/O area" in i.message for i in check(Layout(bank=3, screen=4)))   # $D000


def test_overlap_with_program(tmp_path):
    (tmp_path / "chars.bin").write_bytes(bytes(2048))
    (tmp_path / "m.asm").write_text("*=$0800\n rts\n*=$3800\n incbin chars.bin\n*=$0400\n lda #1\n")
    r = Assembler().assemble_files([tmp_path / "m.asm"])
    issues = check(Layout(bank=0, screen=1, charset=7), memmap.from_build(r))
    assert any(i.severity == "warning" and "overlaps code from m.asm" in i.message for i in issues)
    assert any(i.severity == "note" and "Character set holds an included binary" in i.message for i in issues)


def test_setup_code_assembles(tmp_path):
    lay = Layout(bank=1, screen=3, charset=6, sprites=[0, 5])
    src = "*=$c000\n" + setup_code(lay)
    r = Assembler().assemble_text(src, str(tmp_path / "s.asm"))
    assert r.ok, r.errors
    assert r.symbols["screenram"] == 0x4C00 and r.symbols["charset"] == 0x7000 and r.symbols["spriteptrs"] == 0x4FF8
    code = r.binary()
    assert bytes([0x09, 0b10]) in code and bytes([0xA9, lay.d018]) in code      # ora #%10, lda #d018
    ka = setup_code(Layout(bitmap_mode=True, bank=3, screen=3, bitmap=1), kickass=True)
    assert ".const BITMAP = $E000" in ka and "bitmap mode on" in ka


@pytest.mark.skipif(not (os.environ.get("L64S_VICE_TESTS") and shutil.which("x64sc")),
                    reason="set L64S_VICE_TESTS=1 to run against VICE (opens emulator windows)")
def test_setup_code_sets_the_layout_on_a_real_c64(tmp_path):
    from l64s.emu import vice
    from l64s.emu.binmon import BinaryMonitor
    want = Layout(bank=2, screen=5, charset=3)
    src = ("*=$0801\n byte $0B,$08,$0A,$00,$9E,$32,$30,$36,$31,$00,$00,$00\n sei\n" + setup_code(want)
           + "loop jmp loop\n")
    r = Assembler().assemble_text(src, str(tmp_path / "v.asm"))
    (tmp_path / "v.prg").write_bytes(r.prg())
    port = vice.free_port()
    p = vice.launch(tmp_path / "v.prg", monitor_port=port, extra_args=["+sound", "-warp"])
    try:
        assert vice.wait_for_port(port)
        m = BinaryMonitor()
        m.connect(port=port)
        m.resume()
        time.sleep(3)
        m.ping()
        got = Layout.from_registers(m.read_memory(0xDD00, 0xDD00)[0], m.read_memory(0xD018, 0xD018)[0])
        m.quit()
        m.close()
    finally:
        p.terminate()
    assert (got.bank, got.screen_addr, got.charset_addr) == (2, 0x9400, 0x9800)
