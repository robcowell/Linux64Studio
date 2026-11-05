from pathlib import Path

from l64s.symindex import SymbolIndex, c_include_at, c_word_at

MAIN = """#include <conio.h>
#include "util.h"
#define LIMIT 3
int total;
static unsigned char count;
int main(void) {
    int i;
    int step = 2;
    for (i = 0; i < LIMIT; i += step) {
        total += twice(i);
    }
    return 0;
}
"""
UTIL_H = "#ifndef UTIL_H\n#define UTIL_H\ntypedef unsigned char byte;\nint twice(int x);\nextern int total;\n#endif\n"
UTIL_C = '#include "util.h"\nint twice(int x) {\n    int y = x * 2;\n    return y;\n}\n'
ASM = "        .import _twice\n        jsr _twice\n"


def index(tmp_path):
    for name, text in (("main.c", MAIN), ("util.h", UTIL_H), ("util.c", UTIL_C), ("fast.s", ASM)):
        (tmp_path / name).write_text(text)
    idx = SymbolIndex()
    idx.update([tmp_path / n for n in ("main.c", "util.h", "util.c", "fast.s")])
    return idx


def where(syms):
    return [(Path(s.file).name, s.line, s.kind) for s in syms]


def test_definitions_prefer_the_body_and_this_function(tmp_path):
    idx = index(tmp_path)
    main = str(tmp_path / "main.c")
    assert where(idx.definitions("twice", main, 10))[:2] == [("util.c", 2, "c-function"), ("util.h", 4, "c-prototype")]
    assert where(idx.definitions("total", main, 10))[:2] == [("main.c", 4, "c-variable"), ("util.h", 5, "c-extern")]
    assert where(idx.definitions("i", main, 10)) == [("main.c", 7, "c-local")]
    assert idx.definitions("i", main, 2) == []                       # outside main(): no i
    assert where(idx.definitions("LIMIT", main, 9)) == [("main.c", 3, "c-macro")]
    assert where(idx.definitions("byte", main, 9)) == [("util.h", 3, "c-typedef")]
    assert where(idx.definitions("x", str(tmp_path / "util.c"), 3)) == [("util.c", 2, "c-param")]
    assert idx.definitions("Total", main, 10) == []                   # C is case-sensitive


def test_assembler_calling_c(tmp_path):
    idx = index(tmp_path)
    assert where(idx.definitions("_twice", str(tmp_path / "fast.s"), 2)) == [("util.c", 2, "c-function")]


def test_completions_in_c(tmp_path):
    idx = index(tmp_path)
    main = str(tmp_path / "main.c")
    got = {t: w for t, w, _s in idx.completions("t", main, from_line=10)}
    assert got["total"].startswith("variable · main.c") and got["twice"].startswith("function")
    assert got["typedef"] == "C keyword" and "tax" not in got                  # no 6502 instructions
    assert [t for t, w, _s in idx.completions("st", main, from_line=10)][:1] == ["step"]   # the local first
    assert "step" not in [t for t, w, _s in idx.completions("st", main, from_line=2)]
    asm = {t for t, w, _s in idx.completions("tw", str(tmp_path / "fast.s"))}
    assert "twice" not in asm                                                    # C names stay in C


def test_words_and_includes(tmp_path):
    assert c_word_at("    total += twice(i);", 16) == (13, 18, "twice")
    assert c_word_at("a->next.x", 4) == (3, 7, "next")
    assert c_word_at("x = 42;", 5)[2] == ""
    (tmp_path / "util.h").write_text("")
    sys_dir = tmp_path / "sys"
    sys_dir.mkdir()
    (sys_dir / "conio.h").write_text("")
    assert c_include_at('#include "util.h"', tmp_path, [sys_dir]) == (tmp_path / "util.h").resolve()
    assert c_include_at("#include <conio.h>", tmp_path, [sys_dir]) == (sys_dir / "conio.h").resolve()
    assert c_include_at("int x;", tmp_path, [sys_dir]) is None


def test_completion_isnt_switched_off_after_a_semicolon_in_c():
    from l64s.ui.completion import _in_comment_or_string
    assert _in_comment_or_string("lda #0 ; a comment")                  # assembler
    assert not _in_comment_or_string("for (i = 0; i < LIM", c=True)
    assert _in_comment_or_string("x = 1; // a comment", c=True)
    assert _in_comment_or_string("x = 1; /* still in it", c=True)
    assert not _in_comment_or_string("x = 1; /* closed */ tot", c=True)


def test_project_information_for_c(tmp_path):
    from l64s.projinfo import collect
    idx = index(tmp_path)
    info = collect(idx.symbols(), project_dir=tmp_path, value_of=lambda s: {"main": 0x80D, "total": 0x990}.get(s.name))
    by_tab = {k: [(g.title, [(i.name, i.detail) for i in g.items]) for g in v] for k, v in info.items()}
    assert ("main.c", [("main", "$080D")]) in by_tab["labels"] and ("util.c", [("twice", "")]) in by_tab["labels"]
    assert by_tab["variables"] == [("main.c", [("total", "$0990"), ("count", "")])]
    assert ("main.c", [("LIMIT", "3")]) in by_tab["macros"]
    assert ("util.h", [("UTIL_H", ""), ("byte", "typedef")]) in by_tab["macros"]
