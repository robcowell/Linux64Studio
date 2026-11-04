import shutil
import subprocess

import pytest

from l64s.basic.petscii import ControlCodeError, parse_control
from l64s.basic.renumber import find_line_refs, renumber
from l64s.basic.tokenizer import BasicErrors, crunch, detokenize, tokenize

PROGRAM = """\
10 print "hello world"
20 for i=1 to 10 step 2:print i;:next i
30 score=0:total=5:if score>total then 100
50 data 1,2,3,print,goto,"a:b",x:print "after data"
60 rem this has print and goto in it "quoted" ? : for
70 a$=left$(b$,3)+mid$(c$,2,1)+right$(d$,1)
80 input#1,a$:print#1,b:get#2,c$
90 on x goto 100,200,300:on y gosub 400,500
100 go to 20
110 poke 53280,0:poke 53281,peek(53280)and15
120 x=sqr(abs(int(rnd(1)*100)))
130 def fn f(x)=x*x:print fn f(3)
140 print "{clr}{wht}white{down}{rght}{rvon}rev{rvof}"
150 print tab(10)spc(3)"x";
160 if a<>b or a<=b and not c>=d then print"ne"
170 print "UPPER case In String"
180 a=atn(1):b=sin(c)+cos(d)+tan(e)+log(f)+exp(g)
190 sys 49152:wait 198,1:load"x",8,1
210 restore:read a,b:open 1,8,15:close 1
220 verify "x":save "y",8:cont:list:clr:new
230 cmd 4:x=usr(5):y=fre(0)+pos(0):z=len("ab")+val("1")+asc("a")
240 print str$(5)
250 end:stop:return
260 forx=1to9:nextx:ifx=1goto10
270 letmeat=1:print meat
"""


@pytest.mark.skipif(not shutil.which("petcat"), reason="VICE's petcat isn't installed")
def test_matches_vice_petcat(tmp_path):
    src = tmp_path / "p.bas"
    src.write_text(PROGRAM)
    subprocess.run(["petcat", "-w2", "-o", str(tmp_path / "p.prg"), "--", str(src)], check=True,
                   capture_output=True)
    assert tokenize(PROGRAM).prg() == (tmp_path / "p.prg").read_bytes()


def test_rom_crunch_quirks():
    assert crunch("score=1") == b"SC\xb0E\xb21"           # OR inside SCORE, as on a real C64
    assert crunch("?a") == b"\x99A"                         # ? is PRINT
    assert crunch('print "print"') == b'\x99 "PRINT"'      # nothing crunched in quotes
    assert crunch("rem goto 10") == b"\x8f GOTO 10"         # nothing after REM
    assert crunch("data print:print") == b"\x83 PRINT:\x99"  # DATA runs to the next colon
    assert crunch("x=π") == b"X\xb2\xff"
    assert crunch("go to 10") == b"\xcb \xa4 10"
    assert crunch('?"AbC"') == b'\x99"\xc1B\xc3"'           # upper case in strings = shifted
    assert crunch("PRINT X") == crunch("print x")           # keywords and names in any case


def test_program_layout():
    r = tokenize("10 print\n20 end\n")
    assert r.prg().hex() == "0108" "0708" "0a00" "99" "00" "0d08" "1400" "80" "00" "0000"
    assert r.start == 0x0801 and r.end == 0x0801 + len(r.program)


def test_lines_are_sorted_with_a_warning():
    r = tokenize("20 end\n10 print\n")
    assert [ln.number for ln in r.lines] == [10, 20]
    assert any("out of order" in w.message for w in r.warnings)


@pytest.mark.parametrize("src,msg", [
    ("print 1\n", "Line number missing"),
    ("10 print\n10 end\n", "used twice"),
    ("64000 print\n", "above 63999"),
    ('10 print "{nonsense}"\n', "Unknown control code"),
    ('10 print "{clr"\n', "closing"),
    ("10 print " + "1" * 260 + "\n", "too long"),
])
def test_errors(src, msg):
    with pytest.raises(BasicErrors) as e:
        tokenize(src)
    assert msg in e.value.errors[0].message
    assert e.value.errors[0].line is not None


