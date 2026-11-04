import csv
import os
from pathlib import Path

import pytest

from l64s.analyser import Report, cycles, from_listing, from_text, opcode, to_html, to_text
from l64s.asm.assembler import Assembler, Options
from l64s.asm.opcodes import OPCODES

BOOK = Path(__file__).parent / "book" / "c64edition-main" / "Chapters" / "chapter17"


def test_cycle_rules():
    assert cycles("lda", "imm") == (2, 2)
    assert cycles("lda", "abx") == (4, 5)          # +1 when a page is crossed
    assert cycles("sta", "abx") == (5, 5)          # stores always take the extra cycle
    assert cycles("lda", "izy") == (5, 6)
    assert cycles("inc", "abx") == (7, 7)
    assert cycles("bne", "rel") == (2, 4)
    assert cycles("jsr", "abs") == (6, 6) and cycles("rts", "imp") == (6, 6)
    assert cycles("jmp", "ind") == (5, 5) and cycles("jmp", "abs") == (3, 3)
    assert cycles("pla", "imp") == (4, 4)


def test_every_opcode_has_cycles():
    for m, modes in OPCODES.items():
        for mode in modes:
            b, x = cycles(m, mode)
            assert 2 <= b <= x <= 8, (m, mode)


@pytest.mark.skipif(not os.environ.get("L64S_CBM_CYCLES"), reason="set L64S_CBM_CYCLES to CBM prg Studio's "
                                                                   "6502_opcodes_cycles.csv")
def test_cycles_match_cbm_prg_studio():
    names = {"Immediate": "imm", "ZeroPage": "zp", "ZeroPage,X": "zpx", "ZeroPage,Y": "zpy", "Absolute": "abs",
             "Absolute,X": "abx", "Absolute,Y": "aby", "(Indirect,X)": "izx", "(Indirect),Y": "izy",
             "(Indirect)": "ind", "Implied": "imp", "Accumulator": "acc", "Relative": "rel"}
    with open(os.environ["L64S_CBM_CYCLES"], encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter=";"):
            m, mode = row["Mnemonic"].lower(), names[row["Mode"]]
            if opcode(m, mode) is None:
                mode = {"imp": "acc", "acc": "imp"}[mode]
            assert opcode(m, mode) == int(row["Opcode"], 16)
            assert cycles(m, mode) == (int(row["BaseCycles"]), int(row["MaxCycles"])), row


SOURCE = """\
        defm CLEAR
        lda #0
        sta /1
        endm
*=$c000
start   CLEAR border
        CLEAR $D021
        ldx #0
loop    lda table,x
        sta $0400,x
        inx
        bne loop
        jsr sub
        rts
sub     ldy border
        rts
border  = $FB
table   byte 1,2,3
"""


def _listing(tmp_path, text=SOURCE):
    p = tmp_path / "main.asm"
    p.write_text(text)
    res = Assembler(Options()).assemble_files([p])
    assert res.ok, res.diagnostics
    return p, res.listing


def test_from_listing(tmp_path):
    p, listing = _listing(tmp_path)
    instrs = from_listing(listing)
    assert len(instrs) == 13                                   # 2 macros x 2, then 9; the byte line isn't code
    first = instrs[1]
    assert (first.mnemonic, first.mode, first.line) == ("sta", "zp", 6)   # counted at the macro's call
    assert any(i.mnemonic == "ldy" and i.mode == "zp" for i in instrs)    # forward reference to zero page
    assert {i.mode for i in instrs if i.mnemonic == "sta"} == {"zp", "abs", "abx"}
    lines = from_listing(listing, {str(p.resolve()): (9, 12)})
    assert [i.mnemonic for i in lines] == ["lda", "sta", "inx", "bne"]


def test_report(tmp_path):
    _, listing = _listing(tmp_path)
    r = Report(from_listing(listing), files=["main.asm"])
    m = dict(r.metrics())
    assert m["Instructions"] == "13"
    assert m["Subroutine calls"] == "1" and m["Returns"] == "2"
    assert m["Most used instruction"] == "LDA (3)" or m["Most used instruction"].startswith("STA")
    base = sum(i.cycles[0] for i in r.instrs)
    assert m["Estimated base cycles"] == str(base)
    assert r.by_category()["Load / Store"] == 8
    text = to_text(r)
    assert "Estimated base cycles" in text and "LDA" in text
    page = to_html(r)
    assert page.startswith("<!doctype html>") and "<td>STA</td>" in page


