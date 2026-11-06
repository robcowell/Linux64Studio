import os
import shutil
import subprocess
import sys

import pytest

from l64s.overlays import OverlayError, describe, load, load_all, parse_ovl


def test_cbm_prg_studios_overlay_format():
    text = """; a table and some zeros
*=1000
a9
01 02,03
00*10
decimal
*=49152
255
7*3
"""
    assert parse_ovl(text) == [(0x1000, bytes([0xA9, 1, 2, 3]) + bytes(16)), (49152, bytes([255, 7, 7, 7]))]
    with pytest.raises(OverlayError, match="before the first"):
        parse_ovl("a9\n")
    with pytest.raises(OverlayError, match="isn't a byte"):
        parse_ovl("*=1000\n100\n")
    with pytest.raises(OverlayError, match="past \\$FFFF"):
        parse_ovl("*=ffff\n01 02\n")


def test_files(tmp_path):
    (tmp_path / "level.bin").write_bytes(b"\x01\x02")
    (tmp_path / "table.prg").write_bytes(b"\x00\xc0\x09\x08")
    (tmp_path / "zp.ovl").write_text("*=fb\n10 20\n")
    entries = [{"file": "level.bin", "address": 0x2000}, {"file": "table.prg"}, {"file": "zp.ovl"}]
    assert load_all(tmp_path, entries) == [(0x2000, b"\x01\x02"), (0xC000, b"\x09\x08"), (0xFB, b"\x10\x20")]
    with pytest.raises(OverlayError, match="needs an address"):
        load(tmp_path, {"file": "level.bin"})
    with pytest.raises(OverlayError, match="Couldn't read"):
        load(tmp_path, {"file": "gone.bin", "address": 0})
    assert [describe(e) for e in entries] == ["at $2000", "at its load address", "overlay: its addresses"]


@pytest.mark.skipif(not (os.environ.get("L64S_VICE_TESTS") == "1" and shutil.which("x64sc")),
                    reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_a_transcript_sees_the_memory(tmp_path):
    from l64s.project.model import load_project
    (tmp_path / "t.asm").write_text("*=$0801\n        byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00\n"
                                    "*=$080d\nstart   lda $c000\n        rts\n")
    (tmp_path / "data.ovl").write_text("*=c000\n42 43\n")
    p = load_project(tmp_path / "t.asm")
    proj = tmp_path / "t.l64proj"
    p.path = proj
    p.debug_memory = [{"file": "data.ovl"}]
    p.save()
    (tmp_path / "t.transcript").write_text("call start\ncheck a = 42\ncheck $c001 = 43\n")
    out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(proj), str(tmp_path / "t.transcript"),
                          "--vice-args=-sounddev dummy"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and "2 checks passed, 0 failed" in out.stdout, out.stdout
