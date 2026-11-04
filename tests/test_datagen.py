import math
import os
import time

import pytest

from l64s.asm.assembler import Assembler, Options as AsmOptions
from l64s.basic.tokenizer import tokenize
from l64s.cbmfloat import FloatError, from_cbm, to_cbm
from l64s.datagen import DataGenError, Function, Options, generate, source


# ---------------------------------------------------------------------- C64 floats
def test_known_floats():
    assert to_cbm(1) == bytes([0x81, 0, 0, 0, 0])
    assert to_cbm(-1) == bytes([0x81, 0x80, 0, 0, 0])
    assert to_cbm(math.pi) == bytes([0x82, 0x49, 0x0F, 0xDA, 0xA2])
    assert to_cbm(0.5) == bytes([0x80, 0, 0, 0, 0])
    assert to_cbm(10) == bytes([0x84, 0x20, 0, 0, 0])
    assert to_cbm(0) == bytes(5)
    with pytest.raises(FloatError):
        to_cbm(1e39)


@pytest.mark.parametrize("v", [1, -2.5, 3.14159265, 1e10, -1e-5, 12345.678, 0.1])
def test_float_round_trip(v):
    assert from_cbm(to_cbm(v)) == pytest.approx(v, rel=1e-9)


def test_fltp_directive():
    res = Assembler(AsmOptions()).assemble_text("*=$c000\nTWO = 2\n        fltp 1, -0.5\n        fltp TWO\n")
    assert res.ok, res.diagnostics
    assert bytes(res.memory[0xC000:0xC00F]) == to_cbm(1) + to_cbm(-0.5) + to_cbm(2)
    bad = Assembler(AsmOptions()).assemble_text("*=$c000\n        fltp 1e40\n")
    assert not bad.ok


# ---------------------------------------------------------------------- functions
def test_function_parsing():
    f = Function("INT(100+99*SIN(X/20))")
    assert f(0) == 100
    assert Function("x^2 + 1")(3) == 10
    assert Function("sqr(x) * pi")(4) == pytest.approx(2 * math.pi)
    assert Function("-x")(5) == -5
    for bad in ("", "1+2", "y*2", "x +", "__import__('os')", "x.real", "open(x)", "'a'*x", "[x]"):
        with pytest.raises(DataGenError):
            Function(bad)
    with pytest.raises(DataGenError, match="x=0"):
        Function("1/x")(0)


# ---------------------------------------------------------------------- tables
def test_sine_table():
    t = generate(Options(function="128+127*sin(x*2*pi/256)", start=0, end=255))
    assert len(t.values) == 256
    assert t.values[0] == 128 and t.values[64] == 255 and t.values[192] == 1


def test_range_errors_and_clamping():
    with pytest.raises(DataGenError, match="x=150"):
        generate(Options(function="x*2", start=0, end=200, step=50))
    t = generate(Options(function="x*2", start=0, end=200, step=50, clamp=True, clamp_min=0, clamp_max=255))
    assert t.values == [0, 100, 200, 255, 255]
    for bad in (Options(start=5, end=5), Options(start=9, end=1), Options(step=0)):
        with pytest.raises(DataGenError):
            generate(bad)


def test_deltas_and_pairs():
    t = generate(Options(function="x*x", start=0, end=4, deltas=True))
    assert t.values == [0, 1, 3, 5, 7]
    text = source(Options(function="x*x", start=0, end=3, include_x=True, comment=False, per_line=4))
    assert text.splitlines() == ["        byte $00, $00, $01, $01", "        byte $02, $04, $03, $09"]


def test_negative_bytes_and_words():
    text = source(Options(function="x-2", start=0, end=3, comment=False))
    assert text.strip() == "byte -2, -1, $00, $01"
    text = source(Options(function="x*1000", start=0, end=2, type="word", comment=False))
    assert text.strip() == "word $0000, $03E8, $07D0"


def test_source_assembles():
    opts = Options(function="100+99*sin(x/20)", start=0, end=63, label="wave")
    res = Assembler(AsmOptions()).assemble_text("*=$c000\n" + source(opts))
    assert res.ok, res.diagnostics
    assert list(res.memory[0xC000:0xC040]) == generate(opts).values
    assert res.symbols["wave"] == 0xC000


def test_floats():
    opts = Options(function="x/4", start=0, end=4, type="float", comment=False)
    text = source(opts)
    assert text.strip() == "fltp 0, 0.25, 0.5, 0.75, 1"
    res = Assembler(AsmOptions()).assemble_text("*=$c000\n" + text)
    assert bytes(res.memory[0xC000:0xC019]) == b"".join(to_cbm(v / 4) for v in range(5))
    kick = source(Options(function="x", start=1, end=2, type="float", kickass=True, comment=False))
    assert kick.splitlines()[0].startswith("    .byte $81, $00, $00, $00, $00, $82, $00")


def test_kickass_output():
    text = source(Options(function="x", start=0, end=2, kickass=True, label="tbl"))
    lines = text.splitlines()
    assert lines[0].startswith("// y = x")
    assert lines[1] == "tbl:"
    assert lines[2] == "    .byte $00, $01, $02"


# ---------------------------------------------------------------------- against the C64's own floats
@pytest.mark.skipif(os.environ.get("L64S_VICE_TESTS") != "1", reason="set L64S_VICE_TESTS=1 to run VICE")
def test_floats_match_c64_basic(tmp_path):
    """BASIC stores a=<number> as 2 name bytes and the 5-byte float: compare with to_cbm."""
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    values = ["1", "-2.5", "3.14159265", "1e10", "12345.678", "0.1", "-1e-05", "255"]
    names = [f"a{i}" for i in range(len(values))]
    prog = "".join(f"{10 * (i + 1)} {n}={v}\n" for i, (n, v) in enumerate(zip(names, values))) + "900 poke 2,42\n"
    prg = tmp_path / "f.prg"
    prg.write_bytes(tokenize(prog).prg())
    port = free_port()
    proc = launch(prg, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy"])
    try:
        assert wait_for_port(port)
        mon = BinaryMonitor()
        mon.connect(port=port)
        for _ in range(40):
            mon.resume()
            time.sleep(0.5)
            if mon.read_memory(2, 2)[0] == 42:
                break
        zp = mon.read_memory(0x2D, 0x30)
        vartab, arytab = zp[0] | zp[1] << 8, zp[2] | zp[3] << 8
        table = mon.read_memory(vartab, arytab - 1)
        mon.quit()
    finally:
        proc.terminate()
        proc.wait(5)
    stored = {bytes(table[i:i + 2]).decode("latin-1"): bytes(table[i + 2:i + 7]) for i in range(0, len(table), 7)}
    # fltp gives the nearest 5-byte value. The ROM's own number reader builds the value digit by digit
    # and can be one step off in the last bit (12345.678 and -1e-05 here), so allow that much.
    exact = 0
    for n, v in zip(names, values):
        key = n.upper()[0] + n[1]
        rom, ours = stored[key], to_cbm(float(v))
        assert rom[:1] == ours[:1] and abs(int.from_bytes(rom[1:], "big") - int.from_bytes(ours[1:], "big")) <= 1, v
        exact += rom == ours
    assert exact >= 6