def test_from_text_kickass():
    src = """\
    .const SCREEN = $0400
!loop:  lda table,x     // a comment
        sta SCREEN,x
        lda $02
        lda.abs $02
        inc zp1
        jmp ($fffc)
        bne !loop-
        lda ($fb),y
        lsr
        rts
table: .byte 1,2,3
/* lda #1
   sta $d020 */
"""
    instrs, bad = from_text(src, "x.asm", symbols={"zp1": 0x10})
    assert not bad
    modes = [(i.mnemonic, i.mode) for i in instrs]
    assert modes == [("lda", "abx"), ("sta", "abx"), ("lda", "zp"), ("lda", "abs"), ("inc", "zp"),
                     ("jmp", "ind"), ("bne", "rel"), ("lda", "izy"), ("lsr", "acc"), ("rts", "imp")]


def test_from_text_cbm_and_invalid():
    instrs, bad = from_text("loop    lda #1\n        jmp (ptr),y\n        stx $10,x\n", "c.asm")
    assert [(i.mnemonic, i.mode) for i in instrs] == [("lda", "imm")]
    assert len(bad) == 2 and bad[0].line == 2


@pytest.mark.skipif(not BOOK.exists(), reason="book sources not present")
def test_book_project():
    from l64s.project.build import build_project
    from l64s.project.model import load_project
    proj = load_project(BOOK / "chapter17.cbmprj")
    res = build_project(proj)
    assert res.ok
    r = Report(from_listing(res.asm_result.listing), files=[str(f) for f in proj.build_list])
    m = dict(r.metrics())
    assert int(m["Instructions"]) > 500
    assert int(m["Files analysed"]) == len(proj.build_list)
    assert r.by_file()                     # every instruction is in a real file
    for f in r.by_file():
        assert Path(f).exists()


def test_analyse_scopes(tmp_path):
    from l64s.analyser import analyse
    p, _ = _listing(tmp_path)
    lib = tmp_path / "lib.asm"
    lib.write_text("*=$c100\nlibsub  lda border\n        rts\n")
    whole = analyse([p, lib])
    assert len(whole.instrs) == 15 and whole.method == "assembled"
    just_lib = analyse([p, lib], scope=lib)
    assert [(i.mnemonic, i.mode) for i in just_lib.instrs] == [("lda", "zp"), ("rts", "imp")]   # border is from main
    sel = analyse([p, lib], scope=p, lines=(9, 10))
    assert [i.mnemonic for i in sel.instrs] == ["lda", "sta"]
    unsaved = analyse([p, lib], overrides={str(lib): "*=$c100\n        nop\n"}, scope=lib)
    assert [i.mnemonic for i in unsaved.instrs] == ["nop"]
    broken = analyse([p], overrides={str(p): "*=$c000\n        lda nosuchlabel\n"})
    assert broken.method.startswith("source text (it doesn't assemble")
    assert [(i.mnemonic, i.mode) for i in broken.instrs] == [("lda", "abs")]
    kick = analyse([p], kickass=True)
    assert kick.method == "source text"


def test_constants_and_imports(tmp_path):
    from l64s.analyser import analyse, constants, kickass_sources
    assert constants(".const ZP = $fb\n.label Other = 2000\nScreen = $0400 // c\nX equ 5\nnotone = foo\n") == {
        "zp": 0xFB, "other": 2000, "screen": 0x400, "x": 5}
    lib = tmp_path / "Library"
    lib.mkdir()
    (lib / "libStuff.asm").write_text("#importonce\n.const PTR = $fb\nlibsub: lda (PTR),y\n    rts\n")
    main = tmp_path / "code" / "main.asm"
    main.parent.mkdir()
    main.write_text('#import "../library/libstuff.asm"\n    lda PTR\n    jsr libsub\n')   # written on Windows
    files = kickass_sources(main)
    assert [f.name for f in files] == ["main.asm", "libStuff.asm"]
    r = analyse(files, kickass=True)
    assert [(i.mnemonic, i.mode) for i in r.instrs] == [("lda", "zp"), ("jsr", "abs"), ("lda", "izy"), ("rts", "imp")]


KICK_BOOK = Path(__file__).parent / "book" / "c64edition-main" / "ChaptersKickAss" / "chapter17"


@pytest.mark.skipif(not KICK_BOOK.exists(), reason="book sources not present")
def test_book_kickass_project():
    from l64s.analyser import analyse, kickass_sources
    from l64s.project.model import load_project
    p = load_project(KICK_BOOK / "ch17.code-workspace")
    files = kickass_sources(p.directory / p.main_file, [p.directory / d for d in p.lib_dirs])
    assert len(files) > 10
    r = analyse(files, kickass=True)
    assert not r.invalid and len(r.instrs) > 1000
