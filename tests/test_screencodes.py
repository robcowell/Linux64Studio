import os
import shutil
import time

import pytest

from l64s.asm.assembler import Assembler
from l64s.basic.screencodes import (BuildError, petscii_to_screencode, simulate_print, text_to_petscii, to_basic,
                                    to_petscii_bytes, to_screen_codes)
from l64s.basic.tokenizer import crunch, tokenize

SAMPLES = [
    "{clear}{white}hello, {cyan}world!{return}{yellow}{reverse on} BASIC {reverse off} {cbm-a}{shift-*}{cbm-s}Q",
    "{3 down}{red}abcdef{left}{left}{delete}X{insert}Y{up}{up}{green}up{home}{purple}H",
    "{clear}{lower case}{light green}Mixed Case{return}{f1}{$22}quoted{$22}£^_",
]


def test_text_to_petscii():
    assert text_to_petscii("{clear}aA{cbm-a}{shift-+}") == bytes([0x93, 0x41, 0xC1, 0xB0, 0xDB])
    assert text_to_petscii("a\nb") == bytes([0x41, 0x0D, 0x42])
    with pytest.raises(BuildError):
        text_to_petscii("{nonsense}")
    with pytest.raises(BuildError):
        text_to_petscii("{clear")


@pytest.mark.parametrize("text", SAMPLES)
def test_basic_output_tokenizes_back_to_the_same_petscii(text):
    pet = text_to_petscii(text)
    line = to_basic(pet, 10)
    body = crunch(line.split(" ", 1)[1])
    assert body[0] == 0x99 and body[1] == 0x20                  # PRINT, space
    assert body[2] == 0x22 and body[-2:] == b'";'
    assert body[3:-2] == pet


def test_basic_output_compresses_repeats_and_names_graphics():
    assert to_basic(text_to_petscii("{down}{down}{down}{cbm-a}A")) == 'print "{3 down}{cbm-a}A";'


@pytest.mark.parametrize("petscii,screen", [(0x41, 0x01), (0x20, 0x20), (0x31, 0x31), (0xC1, 0x41), (0x60, 0x40),
                                            (0xA0, 0x60), (0xB0, 0x70), (0xE0, 0x60), (0xFF, 0x5E), (0x93, None),
                                            (0x05, None)])
def test_petscii_to_screencode(petscii, screen):
    assert petscii_to_screencode(petscii) == screen


def test_simulation_rules():
    s = simulate_print(text_to_petscii("{white}ab{reverse on}c{return}d"))
    assert s.chars[0][:3] == [1, 2, 3 | 0x80] and s.colours[0][0] == 1
    assert s.chars[1][0] == 4 and not s.reverse                     # RETURN turns reverse off
    s = simulate_print(text_to_petscii("abc{left}{left}{delete}"))
    assert s.chars[0][:3] == [2, 3, 0x20] and s.col == 0
    s = simulate_print(text_to_petscii("abc{left}{left}{insert}"))
    assert s.chars[0][:4] == [1, 0x20, 2, 3]
    s = simulate_print(text_to_petscii("{24 down}x{return}y"))
    assert s.chars[23][0] == 24 and s.chars[24][0] == 25           # scrolled up a line
    s = simulate_print(text_to_petscii("{white}{clear}"))
    assert s.colours[10][10] == 1                                   # clear fills colour RAM with the text colour
    assert simulate_print(text_to_petscii("{lower case}")).lowercase


def test_byte_outputs_assemble(tmp_path):
    pet = text_to_petscii(SAMPLES[0])
    src = "*=$c000\n" + to_petscii_bytes(pet, "msg")
    r = Assembler().assemble_text(src, str(tmp_path / "a.asm"))
    assert r.ok and r.binary() == pet + b"\0" and r.symbols["msg"] == 0xC000
    s = simulate_print(pet)
    src = "*=$c000\n" + to_screen_codes(s, "scr", colours=True)
    r = Assembler().assemble_text(src, str(tmp_path / "b.asm"))
    assert r.ok and r.symbols["scrcolours"] == 0xC000 + 80        # rows 0-1, 40 bytes each
    assert r.binary()[:5] == bytes([8, 5, 12, 12, 15])             # "hello"
    ka = to_petscii_bytes(pet, "msg", kickass=True)
    assert ka.splitlines()[1] == "msg:" and ".byte" in ka
    with pytest.raises(BuildError):
        to_screen_codes(simulate_print(b"\x05"))


@pytest.mark.skipif(not (os.environ.get("L64S_VICE_TESTS") and shutil.which("x64sc")),
                    reason="set L64S_VICE_TESTS=1 to run against VICE (opens emulator windows)")
@pytest.mark.parametrize("text", SAMPLES[:2] + ["{clear}{lower case}{orange}Mixed{reverse on}Case{blue}{shift-a}"])
def test_simulation_matches_a_real_c64(tmp_path, text):
    from l64s.emu import vice
    from l64s.emu.binmon import BinaryMonitor
    # The simulation starts from a blank screen; the real one has VICE's LOAD and RUN on it.
    pet = text_to_petscii(text if text.startswith("{clear}") else "{clear}" + text)
    src = "1 " + to_basic(pet) + "\n2 goto 2\n"
    prg = tmp_path / "t.prg"
    prg.write_bytes(tokenize(src).prg())
    port = vice.free_port()
    p = vice.launch(prg, monitor_port=port, extra_args=["+sound", "-warp"])
    try:
        assert vice.wait_for_port(port)
        m = BinaryMonitor()
        m.connect(port=port)
        m.resume()
        time.sleep(4)
        m.ping()
        scr, col, d018 = m.read_memory(0x0400, 0x07E7), m.read_memory(0xD800, 0xDBE7), m.read_memory(0xD018, 0xD018)
        m.quit()
        m.close()
    finally:
        p.terminate()
    s = simulate_print(pet)
    assert list(scr) == [b for row in s.chars for b in row]
    assert [c & 15 for c in col] == [c for row in s.colours for c in row]
    assert bool(d018[0] & 2) == s.lowercase
