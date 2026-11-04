"""The symbol index behind Go to Definition and auto-complete."""
import shutil
import subprocess
from pathlib import Path

import pytest

from l64s.symindex import SymbolIndex, basic_target, include_at, looks_like_kick, scan, word_at

BOOK = Path(__file__).resolve().parent / "book" / "c64edition-main"
GAME = Path.home() / "code" / "calvin-hobbes-c64"
JAR = Path.home() / ".local/share/linux64studio/KickAssembler/KickAss.jar"

CBM = """; a comment with label: in it
SCREEN  = $0400
NUMBER equ 5
        defm  ADD8
        lda /1
        endm
start   ldx #0
@loop   inx
        bne @loop
main:   jsr start ; call
@loop   rts
lda_table byte 1
        lda #0
"""

KICK = """.const SCREEN = $0400
.var count = 3
.label border = $d020
.macro print_at(text, row) {
}
.function double(x) {
    .return x * 2
}
.pseudocommand mov src : dst {
}
.namespace sound {
play:   rts
}
start:  ldx #0
!loop:  inx
        jmp start
"""


def names(syms):
    return [(s.name, s.kind, s.line) for s, _scope in syms]


def test_scan_cbm():
    assert names(scan(CBM)) == [("SCREEN", "const", 2), ("NUMBER", "const", 3), ("ADD8", "macro", 4),
                                ("start", "label", 7), ("@loop", "local", 8), ("main", "label", 10),
                                ("@loop", "local", 11), ("lda_table", "label", 12)]


def test_scan_kick():
    assert names(scan(KICK, kickass=True)) == [
        ("SCREEN", "const", 1), ("count", "var", 2), ("border", "label", 3), ("print_at", "macro", 4),
        ("double", "function", 6), ("mov", "macro", 9), ("sound", "namespace", 11), ("play", "label", 12),
        ("start", "label", 14)]
    assert looks_like_kick(KICK) and not looks_like_kick(CBM)


def test_definitions(tmp_path):
    a, b = tmp_path / "a.asm", tmp_path / "b.asm"
    a.write_text(CBM)
    b.write_text("start   rts\nother   jmp START\n")
    idx = SymbolIndex()
    idx.update([a, b])
    assert [(Path(s.file).name, s.line) for s in idx.definitions("START", str(b))] == [("b.asm", 1), ("a.asm", 7)]
    assert [(Path(s.file).name, s.line) for s in idx.definitions("start", str(a))] == [("a.asm", 7), ("b.asm", 1)]
    assert [s.line for s in idx.definitions("@loop", str(a), 9)] == [8]          # the one under start
    assert [s.line for s in idx.definitions("@loop", str(a), 11)] == [11]        # the one under main
    assert idx.definitions("add8") == [] and idx.definitions("ADD8")[0].line == 4   # macros keep their case
    assert idx.definitions("nothing") == []
    # unsaved text wins over the file
    idx.update([a, b], {str(b): "renamed rts\n"})
    assert idx.definitions("renamed")[0].file == str(b.resolve())
    idx.update([a])
    assert idx.definitions("renamed") == []


def test_kick_definitions(tmp_path):
    k = tmp_path / "k.asm"
    k.write_text(KICK)
    idx = SymbolIndex()
    idx.update([k], kickass=True)
    assert idx.definitions("sound.play", str(k))[0].line == 12
    assert idx.definitions("Start", str(k)) == []                                # Kick is case-sensitive
    assert [c[0] for c in idx.completions("co", str(k))][:2] == ["count", "const"]


