"""CBM prg Studio's directives and dialect details, following its help (the examples are its own)."""
import os
import time
from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler, Options


def asm(src: str, start: int = 0xC000):
    r = Assembler(Options()).assemble_text(f"*=${start:04x}\n" + src + "\n")
    return r


def code(src: str) -> bytes:
    r = asm(src)
    assert r.ok, [str(d) for d in r.diagnostics]
    return bytes(r.memory[0xC000:r.end])


def errors(src: str) -> list[str]:
    return [d.message for d in asm(src).diagnostics if d.severity == "error"]


def warnings(src: str) -> list[str]:
    return [d.message for d in asm(src).diagnostics if d.severity == "warning"]


# ---------------------------------------------------------------------- numbers and operators
def test_literals():
    assert code("        byte @17, `a`, 'a'") == bytes([0o17, 1, 1])
    assert code('v = "a"\n        byte v') == b"a"                  # "a" is ASCII
    assert code("        byte 2^3, 2^3^2 & $ff") == bytes([8, 0])  # ^ is a power, grouping to the right


def test_word_operators():
    assert code("        byte 7 mod 3, 6 and 3, 6 or 1, 6 xor 3, not 0, not 5, 1 << 3, 16 >> 2") == \
        bytes([1, 2, 7, 5, 1, 0, 8, 4])
    assert code("        byte 7 MOD 3, 6 XOR 3") == bytes([1, 5])
    assert code("notes   = 3\n        byte notes") == bytes([3])       # a name starting "not" is a name


def test_empty_macro_parameter_is_zero():
    assert code("        defm m\n        byte /1,/2,/3\n        endm\n        m 1,,3") == bytes([1, 0, 3])


# ---------------------------------------------------------------------- data
def test_dcb_and_dcw_repeat_a_list():
    assert code("        dcb 5,1,2,3,4") == bytes([1, 2, 3, 4]) * 5
    assert code("        dcb 3,$ea") == bytes([0xEA]) * 3
    assert code("        dcw 2,$1234,1") == bytes([0x34, 0x12, 1, 0]) * 2


def test_bits():
    assert code("        bits 0000010010010001") == bytes([0x04, 0x91])
    assert code("        bits ........@@@@@@@@........") == bytes([0, 0xFF, 0])
    assert code("        bits 101") == bytes([5])                   # padded on the left


def test_bytes_and_words():
    assert code("var1 = 5\n        bytes 2,4*var1, var1*2") == bytes([0, 0, 4, 4, 4, 4, 4, 5, 5])
    assert code("        words 1, $1234*2") == bytes([0, 0, 0x34, 0x12, 0x34, 0x12])


def test_null_and_ptext():
    assert code('        null "hi"') == b"HI\x00"
    assert code("        ptext 'hi'") == bytes([2, 8, 9])
    assert errors("        null 'a','b'")


def test_long_is_65816_only():
    assert any("65816" in e for e in errors("        long 1"))


def test_func():
    assert code("        func 1,10,1,x*5") == bytes(range(5, 51, 5))
    assert code("        funcw 0,2,1,x*1000") == bytes([0, 0, 0xE8, 3, 0xD0, 7])
    assert code("        func 0,3,1,max(x,2)") == bytes([2, 2, 2, 3])
    assert errors("        func 1,300,1,x")                          # 256-300 don't fit a byte


def test_random():
    a, b = code("        random 16,1,6,99"), code("        random 16,1,6,99")
    assert a == b and all(1 <= v <= 6 for v in a)                    # a seed gives the same values
    w = code("        randomw 4,1000,2000,7")
    assert all(1000 <= w[i] | w[i + 1] << 8 <= 2000 for i in range(0, 8, 2))
    assert errors("        random 4,9,1")


# ---------------------------------------------------------------------- text
def test_charset():
    assert code("        text 'Ab'") == bytes([1, 2])                # set 1 (the default): both cases are 1-26
    assert code("        charset 2\n        text 'Ab'") == bytes([65, 2])
    assert code("        charset 2\n        byte 'A'") == bytes([65])


def test_charmap():
    assert code("        charmap a,3,5\n        text \"a\",'a'") == bytes([3, 5])
    assert code("        charmap a,3,5\n        charmap off\n        text 'a'") == bytes([1])


# ---------------------------------------------------------------------- program layout
def test_relocate():
    # the help's example: labels at $3000 while the code is stored at $2000
    r = asm("relocate  $3000\nstart     ldx #$0\ncycle     lda hworld,x\n          beq exit\n"
            "          inx\n          jmp cycle\nexit      rts\nhworld    text 'hello'\n          byte 0", 0x2000)
    assert r.ok
    assert r.symbols["start"] == 0x3000 and r.symbols["cycle"] == 0x3002
    assert r.start == 0x2000 and r.memory[0x2000] == 0xA2
    assert r.memory[0x2008:0x200B] == bytes([0x4C, 0x02, 0x30])       # jmp cycle -> $3002
    r = asm("        relocate $3000\n        nop\n        relocate off\nback    nop", 0x2000)
    assert r.symbols["back"] == 0x2001