@pytest.mark.parametrize("body,codes", [
    ("clr", [0x93]), ("clear", [0x93]), ("CLR", [0x93]), ("white", [0x05]), ("wht", [0x05]),
    ("rvs on", [0x12]), ("reverse off", [0x92]), ("light blue", [0x9A]), ("gry2", [0x98]),
    ("$93", [0x93]), ("147", [0x93]), ("3 down", [0x11] * 3), ("down*3", [0x11] * 3), ("f1", [0x85]),
])
def test_control_codes(body, codes):
    assert parse_control(body) == codes


def test_bad_control_codes():
    for bad in ("nope", "$zz", "300", "0 down"):
        with pytest.raises(ControlCodeError):
            parse_control(bad)


def test_detokenize_roundtrip():
    prg = tokenize(PROGRAM).prg()
    listed = detokenize(prg)
    assert tokenize(listed).prg() == prg
    assert "10 print \"hello world\"" in listed
    assert "{clear}{white}white{down}{right}{reverse on}rev{reverse off}" in listed


def test_detokenize_basic_loader_of_machine_code_program():
    # The book's programs start with a 10 SYS (2064) line, followed by machine code.
    prg = bytes([0x01, 0x08, 0x0E, 0x08, 0x0A, 0x00, 0x9E, 0x20, 0x28, 0x32, 0x30, 0x36, 0x34, 0x29,
                 0x00, 0x00, 0x00, 0x78, 0xA9])
    assert detokenize(prg) == "10 sys (2064)\n"


def test_line_refs():
    body = 'on x goto 100, 200:if a then 30:gosub 40:print "goto 99":rem goto 98'
    nums = [body[r.start:r.end] for r in find_line_refs(body)]
    assert nums == ["100", "200", "30", "40"]
    other = "list 10-20:run 5:go to 7"
    assert [other[r.start:r.end] for r in find_line_refs(other)] == ["10", "20", "5", "7"]
    assert find_line_refs("data goto 5:x=1") == []


def test_renumber():
    src = "5 rem demo\n7 print \"x\":goto 20\n20 on x gosub 7,5:if a then 5\n30 go to 7:goto 999\n"
    new, warnings = renumber(src, 100, 5)
    assert new == ("100 rem demo\n105 print \"x\":goto 110\n110 on x gosub 105,100:if a then 100\n"
                   "115 go to 105:goto 999\n")
    assert len(warnings) == 1 and "999" in warnings[0].message


def test_renumber_out_of_range():
    with pytest.raises(BasicErrors):
        renumber("10 end\n20 end\n", 63990, 100)


def test_project_with_basic_and_assembly(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text("10 sys 49152\n")
    (tmp_path / "code.asm").write_text("*=$c000\n inc $d020\n rts\n")
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas", "code.asm"], executable="t.prg")
    res = build_project(proj)
    assert res.ok, res.log
    data = res.prg.read_bytes()
    assert data[:2] == b"\x01\x08"
    assert detokenize(data).startswith("10 sys 49152")
    assert data[2 + 0xC000 - 0x0801:] == bytes([0xEE, 0x20, 0xD0, 0x60])


def test_project_basic_errors_have_locations(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text("10 print\nprint oops\n")
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas"], executable="t.prg")
    res = build_project(proj)
    assert not res.ok
    d = res.diagnostics[0]
    assert d.loc.line == 2 and d.loc.file.endswith("main.bas")


def test_assembly_overlapping_basic_is_an_error(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text("10 sys 2061\n")
    (tmp_path / "code.asm").write_text("*=$0801\n rts\n")
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas", "code.asm"], executable="t.prg")
    res = build_project(proj)
    assert not res.ok and "overlaps the BASIC program" in res.diagnostics[-1].message
