"""pBASIC, following CBM prg Studio's help page and tutorial 17 (the examples are theirs)."""
import os
import time

import pytest

from l64s.basic.pbasic import (PBasicOptions, create_label, from_basic, jump_target_at, label_refs,
                               remove_line_numbers, to_basic)
from l64s.basic.tokenizer import BasicError, BasicErrors, tokenize

COLOUR_BARS = """REM AUTOMATIC COLOR BARS
PRINT CHR$(147): REM CLR/HOME
@loop
PRINT CHR$(18); "     ";: REM REVERSE BAR
CL = INT(8*RND(1))+1
ON CL GOTO @col1,@col2,@col3,@col4,@col5,@col6,@col7,@col8
@col1
PRINT CHR$(5);: GOTO @loop
@col2
PRINT CHR$(28);: GOTO @loop
@col3
PRINT CHR$(30);: GOTO @loop
@col4
PRINT CHR$(31);: GOTO @loop
@col5
PRINT CHR$(144);: GOTO @loop
@col6
PRINT CHR$(156);: GOTO @loop
@col7
PRINT CHR$(158);: GOTO @loop
@col8
PRINT CHR$(159);: GOTO @loop
"""

TUTORIAL = """10 rem pbasic demo
20 print "hello from pbasic"
30 for a = 1 to 5
40 gosub 100
50 gosub 200
60 gosub 300
70 next a
80 end
100 print "subroutine 1"
110 return
200 print "subroutine 2"
210 return
300 print "subroutine 3"
310 return
"""

TUTORIAL_PBASIC = """rem pbasic demo
print "hello from pbasic"
for a = 1 to 5
gosub @sub1
gosub @sub2
gosub @sub3
next a
end
@sub1
print "subroutine 1"
return
@sub2
print "subroutine 2"
return
@sub3
print "subroutine 3"
return
"""


def test_colour_bars():
    r = to_basic(COLOUR_BARS)
    lines = r.text.splitlines()
    assert lines[0] == "10 REM AUTOMATIC COLOR BARS"
    assert lines[2] == '30 PRINT CHR$(18); "     ";: REM REVERSE BAR'
    assert lines[4] == "50 ON CL GOTO 60,70,80,90,100,110,120,130"
    assert lines[5] == "60 PRINT CHR$(5);: GOTO 30"
    assert r.labels["loop"] == 30 and r.labels["col8"] == 130
    tokenize(r.text)


def test_start_step_and_prefix():
    r = to_basic(COLOUR_BARS.replace("@", "!"), PBasicOptions(start=1000, step=5, prefix="!"))
    assert r.text.splitlines()[4] == "1020 ON CL GOTO 1025,1030,1035,1040,1045,1050,1055,1060"
    with pytest.raises(BasicErrors):
        to_basic("print", PBasicOptions(prefix="a"))
    with pytest.raises(BasicErrors) as e:
        to_basic("print\n" * 10, PBasicOptions(start=63990, step=10))
    assert "line 64080, above 63999" in e.value.errors[0].message


def test_namespaces():
    src = """@loop
print "hello"
goto @loop
namespace block1
@loop
print "block1"
goto @loop
namespace end
namespace block2
@loop
print "block2"
goto @loop
namespace end
"""
    assert to_basic(src).text == '10 print "hello"\n20 goto 10\n30 print "block1"\n40 goto 30\n' \
                                 '50 print "block2"\n60 goto 50\n'
    # Linux64Studio's additions: reaching a global label, and naming another block's label
    r = to_basic('@top\nprint 1\nnamespace a\n@x\ngoto @top\nnamespace end\ngoto @a.x\n')
    assert r.text == "10 print 1\n20 goto 10\n30 goto 20\n"
    assert r.labels == {"top": 10, "a.x": 20}


def test_labels_in_strings_rem_and_data_are_text():
    r = to_basic('@a\nprint "@a": rem goto @nowhere\ndata @x, 1: goto @a\n')
    assert r.text == '10 print "@a": rem goto @nowhere\n20 data @x, 1: goto 10\n'
    assert label_refs('print "@a";@b') == [(11, 13, "b")]
    assert to_basic("@Loop\ngoto @LOOP\n").text == "10 goto 10\n"       # any case


def test_errors_give_the_pbasic_line():
    def errs(src):
        with pytest.raises(BasicErrors) as e:
            to_basic(src)
        return [(x.line, x.message) for x in e.value.errors]
    assert errs("print\ngoto @nowhere") == [(2, "There's no label @nowhere")]
    (line, msg), = errs("@a\nprint\n@a\nprint")
    assert line == 3 and "twice" in msg
    (line, msg), = errs("print\n@end")
    assert line == 2 and "no line after" in msg
    (line, msg), = errs("@loop print 1")
    assert line == 1 and "own" in msg
    (line, msg), = errs("print\n20 goto 10")
    assert line == 2 and "Remove Line Numbers" in msg
    assert any("no 'namespace end'" in m for _l, m in errs("namespace a\nprint"))
    assert any("no label @x in namespace b" in m for _l, m in errs("namespace a\n@x\nprint\nnamespace end\n"
                                                                    "namespace b\ngoto @x\nnamespace end"))
    r = to_basic("\n\nprint\n\n@x\ngoto @x")
    assert r.source_lines == [3, 6] and r.source_line(2) == 6


