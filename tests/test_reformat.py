"""Reformatting BASIC (CBM prg Studio's Reformat BASIC Code, Compress, Uncompress)."""
from l64s.basic.reformat import ABBREVIATIONS, Options, reformat, scan
from l64s.basic.tokenizer import PRINT, tokenize

POKE = 0x97


def program(text: str) -> list:
    """What a program does: each line's number and its tokens, without spaces outside strings."""
    out = []
    for ln in tokenize(text).lines:
        b, keep, q = ln.data, bytearray(), False
        for c in b:
            if c == 0x22:
                q = not q
            if c != 0x20 or q:
                keep.append(c)
        out.append((ln.number, bytes(keep)))
    return out



def fmt(text, **kw):
    return reformat(text, Options(**kw))


def test_scan():
    body = 'print "a b" : rem x y'
    assert [(p.kind, body[p.start:p.end]) for p in scan(body)] == [
        ("kw", "print"), ("space", " "), ("string", '"a b"'), ("space", " "), ("other", ":"), ("space", " "),
        ("kw", "rem"), ("rem", " x y")]
    assert [(p.kind, p.token) for p in scan("pO53280,0")][0] == ("kw", POKE)
    assert [p.kind for p in scan('data 1, "x,y" ,2: print')] == ["kw", "data", "other", "space", "kw"]


def test_general_formatting():
    assert fmt("10print 1\n\n20  goto 10\n")[0] == "10 print 1\n20 goto 10\n"
    assert fmt("10print 1\n\n", remove_blank_lines=False, space_after_number=False)[0] == "10print 1\n\n"
    assert fmt('10 print "Hello {red}World": rem Say Hi\n', strings_case="lower", comments_case="upper")[0] == \
        '10 print "hello {red}world": rem SAY HI\n'


def test_compression():
    src = '10 print "a b" : rem a note\n20 poke 53280 , 0\n30 data 0, 1, 0.5 , -0.25, "0"\n'
    assert fmt(src, remove_spaces=True)[0] == \
        '10 print"a b":rem a note\n20 poke53280,0\n30 data0,1,0.5,-0.25,"0"\n'
    assert fmt(src, remove_spaces=True, spaces_after_rem=True)[0].startswith('10 print"a b":remanote\n')
    assert fmt(src, remove_rems=True)[0].startswith('10 print "a b"\n')
    assert fmt(src, remove_zeros=True)[0].endswith('30 data , 1, .5 , -.25, "0"\n')
    # a line that's only a REM goes, unless a GOTO goes to it
    text, warn = fmt("10 rem start\n20 rem note\n30 goto 10\n", remove_rems=True)
    assert text == "10 rem\n30 goto 10\n" and "jump goes to it" in warn[0].message


def test_compress_and_expand():
    src = '10 print "x";a:poke 53280,0:for i=1 to 10:next i\n'
    small, _ = fmt(src, keywords="abbreviate", remove_spaces=True)
    assert small == '10 ?"x";a:pO53280,0:fOi=1to10:nEi\n'
    assert program(small) == program(src)
    big, _ = fmt(small, expand=True)
    assert big == '10 print "x";a:poke 53280,0:for i=1 to 10:next i\n'
    assert fmt("10 pO53280,0\n", keywords="FULL")[0] == "10 POKE53280,0\n"
    assert ABBREVIATIONS[PRINT] == "?" and ABBREVIATIONS[POKE] == "pO"


def test_never_changes_what_it_does():
    # removing the spaces would make "ta" + "n" read as TAN: left as it is, with a warning
    text, warn = fmt("10 a=t an\n", remove_spaces=True)
    assert text == "10 a=t an\n" and warn and warn[0].line == 1
    for src in ("10 if a then print \"x\"\n", "10 on x goto 10,20\n20 end\n"):
        for kw in ({"remove_spaces": True}, {"keywords": "abbreviate"}, {"expand": True}):
            assert program(fmt(src, **kw)[0]) == program(src)


def test_regions_and_pbasic_lines_are_kept():
    assert fmt("#region a\n10print 1\n#endregion\n")[0] == "#region a\n10 print 1\n#endregion\n"
    assert fmt("@loop\nprint  1:goto @loop\n", remove_spaces=True)[0] == "@loop\nprint1:goto@loop\n"


def test_real_programs_round_trip():
    """Compressing and expanding the BASIC snippets (real routines) keeps what they do."""
    from l64s import snippets
    sources = [snippets.expand(s) for s in snippets.builtin() if s.is_basic]
    assert len(sources) > 20
    for src in sources:
        want = program(src)
        for kw in ({"remove_spaces": True, "keywords": "abbreviate"}, {"expand": True}, {"keywords": "full"}):
            text, _warn = fmt(src, **kw)
            assert program(text) == want, (src, kw, text)
