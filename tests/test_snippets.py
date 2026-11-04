import pytest

from l64s.asm.assembler import Assembler, Options
from l64s.basic.tokenizer import detokenize, tokenize
from l64s.snippets import (MACHINE_CODE, TYPES, Snippet, SnippetError, builtin, cbm_case, expand, load, merge,
                           number_basic, parse, save, to_kickass, to_xml)

CBM_XML = """﻿<?xml version="1.0" encoding="utf-8"?>
<snippets>
  <snippet>
    <type>0</type>
    <description>Enable Nth sprite</description>
    <code>
      <line>REM V = 53248, START OF DISPLAY CHIP</line>
      <line>POKE V + 21, PEEK(V + 21) OR 2 ^ N</line>
      <line>RETURN</line>
    </code>
  </snippet>
  <snippet>
    <type>3</type>
    <description>Clear SID chip</description>
    <code>
      <line>FOR L = S TO S+24:POKE L,0:NEXT</line>
    </code>
  </snippet>
</snippets>
"""


def test_reads_cbm_format():
    sn = parse(CBM_XML)
    assert [(s.type, s.description) for s in sn] == [(0, "Enable Nth sprite"), (3, "Clear SID chip")]
    assert sn[0].lines[1] == "POKE V + 21, PEEK(V + 21) OR 2 ^ N"
    assert sn[0].is_basic


def test_round_trip(tmp_path):
    sn = parse(CBM_XML)
    p = tmp_path / "Snippets.xml"
    save(sn, p)
    assert load(p) == sn
    assert parse(to_xml(sn)) == sn


def test_not_a_snippets_file():
    with pytest.raises(SnippetError):
        parse("<project/>")
    with pytest.raises(SnippetError):
        parse("not xml")


def test_labels_as_in_cbms_help():
    lines = ["A=1", "!2 A=A+1:IF A = 10 THEN GOTO !1", "GOTO !2", "!1 END"]
    assert number_basic(lines, 1000, 10) == ["1000 A=1", "1010 A=A+1:IF A = 10 THEN GOTO 1030", "1020 GOTO 1010",
                                             "1030 END"]


def test_labels_leave_strings_and_rems_alone():
    lines = ['!1 print "!1 wow" : rem goto !1', "goto !1"]
    assert number_basic(lines, 10, 5) == ['10 print "!1 wow" : rem goto !1', "15 goto 10"]


def test_label_errors():
    with pytest.raises(SnippetError, match="!3"):
        number_basic(["goto !3"])
    with pytest.raises(SnippetError):
        number_basic(["!1 a=1", "!1 b=2"])
    with pytest.raises(SnippetError):
        number_basic(["a=1", "b=2"], 63995, 10)


def test_cbm_capitals_become_listing_case():
    assert cbm_case('PRINT "{CLEAR}HELLO"') == 'print "{CLEAR}hello"'
    assert cbm_case('print "Hello"') == 'print "Hello"'        # already listing case: left as written
    sn = parse(CBM_XML)[0]
    out = expand(sn, 100, 10)
    assert out.splitlines()[1] == "110 poke v + 21, peek(v + 21) or 2 ^ n"
    assert not tokenize(out).warnings


def test_builtins_are_well_formed():
    sn = builtin()
    assert len(sn) >= 30
    assert {s.type for s in sn} == set(range(len(TYPES)))
    assert len({s.key for s in sn}) == len(sn)


@pytest.mark.parametrize("snippet", [s for s in builtin() if s.is_basic], ids=lambda s: s.description)
def test_builtin_basic_tokenizes_and_lists_back(snippet):
    text = expand(snippet, 1000, 10)
    result = tokenize(text)
    assert not result.warnings
    assert detokenize(result.prg()).strip() == text.strip()


@pytest.mark.parametrize("snippet", [s for s in builtin() if not s.is_basic], ids=lambda s: s.description)
def test_builtin_machine_code_assembles(snippet):
    res = Assembler(Options()).assemble_text("*=$c000\n" + expand(snippet) + "        rts\n")
    assert res.ok, [str(d) for d in res.diagnostics]