def test_noloadaddr_saveblock_padbyte():
    assert asm("        noloadaddr\n        byte 1,2").prg() == bytes([1, 2])
    assert asm("        byte 1,2,3,4\n        saveblock $c001,$c002").prg() == bytes([1, 0xC0, 2, 3])
    assert asm("        padbyte $ea\n        byte 1\n*=$c004\n        byte 2").prg() == \
        bytes([0, 0xC0, 1, 0xEA, 0xEA, 0xEA, 2])


def test_zpopt():
    assert code("        lda $0002,x") == bytes([0xB5, 2])          # optimised by default
    assert code("        zpopt off\n        lda $0002,x\n        zpopt on\n        lda $0002,x") == \
        bytes([0xBD, 2, 0, 0xB5, 2])
    assert any("could be zero page" in w for w in warnings("        zpopt off\n        ldx $00f3,y"))
    assert code("        zpopt off\n        lda $02,x") == bytes([0xB5, 2])     # written as one byte


def test_target():
    src = "        target TGT_C64\n        ifdef TGT_C64\n        byte 1\n        endif\n" \
          "        ifdef TGT_VIC20\n        byte 2\n        endif"
    assert code(src) == bytes([1])
    assert code("        ifdef TGT_C64\n        byte 1\n        endif") == bytes([1])    # the default
    assert any("C64" in w for w in warnings("        target TGT_VIC20"))
    assert errors("        target TGT_AMIGA")


# ---------------------------------------------------------------------- REPEAT
def test_repeat():
    assert code("        repeat 5\n        byte 0\n        endrepeat") == bytes(5)
    assert code("        repeat 5, index\n        byte 0,index\n        endrepeat") == \
        bytes([0, 1, 0, 2, 0, 3, 0, 4, 0, 5])
    assert code("        repeat 5,10,index\n        byte 0,index\n        endrepeat") == \
        bytes([0, 5, 0, 6, 0, 7, 0, 8, 0, 9, 0, 10])
    assert code("        repeat 4,10,2,index\n        byte 0,index\n        endrepeat") == \
        bytes([0, 4, 0, 6, 0, 8, 0, 10])
    assert code("n = 3\n        repeat n\n        nop\n        endrepeat") == bytes([0xEA]) * 3
    assert code("        repeat 2,i\n        repeat 2,j\n        byte i*10+j\n        endrepeat\n"
                "        endrepeat") == bytes([11, 12, 21, 22])
    assert errors("        repeat 3\n        nop")


# ---------------------------------------------------------------------- messages and the debugger
def test_warning_and_jmp_indirect():
    assert any("page-boundary" in w for w in warnings("        jmp ($c0ff)"))
    assert not warnings("        warning off\n        jmp ($c0ff)\n        warning on")


def test_debug_messages():
    r = asm('        debug "Main loop code"\n        debug option auto on\n        debug option base hex\n'
            'loop1   debug loop1\n        debug option base decimal\n        debug loop1')
    assert r.messages == ["Main loop code", "loop1 = $C000", "loop1 = 49152"]


def test_debugger_directives():
    r = asm("        export start\nstart   rts\n        watch start, the start\n        breakpoint\n"
            "        breakpoint start X == 20\n        breakpoint PC == $1000\n        debugstartaddress start\n"
            "        generateto game.prg,game.d64,mydisk\n        checksum")
    assert r.ok
    assert r.exports == {"start": 0xC000}
    assert r.watches == [("start", 0xC000, "the start")]
    assert r.breakpoints == [(0xC001, ""), (0xC000, "X == $14"), (0xC001, "PC == $1000")]
    assert r.debug_start == 0xC000
    assert r.generate_to == ["game.prg", "game.d64", "mydisk"]


# ---------------------------------------------------------------------- labels across files
def test_labels_are_local_to_their_file(tmp_path):
    (tmp_path / "a.asm").write_text("*=$c000\nstart   nop\n        jmp start\nshared$ nop\n")
    (tmp_path / "b.asm").write_text("*=$c100\nstart   rts\n        jmp start\n        jmp shared$\n")
    (tmp_path / "c.asm").write_text("*=$c200\n        jsr libonly\n")
    (tmp_path / "d.asm").write_text("*=$c300\nlibonly rts\n")
    r = Assembler(Options()).assemble_files([tmp_path / n for n in ("a.asm", "b.asm", "c.asm", "d.asm")])
    assert r.ok, [str(d) for d in r.diagnostics]
    m = r.memory
    assert m[0xC002] | m[0xC003] << 8 == 0xC000        # a's own start
    assert m[0xC102] | m[0xC103] << 8 == 0xC100        # b's own start
    assert m[0xC105] | m[0xC106] << 8 == 0xC004        # shared$ is project-wide
    assert m[0xC201] | m[0xC202] << 8 == 0xC300        # a label in only one file is found from others
    (tmp_path / "e.asm").write_text("*=$c400\nshared$ nop\n")
    r = Assembler(Options()).assemble_files([tmp_path / "a.asm", tmp_path / "e.asm"])
    assert any("shared$" in d.message for d in r.diagnostics if d.severity == "error")


