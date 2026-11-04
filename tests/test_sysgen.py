import os
import time
from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler, Options
from l64s.binconv import Binary, basic_sys_address
from l64s.basic.tokenizer import detokenize
from l64s.sysgen import SysCall, SysError, generate, source

BOOK_STUB = bytes([0x0E, 0x08, 0x0A, 0x00, 0x9E, 0x20, 0x28, 0x32, 0x30, 0x36, 0x34, 0x29, 0x00, 0x00, 0x00])


def test_decorated_is_the_books_stub():
    data, addr, listing = generate(SysCall())
    assert data == BOOK_STUB
    assert addr == 2064 and listing == "10 SYS (2064)"


def test_plain():
    data, addr, listing = generate(SysCall(style="plain"))
    assert addr == 0x0801 + len(data) == 2061
    assert listing == "10 SYS2061"
    assert detokenize(bytes([0x01, 0x08]) + data).strip() == "10 sys2061"


def test_explicit_address_and_line():
    data, addr, listing = generate(SysCall(address=0xC000, line=2024, style="plain"))
    assert addr == 49152 and listing == "2024 SYS49152"
    assert data[2:4] == bytes([0xE8, 0x07])
    with pytest.raises(SysError, match="inside"):
        generate(SysCall(address=0x0805))
    with pytest.raises(SysError):
        generate(SysCall(line=64000))


@pytest.mark.parametrize("style", ["decorated", "plain", "obfuscated"])
def test_sys_address_reads_back(style):
    data, addr, _ = generate(SysCall(style=style, message="my game"))
    b = Binary(0x0801, data)
    assert basic_sys_address(b) == addr


def test_obfuscated():
    data, addr, listing = generate(SysCall(style="obfuscated", message="(c) 2026 me"))
    text = data[4:data.index(0, 4)]
    assert text.startswith(b"\x9e" + str(addr).encode() + b":\x8f")
    dels = text.count(0x14)
    assert dels == len("10 SYS") + len(str(addr)) + len(":REM")
    assert "lists as: (c) 2026 me" in listing
    with pytest.raises(SysError):
        generate(SysCall(style="obfuscated", message=" "))


def test_source_assembles_to_the_stub():
    for kickass in (False, True):
        text = source(SysCall(), kickass)
        assert ("// BASIC loader" if kickass else "; BASIC loader") in text
        assert "*=$0810" in text
    res = Assembler(Options()).assemble_text(source(SysCall()) + "        rts\n")
    assert res.ok
    assert bytes(res.memory[0x0801:0x0811]) == BOOK_STUB + b"\x60"


def _run(prg: bytes, tmp_path: Path, check, keys: bytes = b""):
    if os.environ.get("L64S_VICE_TESTS") != "1":
        pytest.skip("set L64S_VICE_TESTS=1 to run VICE")
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    p = tmp_path / "sys.prg"
    p.write_bytes(prg)
    port = free_port()
    proc = launch(p, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy"])
    try:
        assert wait_for_port(port)
        mon = BinaryMonitor()
        mon.connect(port=port)
        typed = False
        result = None
        for _ in range(40):
            mon.resume()
            time.sleep(0.5)
            if keys and not typed and mon.read_memory(0x02, 0x02)[0] == 0x42:
                mon.write_memory(0x0277, keys)          # the keyboard buffer
                mon.write_memory(0xC6, bytes([len(keys)]))
                typed = True
                continue
            result = check(mon)
            if result:
                break
        mon.quit()
        return result
    finally:
        proc.terminate()
        proc.wait(5)


@pytest.mark.parametrize("style", ["decorated", "plain"])
def test_sys_runs_the_program_in_vice(style, tmp_path):
    # the program stores $42 in $02 (a free zero page byte) and loops
    src = source(SysCall(style=style)) + "        lda #$42\n        sta $02\n        jmp *\n"
    res = Assembler(Options()).assemble_text(src)
    assert res.ok
    prg = bytes([0x01, 0x08]) + bytes(res.memory[0x0801:res.end])
    assert _run(prg, tmp_path, lambda mon: mon.read_memory(0x02, 0x02)[0] == 0x42)


def test_obfuscated_lists_as_the_message_in_vice(tmp_path):
    # the program sets the marker and returns to BASIC; then we type LIST
    call = SysCall(address=0x0900, style="obfuscated", message="hello there")
    src = source(call) + "        lda #$42\n        sta $02\n        rts\n"
    res = Assembler(Options()).assemble_text(src)
    assert res.ok
    prg = bytes([0x01, 0x08]) + bytes(res.memory[0x0801:res.end])

    def listed(mon):
        screen = mon.read_memory(0x0400, 0x07E7)
        rows = [bytes(screen[r * 40:r * 40 + 40]) for r in range(25)]
        # screen codes: "hello there" in the upper case set is 8,5,12,12,15,32,20,8,5,18,5
        want = bytes([8, 5, 12, 12, 15, 32, 20, 8, 5, 18, 5])
        hit = [r for r in rows if r.startswith(want)]
        return hit and not any(bytes([19, 25, 19]) in r for r in rows[-8:])     # no "SYS" left showing
    assert _run(prg, tmp_path, listed, keys=b"LIST\r")
