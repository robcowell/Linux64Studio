"""The token files for C64 BASIC extensions Linux64Studio comes with (tools/gen-basic-tokens.py made
them from VICE's petcat): they load, tokenize as petcat does, list programs back, and a program's
extension is recognised."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from l64s.basic import tokenfile
from l64s.basic.tokenizer import detokenize, tokenize_files

HAVE_PETCAT = shutil.which("petcat") is not None


def test_they_all_load():
    files = tokenfile.builtin()
    assert len(files) >= 27 and "simons-basic" in files and "final-cartridge-iii" in files
    for name, path in files.items():
        toks = tokenfile.load(path)
        assert len(toks) > 76, name                       # BASIC V2's keywords and the extension's
        assert tokenfile.builtin_title(path) and "(C64)" not in tokenfile.builtin_title(path)


def test_a_tokenfile_line_names_one():
    assert tokenfile.find("simons-basic", Path("/nowhere")) == tokenfile.builtin()["simons-basic"]
    src = "tokenfile simons-basic\n10 hires 0,1\n20 end proc\n30 print\n"
    prg = tokenize_files([("t.bas", src)]).prg()
    assert prg[6:8] == b"\x64\x01" and b"\x64\x34" in prg            # HIRES, END PROC: Simons' $64 xx
    assert tokenfile.candidates(prg) == ["simons-basic"] and tokenfile.guess(prg) == "simons-basic"
    listed = detokenize(prg, tokens=tokenfile.load(tokenfile.builtin()["simons-basic"]))
    assert listed == "10 hires 0,1\n20 end proc\n30 print\n"
    assert tokenfile.candidates(tokenize_files([("v.bas", "10 print 1\n")]).prg()) == []    # plain V2


def test_shared_tokens_are_ambiguous():
    # most extensions put their tokens at $CC on, so a program can fit several of them
    own = next(t for t in tokenfile.load(tokenfile.builtin()["final-cartridge-iii"])
               if not (len(t.value) == 1 and t.value[0] <= 0xCB))      # one of its own, not one of V2's
    prg = tokenize_files([("t.bas", f"tokenfile final-cartridge-iii\n10 {own.keyword.lower()}\n")]).prg()
    found = tokenfile.candidates(prg)
    assert "final-cartridge-iii" in found
    assert tokenfile.guess(prg) == (found[0] if len(found) == 1 else None)


def _dialects():
    if not HAVE_PETCAT:
        return []
    text = subprocess.run(["petcat", "-help"], capture_output=True, text=True).stdout
    return re.findall(r"^\s+(\S+)\s+Basic v2\.0 with (.+) \(C64\)$", text, re.M)


@pytest.mark.skipif(not HAVE_PETCAT, reason="needs VICE's petcat")
@pytest.mark.parametrize("code, name", _dialects())
def test_the_same_as_petcat(code, name, tmp_path):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")
    toks = tokenfile.load(tokenfile.builtin()[slug])
    words = [t.keyword.lower() for t in toks if any(c.isalpha() for c in t.keyword)]
    lines = [f"{10 + i} {w}" for i, w in enumerate(words)] + ['9000 print "x";a$:goto 10', "9010 for i=1 to 9:next i"]
    (tmp_path / "t.txt").write_text("\n".join(lines) + "\n")
    subprocess.run(["petcat", f"-w{code}", "-o", str(tmp_path / "t.prg"), "--", str(tmp_path / "t.txt")],
                   check=True, capture_output=True)
    theirs = (tmp_path / "t.prg").read_bytes()
    ours = tokenize_files([(str(tmp_path / "t.bas"), f"tokenfile {slug}\n" + "\n".join(lines) + "\n")],
                          start=theirs[0] | theirs[1] << 8).prg()
    assert ours == theirs
    assert detokenize(theirs, tokens=toks).splitlines() == lines
    assert slug in tokenfile.candidates(theirs)
