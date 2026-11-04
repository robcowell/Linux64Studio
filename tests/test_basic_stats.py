import pytest

from l64s.basic.stats import BASIC_BYTES, BasicErrors, analyse, report

PROG = '''10 score=0 : scale=2 : lives%=3 : n$="bob"
20 dim hi(10),nm$(10)
30 for i=1 to 10 : hi(i)=i*100 : next i
40 input "name";n$ : get k$ : read a,b
50 get#1,c$ : input#1,d
60 if lives%>0 then goto 90
70 print x : st=1 : ti$="000000"
80 data 1,2,hello,zz
90 gosub 200 : rem q=1
100 def fn sq(z)=z*z : y=fn sq(3)
110 print "w=1"
'''


@pytest.fixture(scope="module")
def st():
    return analyse(PROG)


def test_program_size(st):
    assert st.lines == 11 and st.start == 0x0801
    assert st.free == BASIC_BYTES - st.size and st.end == 0x0801 + st.size - 1


def test_assignments(st):
    got = {v.key: (v.first_set, v.how) for v in st.assigned()}
    assert got["LI%"] == (10, "=") and got["N$"] == (10, "=")
    assert got["HI("] == (20, "dim") and got["NM$("] == (20, "dim")
    assert got["I"] == (30, "for")
    assert got["A"] == (40, "read") and got["B"] == (40, "read") and got["K$"] == (40, "get")
    assert got["C$"] == (50, "get#") and got["D"] == (50, "input#")
    assert got["TI$"] == (70, "=") and got["Y"] == (100, "=")
    # strings, DATA and REM aren't code; FN's parameter and the function name aren't variables
    for key in ("W", "ZZ", "HE", "Q", "Z", "SQ"):
        assert key not in st.variables


def test_two_characters_count(st):
    sc = st.variables["SC"]
    assert sc.spellings == ["SC", "SCALE"] and sc in st.duplicates()


def test_never_set(st):
    assert [v.key for v in st.never_set()] == ["E", "X"]


def test_problems(st):
    assert [p.message for p in st.keyword_words] == ["score is read as SC OR E"]
    msgs = [p.message for p in st.problems]
    assert any("ST is the system variable" in m for m in msgs)
    assert not any("TI$" in m and "won't" in m.split(":")[0] for m in msgs)
    assert "Line 90 jumps to line 200, which doesn't exist" in msgs


def test_keywords_in_names():
    st = analyse("10 fort=1 : aandb=2 : heart=3 : total=4\n")
    words = {p.message.split()[0]: p.message for p in st.keyword_words}
    assert "fort" not in words                    # FOR T: the keyword starts the word, as crunched code does
    assert words["aandb"] == "aandb is read as A AND B"
    assert "heart" not in words                   # no keyword in it
    # a keyword at the start of a word is how crunched code is written (FORT=1TO10), so TOTAL isn't flagged
    assert "total" not in words


def test_report(st):
    text = report(st, "game.bas")
    assert text.startswith("BASIC Program Statistics: game.bas")
    assert "Duplicate Variables" in text and "SC = SCALE" in text
    assert "Used but never set" in text and "Names with a keyword inside" in text


def test_bad_program():
    with pytest.raises(BasicErrors):
        analyse("print 1\n")


def _run_basic(text: str, tmp_path) -> list[str]:
    """Run a BASIC program in VICE; returns the screen's text rows (upper case set)."""
    import os
    import time
    if os.environ.get("L64S_VICE_TESTS") != "1":
        pytest.skip("set L64S_VICE_TESTS=1 to run VICE")
    from l64s.basic.tokenizer import tokenize
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    p = tmp_path / "t.prg"
    p.write_bytes(tokenize(text).prg())
    port = free_port()
    proc = launch(p, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy"])
    try:
        assert wait_for_port(port)
        mon = BinaryMonitor()
        mon.connect(port=port)
        rows = []
        for _ in range(30):
            mon.resume()
            time.sleep(0.5)
            screen = mon.read_memory(0x0400, 0x07E7)
            rows = ["".join(chr(c + 64) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else " "
                            for c in screen[r * 40:r * 40 + 40]).rstrip() for r in range(25)]
            if any(r.startswith("READY.") for r in rows[6:]):
                break
        mon.quit()
        return rows
    finally:
        proc.terminate()
        proc.wait(5)


def test_c64_agrees_with_the_statistics(tmp_path):
    # what the statistics say: SCALE and SC are one variable; SCORE is SC OR E; TI can't be set
    prog = "10 scale=7 : print sc\n20 score=5\n"
    st = analyse(prog)
    assert st.variables["SC"].spellings == ["SCALE", "SC"]
    assert [p.message for p in st.keyword_words] == ["score is read as SC OR E"]
    rows = _run_basic(prog, tmp_path)
    assert " 7" in rows                                  # PRINT SC shows SCALE's value
    assert "?SYNTAX  ERROR IN 20" in rows
    assert any("SYNTAX" in r and "30" in r for r in _run_basic("30 ti=5\n", tmp_path))
