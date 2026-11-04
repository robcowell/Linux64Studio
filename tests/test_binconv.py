import os
import shutil
import time
from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler
from l64s.basic.tokenizer import detokenize, tokenize
from l64s.binconv import (Binary, ConvertError, basic_sys_address, disassemble_to_source, export_range,
                          load_binary, to_asm_data, to_basic_data)

BOOK = Path(__file__).parent / "book"
PRGS = sorted(BOOK.rglob("prgs/*.prg"))


def reassemble(source: str, tmp_path) -> tuple[int, bytes]:
    r = Assembler().assemble_text(source, str(tmp_path / "re.asm"))
    assert r.ok, [str(e) for e in r.errors[:5]]
    return r.start, r.binary()


@pytest.mark.skipif(not PRGS, reason="book downloads not present")
@pytest.mark.parametrize("prg", PRGS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_book_programs_disassemble_and_reassemble_identically(prg, tmp_path):
    b = load_binary(prg)
    sys_addr = basic_sys_address(b)
    for entries in (None, [sys_addr]):
        d = disassemble_to_source(b, entries)
        assert reassemble(d.source, tmp_path) == (b.start, b.data)
    assert d.code_bytes > 0 and d.data_bytes > 0


def test_zero_page_with_absolute_addressing_is_kept_as_bytes(tmp_path):
    b = Binary(0xC000, bytes([0xAD, 0x10, 0x00, 0xA5, 0x10, 0x8D, 0x20, 0xD0, 0x60]))
    d = disassemble_to_source(b)
    assert "byte $AD, $10, $00   ; lda $0010 (absolute)" in d.source
    assert "lda $10" in d.source and "sta $D020" in d.source
    assert reassemble(d.source, tmp_path) == (0xC000, b.data)


def test_undocumented_opcodes_and_labels(tmp_path):
    # $C000: lda #0 / $C002: illegal $02 / $C003: inc $C007 (self-modifying: label+1) / bne $C000
    code = bytes([0xA9, 0x00, 0x02, 0xEE, 0x08, 0xC0, 0xD0, 0xF8, 0xAD, 0x34, 0x12])
    b = Binary(0xC000, code)
    d = disassemble_to_source(b)
    assert "LC000" in d.source and "byte $02" in d.source
    assert "inc LC008+0" not in d.source and ("inc LC008" in d.source or "inc LC007+1" in d.source)
    assert reassemble(d.source, tmp_path) == (0xC000, code)


def test_tracing_separates_code_from_data(tmp_path):
    # jmp over a table: only the jmp and the code after the table are code
    code = bytes([0x4C, 0x07, 0xC0, 0xA9, 0xEA, 0xEA, 0xEA, 0xA9, 0x01, 0x60])
    b = Binary(0xC000, code)
    d = disassemble_to_source(b, [0xC000])
    assert d.code_bytes == 6 and d.data_bytes == 4
    assert "jmp LC007" in d.source and "LC007   lda #$01" in d.source
    assert reassemble(d.source, tmp_path) == (0xC000, code)


def test_basic_sys_address():
    stub = bytes([0x0E, 0x08, 0x0A, 0x00, 0x9E, 0x20, 0x28, 0x32, 0x30, 0x36, 0x34, 0x29, 0, 0, 0])
    assert basic_sys_address(Binary(0x0801, stub)) == 2064
    assert basic_sys_address(Binary(0xC000, stub)) is None


def test_asm_data(tmp_path):
    b = Binary(0x3000, bytes(range(20)), "x.bin")
    src = to_asm_data(b, "tbl", per_line=8)
    assert sum(1 for ln in src.splitlines() if ln.strip().startswith("byte ")) == 3 and "tbl" in src
    r = Assembler().assemble_text(src, str(tmp_path / "d.asm"))
    assert r.ok and r.binary() == b.data and r.symbols["tbl"] == 0x3000
    assert "%00000001" in to_asm_data(b, radix="bin") and ", 19" in to_asm_data(b, radix="dec")
    ka = to_asm_data(b, "tbl", kickass=True)
    assert "*= $3000" in ka and "tbl:" in ka and ".byte" in ka


def test_basic_data_tokenizes():
    b = Binary(49152, bytes([1, 2, 255, 0]))
    src = to_basic_data(b, 1000, 10, 3)
    assert src.splitlines()[0] == "10 for i=49152 to 49155:read v:poke i,v:next"
    listed = detokenize(tokenize(src).prg())
    assert "1000 data 1,2,255" in listed and "1010 data 0" in listed
    with pytest.raises(ConvertError):
        to_basic_data(b, 5, 10, 3, loader=True)


def test_load_and_export(tmp_path):
    (tmp_path / "a.prg").write_bytes(b"\x00\xc0" + bytes(range(10)))
    b = load_binary(tmp_path / "a.prg", skip=2, length=3)
    assert (b.start, b.data) == (0xC002, bytes([2, 3, 4]))
    (tmp_path / "raw.bin").write_bytes(bytes(5))
    with pytest.raises(ConvertError, match="load address"):
        load_binary(tmp_path / "raw.bin")
    assert load_binary(tmp_path / "raw.bin", 0x2000).start == 0x2000
    mem = bytearray(0x10000)
    mem[0x3000:0x3004] = b"\x01\x02\x03\x04"
    assert export_range(mem, 0x3000, 0x3003, prg=False) == b"\x01\x02\x03\x04"
    assert export_range(mem, 0x3000, 0x3001, prg=True) == b"\x00\x30\x01\x02"
    with pytest.raises(ConvertError):
        export_range(mem, 0x3001, 0x3000, prg=False)


def test_l64bin_cli(tmp_path, capsys):
    from l64s.bincli import main
    (tmp_path / "a.prg").write_bytes(b"\x00\xc0\xa9\x01\x60")
    assert main(["import", str(tmp_path / "a.prg")]) == 0
    assert "lda #$01" in capsys.readouterr().out
    assert main(["export", str(tmp_path / "a.prg"), "--from", "c000", "--to", "c001", "-o", str(tmp_path / "o.bin")]) == 0
    assert (tmp_path / "o.bin").read_bytes() == b"\xa9\x01"
    assert main(["import", str(tmp_path / "a.prg"), "--as", "basic"]) == 0
    assert "data 169,1,96" in capsys.readouterr().out


@pytest.mark.skipif(not (os.environ.get("L64S_VICE_TESTS") and shutil.which("x64sc")),
                    reason="set L64S_VICE_TESTS=1 to run against VICE (opens emulator windows)")
def test_basic_loader_pokes_the_bytes_on_a_real_c64(tmp_path):
    from l64s.emu import vice
    from l64s.emu.binmon import BinaryMonitor
    data = bytes((i * 37 + 11) & 0xFF for i in range(100))
    src = to_basic_data(Binary(49152, data)) + "9000 goto 9000\n"
    prg = tmp_path / "loader.prg"
    prg.write_bytes(tokenize(src).prg())
    port = vice.free_port()
    p = vice.launch(prg, monitor_port=port, extra_args=["+sound", "-warp"])
    try:
        assert vice.wait_for_port(port)
        m = BinaryMonitor()
        m.connect(port=port)
        m.resume()
        time.sleep(5)
        m.ping()
        got = m.read_memory(49152, 49152 + len(data) - 1)
        m.quit()
        m.close()
    finally:
        p.terminate()
    assert got == data