def test_tutorial_17():
    text, n = create_label(TUTORIAL, 100, "sub1")
    assert n == 1
    text, _ = create_label(text, 200, "sub2")
    text, _ = create_label(text, 300, "sub3")
    assert "40 gosub @sub1\n" in text and "80 end\n@sub1\n100 print" in text
    text, warnings = remove_line_numbers(text)
    assert text == TUTORIAL_PBASIC and warnings == []
    assert to_basic(text).text.splitlines()[3] == "40 gosub 90"
    tokenize(to_basic(text).text)


def test_create_label_details():
    src = "10 goto 30\n20 on x goto 30,30\n30 end\n"
    text, n = create_label(src, 30, "fin")
    assert n == 3 and text == "10 goto @fin\n20 on x goto @fin,@fin\n@fin\n30 end\n"
    assert create_label(text, 30, "fin") == (text, 0)                   # again: nothing new
    with pytest.raises(BasicError, match="no line 40"):
        create_label(src, 40, "x")
    with pytest.raises(BasicError, match="another line"):
        create_label(text, 10, "fin")
    with pytest.raises(BasicError, match="isn't a label"):
        create_label(src, 30, "2x")
    assert jump_target_at("20 on x goto 30,40", 16) == 40
    assert jump_target_at("20 on x goto 30,40", 4) is None


def test_remove_line_numbers_warnings():
    text, warnings = remove_line_numbers("10 print\n20 goto 10\n")
    assert text == "print\ngoto 10\n"
    assert "No labels" in warnings[0].message and warnings[1].line == 2


def test_from_basic():
    text, warnings = from_basic(TUTORIAL + "320 goto 999\n")
    assert text.startswith("rem pbasic demo\n") and "gosub @line100\n" in text and "@line100\nprint" in text
    assert warnings[0].message == "Line 320 jumps to line 999, which doesn't exist"
    assert to_basic(text).text.count("\n") == 15


def test_build(tmp_path):
    """A pBASIC file in a project builds like a BASIC one, errors pointing at the pBASIC line."""
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "t.pbas").write_text(TUTORIAL_PBASIC)
    p = Project(path=tmp_path / "t.l64proj", name="t", build_list=["t.pbas"], executable="t.prg")
    res = build_project(p)
    assert res.ok, res.log
    from l64s.basic.tokenizer import detokenize
    assert "40 gosub 90" in detokenize(res.prg.read_bytes())
    assert res.basic_preview and res.basic_preview[0][1].startswith("10 rem pbasic demo")
    res = build_project(p, pbasic=PBasicOptions(start=100, step=1))
    assert "103 gosub 108" in detokenize(res.prg.read_bytes())
    (tmp_path / "t.pbas").write_text("print\n\ngosub @nope\n")
    res = build_project(p)
    assert not res.ok
    (d,) = [d for d in res.diagnostics if d.severity == "error"]
    assert d.loc.line == 3 and "@nope" in d.message
    (tmp_path / "t.pbas").write_text("print\n\n" + "print 1234567890:" * 20 + "\n")   # too long
    res = build_project(p)
    assert not res.ok and [d.loc.line for d in res.diagnostics if d.severity == "error"] == [3]
    if os.environ.get("L64S_VICE_TESTS") == "1":
        (tmp_path / "t.pbas").write_text(TUTORIAL_PBASIC)
        assert "subroutine 3" in _run(build_project(p).prg)


def _run(prg) -> str:
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    port = free_port()
    proc = launch(prg, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy", "+saveres"])
    try:
        assert wait_for_port(port)
        m = BinaryMonitor()
        m.connect(port=port)
        text = ""
        for _ in range(30):
            m.resume()
            time.sleep(0.5)
            screen = m.read_memory(0x0400, 0x07E7)
            text = "".join(chr(c + 96) if 1 <= c <= 26 else chr(c) if 32 <= c < 64 else " " for c in screen)
            if text.count("subroutine 3") == 5:
                break
        m.quit()
        return text
    finally:
        proc.terminate()
        proc.wait(5)


def test_cli(tmp_path, capsys):
    from l64s.basic.cli import main
    src = tmp_path / "t.pbas"
    src.write_text(TUTORIAL_PBASIC)
    assert main(["--preview", "--start", "100", "--step", "1", str(src)]) == 0
    assert capsys.readouterr().out.splitlines()[3] == "103 gosub 108"
    assert main([str(src)]) == 0 and (tmp_path / "t.prg").exists()
    src.write_text("print\n\n" + "print 1234567890:" * 20 + "\ngoto @x\n")
    assert main([str(src)]) == 1
    assert f"{src}:4: error: There's no label @x" in capsys.readouterr().err
    src.write_text("print\n\n" + "print 1234567890:" * 20 + "\n")
    assert main([str(src)]) == 1
    assert f"{src}:3: error: Line 20 is too long" in capsys.readouterr().err
