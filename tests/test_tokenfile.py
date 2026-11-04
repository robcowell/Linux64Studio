"""User-defined BASIC tokens (token files)."""
import pytest

from l64s.basic.pbasic import to_basic
from l64s.basic.renumber import renumber
from l64s.basic.tokenfile import Token, default_text, parse, tokenfile_line
from l64s.basic.tokenizer import BasicError, BasicErrors, tokenize_files

SUPER_EXPANDER = """# super expander only
GRAPHIC, CD
RESTORE, 8C, reS
SCNCLR, CE
CIRCLE, CF
REGION, D1
"""


def lines(src, tmp_path, tkn=None, name="t.tkn"):
    if tkn is not None:
        (tmp_path / name).write_text(tkn)
    bas = tmp_path / "t.bas"
    bas.write_text(src)
    return [ln.data for ln in tokenize_files([(str(bas), src)]).lines]


def test_parse():
    toks = parse(SUPER_EXPANDER)
    assert toks[0] == Token("GRAPHIC", b"\xcd") and toks[1] == Token("RESTORE", b"\x8c", "reS")
    assert parse("BANK, FE02\n")[0].value == b"\xfe\x02"
    for bad in ("X\n", "X, 7F\n", "X, ZZ\n", "X, 80\nX, 81\n"):
        with pytest.raises(BasicError):
            parse(bad)
    assert tokenfile_line("tokenfile  my tokens.tkn ") == "my tokens.tkn" and tokenfile_line("10 print") is None


def test_cbm_tutorial_print_as_a1(tmp_path):
    """CBM prg Studio's tutorial 18: PRINT given the token $A1."""
    tkn = default_text().replace("PRINT, 99", "PRINT, A1")
    got = lines('tokenfile CustomTokens\n10 print "custom token demo"\n20 end\n', tmp_path, tkn, "CustomTokens.tkn")
    assert got[0][0] == 0xA1 and got[1] == bytes([0x80])


def test_an_extension(tmp_path):
    got = lines("tokenfile t.tkn\n10 graphic 2,1\n20 circle 1,160,100,50: print\n30 scnclr: gR 0\n", tmp_path,
                SUPER_EXPANDER)
    assert got[0][0] == 0xCD and got[1][0] == 0xCF and got[1][-1] == 0x99      # BASIC V2's are still there
    assert got[2][0] == 0xCE and got[2][-3] == 0xCD                            # gR: an abbreviation of GRAPHIC
    two = lines("tokenfile m.tkn\n10 bank 1\n", tmp_path, "BANK, FE02\n", "m.tkn")
    assert two[0][:2] == b"\xfe\x02"


def test_default_file_changes_nothing(tmp_path):
    src = '10 print "hi";:poke 53280,0:goto 10\n20 data 1,2: rem x\n30 a$=left$("ab",1)\n'
    want = lines(src, tmp_path)
    assert lines("tokenfile d.tkn\n" + src, tmp_path, default_text(), "d.tkn") == want


def test_missing_and_bad_files(tmp_path):
    with pytest.raises(BasicErrors) as e:
        lines("tokenfile nothere\n10 print\n", tmp_path)
    assert "isn't there" in e.value.errors[0].message and e.value.errors[0].line == 1
    with pytest.raises(BasicErrors):
        lines("tokenfile t.tkn\n10 print\n", tmp_path, "PRINT, 7\n")


def test_renumber_and_pbasic_keep_it():
    text, _ = renumber("tokenfile t.tkn\n10 graphic 1\n15 goto 10\n")
    assert text == "tokenfile t.tkn\n10 graphic 1\n20 goto 10\n"
    r = to_basic("tokenfile t.tkn\n@top\ngraphic 1\ngoto @top\n")
    assert r.text == "tokenfile t.tkn\n10 graphic 1\n20 goto 10\n"


def test_project_build(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "se.tkn").write_text(SUPER_EXPANDER)
    (tmp_path / "main.bas").write_text("tokenfile se\n10 graphic 2\n")
    p = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas"], executable="t.prg")
    res = build_project(p)
    assert res.ok, res.log
    assert res.prg.read_bytes()[6] == 0xCD