def test_completions(tmp_path):
    a = tmp_path / "a.asm"
    a.write_text(CBM)
    (tmp_path / "b.asm").write_text("startgame rts\n")
    idx = SymbolIndex()
    idx.update([a, tmp_path / "b.asm"])
    got = idx.completions("sta", str(a))
    assert [t for t, _w, _s in got][:2] == ["start", "startgame"]       # "sta" is what was typed
    assert got[0][1] == "label · a.asm:7"
    assert ("stx", "instruction", None) in idx.completions("st", str(a))
    assert "SCREEN" in [t for t, _w, _s in idx.completions("scr", str(a))]
    assert "repeat" in [t for t, _w, _s in idx.completions("rep", str(a))]
    assert [t for t, _w, _s in idx.completions("got", basic=True)] == ["goto"]
    assert idx.completions("") == []


def test_word_at():
    assert word_at("        jsr gameFlowUpdate ; x", 15)[2] == "gameFlowUpdate"
    assert word_at("        bne @loop", 14)[2] == "@loop"
    assert word_at("        lda #<SCREEN+40", 17)[2] == "SCREEN"
    assert word_at("        lda $c000", 13)[2] == ""
    assert word_at("    .const X = 1", 6)[2] == "const"
    assert word_at("    jmp sound.play", 12)[2] == "sound.play"


def test_include_at(tmp_path):
    assert include_at('        incasm "libScreen.asm"', tmp_path) == tmp_path / "libScreen.asm"
    assert include_at("        incbin sprites.bin, 2", tmp_path) == tmp_path / "sprites.bin"
    assert include_at('#import "game/player.asm"', tmp_path) == tmp_path / "game" / "player.asm"
    assert include_at('    .import binary "../gfx/chars.bin"', tmp_path) == (tmp_path / "../gfx/chars.bin").resolve()
    assert include_at("        lda #1", tmp_path) is None


def test_basic_target():
    src = "10 print 1\n20 goto 10\n30 on x gosub 10,20\n"
    assert basic_target(src, 2, 8) == 1
    assert basic_target(src, 3, 18) == 2
    assert basic_target(src, 1, 3) is None
    pb = "@top\nprint 1\ngoto @top\n"
    assert basic_target(pb, 3, 7) == 1


@pytest.mark.skipif(not BOOK.exists(), reason="book downloads not in tests/book")
def test_every_book_label_is_found():
    from l64s.asm.assembler import Assembler, Options
    from l64s.project.model import load_project
    for prj in sorted(BOOK.rglob("*.cbmprj")):
        proj = load_project(prj)
        r = Assembler(Options()).assemble_files(proj.build_paths())
        idx = SymbolIndex()
        idx.update(proj.build_paths(), kickass=False)
        for key, loc in r.label_locs.items():
            if "__m" in key:
                continue
            name = r.names.get(key, key).split("::")[-1]
            if "@" in name:
                name = "@" + name.split("@", 1)[1]
            assert any(Path(s.file) == Path(loc.file).resolve() and s.line == loc.line
                       for s in idx.definitions(name, loc.file, loc.line)), (prj.name, name)


@pytest.mark.skipif(not (GAME.exists() and JAR.exists() and shutil.which("java")),
                    reason="needs ~/code/calvin-hobbes-c64 and Kick Assembler 5")
def test_every_kick_label_is_found(tmp_path):
    """Against the labels in Kick Assembler's own debug dump (built from a copy of the game)."""
    from l64s import kickdbg
    copy = tmp_path / "game"
    shutil.copytree(GAME, copy, ignore=shutil.ignore_patterns(".git", "*.prg", "*.d64", "*.exo"))
    subprocess.run(["java", "-jar", str(JAR), "game.asm", "-debugdump", "-o", "g.prg"], cwd=copy,
                   check=True, capture_output=True)
    info = kickdbg.parse(copy / "g.dbg", copy)
    idx = SymbolIndex()
    idx.update(sorted({Path(f) for _a, _n, f, _l in info.labels if f}), kickass=True)
    found = [any(s.file == str(Path(f).resolve()) and s.line == line for s in idx.definitions(name, f, line))
             for _a, name, f, line in info.labels if f]
    assert len(found) > 200 and all(found)