def test_merge_skips_ones_already_there():
    have = parse(CBM_XML)
    assert merge(have, [Snippet(3, "clear sid chip", ["x"]), Snippet(4, "New", ["y"])]) == 1
    assert len(have) == 3


def test_to_kickass():
    src = "\n".join(["; a comment", "loop    lda #$20       ; space", "        sta $0400,x", "        bne loop",
                     "msg     byte 1,2,3", "VALUE = 5", "*=$c000"])
    out = to_kickass(src).splitlines()
    assert out[0] == "// a comment"
    assert out[1].startswith("loop:") and out[1].endswith("// space")
    assert out[2].strip() == "sta $0400,x"
    assert out[4].startswith("msg:") and ".byte 1,2,3" in out[4]
    assert out[5] == ".const VALUE = 5"
    assert out[6] == "*= $c000"


def test_expand_machine_code_for_kickass():
    raster = next(s for s in builtin() if s.type == MACHINE_CODE and s.description.startswith("Raster"))
    out = expand(raster, kickass=True)
    assert "irq:" in out and "//" in out and ";" not in out


def test_basic_placement():
    from l64s.ui.snippets_view import basic_placement
    prog = "10 print 1\n20 gosub 1000\n2000 end\n"
    assert basic_placement(prog, "1000 rem\n1010 return\n") == (2, [])
    assert basic_placement(prog, "3000 rem\n") == (None, [])
    assert basic_placement(prog, "5 rem\n") == (0, [])
    assert basic_placement(prog, "20 rem\n2000 x\n") == (2, [20, 2000])


def _vice_run(prg_bytes: bytes, tmp_path, check, tries: int = 60):
    """Run a program in x64sc (warp) until check(monitor) returns true; returns the last result."""
    import os
    import time
    if os.environ.get("L64S_VICE_TESTS") != "1":
        pytest.skip("set L64S_VICE_TESTS=1 to run VICE")
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    prg = tmp_path / "snippet.prg"
    prg.write_bytes(prg_bytes)
    port = free_port()
    proc = launch(prg, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy"])
    try:
        assert wait_for_port(port)
        mon = BinaryMonitor()
        mon.connect(port=port)
        result = None
        for _ in range(tries):
            mon.resume()
            time.sleep(0.5)
            result = check(mon)
            if result:
                break
        mon.quit()
        return result
    finally:
        proc.terminate()
        proc.wait(5)


def _snippet(desc: str) -> Snippet:
    return next(s for s in builtin() if s.description.startswith(desc))


def test_charset_and_plot_snippets_in_vice(tmp_path):
    text = (expand(_snippet("Copy the ROM character set"), 100)
            + "200 x=100 : y=50\n" + expand(_snippet("Plot point"), 210) + "300 poke 2,42\n")
    prg = tokenize(text).prg()

    def done(mon):
        # $02 (a free zero page byte) is set once BASIC has finished
        if mon.read_memory(0x0002, 0x0002)[0] != 42:
            return None
        return mon.read_memory(0x3000, 0x3007), mon.read_memory(0x3008, 0x300F), mon.read_memory(10210, 10210)[0]
    at, a, plotted = _vice_run(prg, tmp_path, done, tries=120)
    assert at == bytes([0x3C, 0x66, 0x6E, 0x6E, 0x60, 0x62, 0x3C, 0x00])     # "@" from the character ROM
    assert a == bytes([0x18, 0x3C, 0x66, 0x7E, 0x66, 0x66, 0x66, 0x00])      # "A"
    assert plotted & 0x08                                                      # x=100 is bit 3 of its byte


def test_raster_interrupt_snippet_in_vice(tmp_path):
    code = ("*=$0801\n        byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00\n*=$080d\n"
            + expand(_snippet("Raster interrupt")))
    res = Assembler(Options()).assemble_text(code)
    assert res.ok
    irq = res.symbols["irq"]
    prg = bytes([0x01, 0x08]) + bytes(res.memory[0x0801:res.end])
    seen = set()

    def running(mon):
        vec = mon.read_memory(0x0314, 0x0315)
        seen.add(mon.read_memory(0xD020, 0xD020, side_effects=False)[0] & 0x0F)
        return vec[0] | vec[1] << 8 == irq and len(seen) > 2
    assert _vice_run(prg, tmp_path, running)
