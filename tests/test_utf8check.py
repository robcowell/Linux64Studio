"""The UTF-8 check."""
from l64s.utf8check import check_file, check_text, fix


def test_finds_pasted_characters():
    text = "        lda #“A”   ; it’s here – ok…\n﻿loop  jmp loop\n"
    found = check_text(text)
    first = text.splitlines()[0]
    want = [(1, first.index(ch) + 1, ch) for ch in "\u201c\u201d\u2019\u00a0\u2013\u2026"] + [(2, 1, "\ufeff")]
    assert [(f.line, f.column, f.char) for f in found] == want
    assert found[0].describe() == "“  U+201C Left Double Quotation Mark → '\"'"
    assert "(no-break space)" in found[3].describe() and "(remove)" in found[6].describe()
    assert fix(text) == ('        lda #"A"   ; it\'s here - ok...\nloop  jmp loop\n', 7, 0)


def test_basic_keeps_the_c64s_own():
    assert check_text('10 print "£π←↑"\n', basic=True) == []
    assert [f.char for f in check_text('10 print "£"\n')] == ["£"]          # in assembler it's flagged
    assert fix('10 print "£" : rem café\n', basic=True) == ('10 print "£" : rem cafe\n', 1, 0)


def test_what_has_no_ascii():
    found = check_text("x = Ω\n")
    assert found[0].replacement is None and fix("Ω")[2] == 1


def test_files(tmp_path):
    good = tmp_path / "a.asm"
    good.write_text("        rts\n")
    assert check_file(good) == []
    bad = tmp_path / "b.asm"
    bad.write_bytes(b"        rts\n; caf\xe9\n")                          # Windows-1252, not UTF-8
    (f, g) = check_file(bad)
    assert (f.line, f.column, f.char) == (2, 6, "") and "isn't UTF-8" in f.describe()
    assert g.char == "é" and g.replacement == "e"