# ---------------------------------------------------------------------- the build: EXPORT, GENERATETO
def test_export_puts_labels_in_basic(tmp_path):
    """CBM prg Studio's tutorial 12: the BASIC says SYS start, the build fills in the address."""
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "t12.bas").write_text('10 rem basic/ml demo\n20 sys start\n30 print "start"\n40 end\n')
    (tmp_path / "t12.asm").write_text("        export start\n*=$8000\nstart  ldx #$0\ncycle  lda hworld,x\n"
                                      "       cmp #0\n       beq exit\n       sta $0400,x\n       inx\n"
                                      "       jmp cycle\nexit   rts\nhworld text 'hello world!'\n       byte 0\n")
    p = Project(path=tmp_path / "t.l64proj", name="t", build_list=["t12.asm", "t12.bas"], executable="t.prg")
    res = build_project(p)
    assert res.ok, res.log
    from l64s.basic.tokenizer import detokenize
    listing = detokenize(res.prg.read_bytes().split(b"\x00\x00\x00")[0] + b"\x00\x00\x00")
    assert "sys32768" in listing.replace(" ", "")
    assert '"start"' in listing                          # not inside strings
    if os.environ.get("L64S_VICE_TESTS") == "1":
        assert "hello world!" in _run_and_read_screen(res.prg, tmp_path)


def test_generateto(tmp_path):
    from l64s.disk.image import DiskImage
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "m.asm").write_text("        generateto other.prg,game.d64,my disk\n*=$c000\n        rts\n")
    p = Project(path=tmp_path / "t.l64proj", name="t", build_list=["m.asm"], executable="t.prg")
    res = build_project(p)
    assert res.ok and res.prg.name == "other.prg" and (tmp_path / "other.prg").read_bytes() == b"\x00\xc0\x60"
    assert DiskImage.load(tmp_path / "game.d64").read_file("other") == b"\x00\xc0\x60"
    (tmp_path / "m.asm").write_text("        generateto game.p00,mygame\n*=$c000\n        rts\n")
    res = build_project(p)
    data = (tmp_path / "game.p00").read_bytes()
    assert data[:8] == b"C64File\x00" and data[8:14] == b"MYGAME" and data[26:] == b"\x00\xc0\x60"
    (tmp_path / "m.asm").write_text("        generateto null\n*=$c000\n        rts\n")
    res = build_project(p)
    assert res.ok and res.prg is None


def _run_and_read_screen(prg: Path, tmp_path) -> str:
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    port = free_port()
    proc = launch(prg, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy", "+saveres"])
    try:
        assert wait_for_port(port)
        m = BinaryMonitor()
        m.connect(port=port)
        text = ""
        for _ in range(30):
            m.resume()
            time.sleep(0.5)
            screen = m.read_memory(0x0400, 0x07E7)
            text = "".join(chr(c + 96) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else " " for c in screen)
            if "hello world!" in text:
                break
        m.quit()
        return text
    finally:
        proc.terminate()
        proc.wait(5)


@pytest.mark.skipif(os.environ.get("L64S_VICE_TESTS") != "1", reason="set L64S_VICE_TESTS=1 to run VICE")
def test_breakpoint_condition_in_vice(tmp_path):
    """BREAKPOINT label X == 20 stops only when X is 20."""
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    r = Assembler(Options()).assemble_text(
        "*=$0801\n        byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00\n*=$080d\n"
        "        ldx #0\nloop    inx\n        jmp loop\n        breakpoint loop X == 20\n")
    (addr, cond), = r.breakpoints
    prg = tmp_path / "bp.prg"
    prg.write_bytes(r.prg())
    port = free_port()
    proc = launch(prg, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy", "+saveres"])
    try:
        assert wait_for_port(port)
        m = BinaryMonitor()
        m.connect(port=port)
        m.set_condition(m.add_checkpoint(addr).id, cond)
        m.resume()
        time.sleep(3)
        regs = m.get_registers()
        m.quit()
    finally:
        proc.terminate()
        proc.wait(5)
    assert regs["X"] == 20 and regs["PC"] == addr
