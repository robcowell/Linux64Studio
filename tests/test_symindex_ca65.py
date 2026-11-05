from pathlib import Path

from l64s.symindex import SymbolIndex, include_at, scan_ca65

SRC = """; fast routines for the C program
        .include "zeropage.inc"
        .export _border, _fill
        .import _twice
SCREEN  = $0400
COUNT   := 40
step    .set 1
        .define WIDTH 40
        .macro  poke addr, value
        lda #value
        sta addr
        .endmacro
        .enum   colour
        BLACK
        WHITE = 1
        .endenum

.proc _border
        sta $d020
        rts
.endproc

_fill:  ldy #0
@loop:  sta SCREEN,y
        iny
        bne @loop
:       dex
        bne :-
        jsr _twice
        rts
"""


def test_scan():
    syms = [(s.name, s.kind, s.line, scope) for s, scope in scan_ca65(SRC, "fast.s")]
    assert syms == [("SCREEN", "const", 5, ""), ("COUNT", "const", 6, ""), ("step", "var", 7, ""),
                    ("WIDTH", "const", 8, ""), ("poke", "macro", 9, ""), ("colour", "namespace", 13, ""),
                    ("BLACK", "const", 14, ""), ("WHITE", "const", 15, ""), ("_border", "label", 18, ""),
                    ("_fill", "label", 23, ""), ("@loop", "local", 24, "_fill")]


def index(tmp_path, ca65=True):
    (tmp_path / "fast.s").write_text(SRC)
    (tmp_path / "util.c").write_text("int twice(int x) {\n    return x * 2;\n}\n")
    idx = SymbolIndex()
    idx.update([tmp_path / "fast.s", tmp_path / "util.c"], kickass=False, ca65=ca65)
    return idx, str(tmp_path / "fast.s")


def test_definitions(tmp_path):
    idx, f = index(tmp_path)
    assert [(s.name, s.line) for s in idx.definitions("@loop", f, 26)] == [("@loop", 24)]
    assert [(s.name, s.line) for s in idx.definitions("SCREEN", f, 24)] == [("SCREEN", 5)]
    assert idx.definitions("screen", f, 24) == []                      # ca65 names are case-sensitive
    assert [(Path(s.file).name, s.line) for s in idx.definitions("_twice", f, 29)] == [("util.c", 1)]


def test_completions_offer_ca65_directives(tmp_path):
    idx, f = index(tmp_path)
    got = {t: w for t, w, _s in idx.completions(".pro", f)}
    assert got[".proc"] == "ca65 control command"
    assert ".segment" in {t for t, w, _s in idx.completions(".seg", f)}
    assert "incasm" not in {t for t, w, _s in idx.completions("inc", f)}           # CBM's, not ca65's
    assert "SCREEN" in {t for t, w, _s in idx.completions("SCR", f)}


def test_outside_c_projects_s_files_stay_cbm(tmp_path):
    idx, f = index(tmp_path, ca65=False)
    assert ".proc" not in {t for t, w, _s in idx.completions(".pro", f)}


def test_include_lines(tmp_path):
    assert include_at('        .include "zeropage.inc"', tmp_path) == (tmp_path / "zeropage.inc").resolve()
    assert include_at('        .incbin "font.bin"', tmp_path) == (tmp_path / "font.bin").resolve()


def test_unchanged_files_arent_rescanned(tmp_path):
    idx, f = index(tmp_path)
    before = idx._files[str(Path(f).resolve())]
    idx.update([tmp_path / "fast.s", tmp_path / "util.c"], kickass=False, ca65=True)
    assert idx._files[str(Path(f).resolve())] is before
