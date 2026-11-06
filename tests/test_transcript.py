import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from l64s.transcript import TEMPLATE, TranscriptError, parse

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_parsing():
    cmds = parse("; a comment\n\n// another\nx $33\ncall delay   ; with a comment after\nCHECK x = 0\n")
    assert [(c.line, c.verb, c.args) for c in cmds] == [(4, "x", "$33"), (5, "call", "delay"), (6, "check", "x = 0")]
    with pytest.raises(TranscriptError, match="Line 2: 'jump somewhere'"):
        parse("call x\njump somewhere\n")
    # CBM prg Studio's own transcript commands are understood
    assert [c.verb for c in parse("step\nstepover\nA $20\nset $1000 $15\nwatch $1000\nclearregs\nresetstack\n"
                                  "skipkernal on\ncheck a = $20\nbreak\nend\n")] == \
        ["step", "stepover", "a", "set", "watch", "clearregs", "resetstack", "skipkernal", "check", "break", "end"]
    assert [c.verb for c in parse(TEMPLATE.format(name="t"))] == ["run"]


def test_names_for_a_c_program():
    from l64s.profiler import Resolver
    r = Resolver({0x4000: "_main", 0x5000: "popax", 0x6000: "_score"}, c=True,
                 functions=[(0x4077, 0x4082, "_wait_frame")])
    t = r.symbol_table()
    assert t["main"] == 0x4000 and t["_main"] == 0x4000 and t["wait_frame"] == 0x4077 and t["score"] == 0x6000


DELAY = """; a raster interrupt isn't needed: a subroutine and some data
*=$0801
        byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00
*=$080d
start   rts

delay   ldx #50
dloop   dex
        bne dloop
        rts

add16   clc
        lda num1
        adc num2
        sta result
        lda num1+1
        adc num2+1
        sta result+1
        rts

border  lda #2
        sta $d020
        rts

num1    word 0
num2    word 0
result  word 0
"""

SCRIPT = """; add16 and delay, timed exactly
set num1 $34 $12
set num2 $01 $00
call add16
check word result = $1235
check cycles = #32
x $33
interrupts off
call delay
check x = 0
check z = 1
check cycles = #257
call border
check $d020 & $0f = 2
set $c000 "hi" $01
check $c000 = "hi" $01
check a = $55
"""


def _vice_ok():
    return os.environ.get("L64S_VICE_TESTS") == "1" and shutil.which("x64sc")


@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_a_transcript_in_vice(tmp_path):
    (tmp_path / "t.asm").write_text(DELAY)
    (tmp_path / "t.transcript").write_text(SCRIPT)
    out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "t.asm"),
                          str(tmp_path / "t.transcript"), "--vice-args=-sounddev dummy"],
                         capture_output=True, text=True, timeout=120)
    text = out.stdout
    assert out.returncode == 1, text                          # the one check meant to fail
    assert "7 checks passed, 1 failed" in text, text
    assert "t.transcript:17: FAIL check a = $55" in text, text
    assert "returned after 32 cycles" in text and "returned after 257 cycles" in text, text


@pytest.mark.skipif(not (_vice_ok() and shutil.which("cl65")), reason="needs VICE and cc65")
def test_a_transcript_for_a_c_program(tmp_path):
    shutil.copytree(EXAMPLES / "glowcave", tmp_path / "gc", ignore=shutil.ignore_patterns("build"))
    (tmp_path / "t.transcript").write_text("run until wait_frame\ncheck pc = wait_frame\ncheck $d021 & $0f = 0\n"
                                           "call wait_frame\ncheck cycles < #19700\n")
    out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "gc" / "glowcave.l64proj"),
                          str(tmp_path / "t.transcript"), "--vice-args=-sounddev dummy"],
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0 and "3 checks passed, 0 failed" in out.stdout, out.stdout
