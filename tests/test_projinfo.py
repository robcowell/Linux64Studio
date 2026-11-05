from pathlib import Path

from l64s.projinfo import collect
from l64s.symindex import scan

CBM = """\
SCREEN = $0400      ; the screen
defm SETBORDER
        lda #/1
        sta $d020
        endm
start   lda #0
@loop   sta SCREEN,x
        inx
        bne @loop
        rts
"""

KICK = """\
.const BORDER = $d020
.var count = 3
.macro Wait(n) {
}
.function double(x) { .return x * 2 }
main:
    rts
.label SPRITES = $07f8
"""

BASIC = """10 sc=0:for i=1 to 10
20 score=score+i:next
30 input "name";n$
"""


def syms(text, file, kick=False):
    return [s for s, _scope in scan(text, file, kick)]


def test_cbm_file_by_tab(tmp_path):
    f = str(tmp_path / "main.asm")
    info = collect(syms(CBM, f), project_dir=tmp_path)
    [labels] = info["labels"]
    assert labels.title == "main.asm"
    assert [(i.name, i.line, i.local) for i in labels.items] == [("start", 6, False), ("@loop", 7, True)]
    [vars_] = info["variables"]
    assert [(i.name, i.detail) for i in vars_.items] == [("SCREEN", "$0400")]
    assert [i.name for i in info["macros"][0].items] == ["SETBORDER"]


def test_label_values_from_the_last_build(tmp_path):
    f = str(tmp_path / "main.asm")
    info = collect(syms(CBM, f), project_dir=tmp_path, value_of=lambda s: 0x0810 if s.name == "start" else None)
    assert [i.detail for i in info["labels"][0].items] == ["$0810", ""]


def test_kick_file(tmp_path):
    f = str(tmp_path / "Code" / "game.asm")
    info = collect(syms(KICK, f, kick=True), project_dir=tmp_path)
    assert info["labels"][0].title == str(Path("Code") / "game.asm")
    assert [i.name for i in info["labels"][0].items] == ["main", "SPRITES"]
    assert [(i.name, i.detail) for i in info["variables"][0].items] == [("BORDER", "$d020"), ("count", "3")]
    assert [(i.name, i.detail) for i in info["macros"][0].items] == [("Wait", ""), ("double", "function")]


def test_basic_variables_and_file_order(tmp_path):
    a, b = str(tmp_path / "b.asm"), str(tmp_path / "a.bas")
    info = collect(syms("x = 1\n", a), {b: BASIC}, project_dir=tmp_path)
    assert [g.title for g in info["variables"]] == ["a.bas", "b.asm"]
    bas = info["variables"][0].items
    assert [(i.name, i.line) for i in bas] == [("I", 1), ("SC", 1), ("N$", 3)]   # SCORE is SC on the C64
    assert bas[2].detail == "string"
    assert info["labels"] == [] and info["macros"] == []


def test_half_typed_basic_doesnt_fail(tmp_path):
    info = collect([], {str(tmp_path / "x.bas"): '10 print "unclosed\n20 goto'}, project_dir=tmp_path)
    assert isinstance(info["variables"], list)
