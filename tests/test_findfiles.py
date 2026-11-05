import pytest

from l64s.findfiles import Match, Options, excerpt, pattern, search

TEXTS = {
    "main.asm": "start   lda #0\n        sta SCREEN\n@loop   jsr Start_Game\n        bne @loop\n",
    "lib.asm": "; START here\nSCREEN = $0400\n",
}


def found(opts, texts=TEXTS, **kw):
    return [(m.file, m.line, m.col, m.length) for m in search(texts, opts, **kw)[0]]


def test_plain_text_ignores_case_by_default():
    assert found(Options("start")) == [("main.asm", 1, 0, 5), ("main.asm", 3, 12, 5), ("lib.asm", 1, 2, 5)]


def test_match_case():
    assert found(Options("START", match_case=True)) == [("lib.asm", 1, 2, 5)]


def test_whole_word_treats_underscore_and_at_as_part_of_a_label():
    assert found(Options("start", whole_word=True)) == [("main.asm", 1, 0, 5), ("lib.asm", 1, 2, 5)]
    assert found(Options("loop", whole_word=True)) == []                 # @loop is a different name
    assert found(Options("@loop", whole_word=True)) == [("main.asm", 3, 0, 5), ("main.asm", 4, 12, 5)]


def test_regex_and_special_characters_in_plain_text():
    assert found(Options(r"\$04\d\d", regex=True)) == [("lib.asm", 2, 9, 5)]
    assert found(Options("$0400")) == [("lib.asm", 2, 9, 5)]              # $ is just a character
    assert found(Options("#0")) == [("main.asm", 1, 12, 2)]
    assert found(Options("^", regex=True)) == []                         # matching nothing isn't a result


def test_bad_regex_says_why():
    with pytest.raises(ValueError, match="Not a valid regular expression"):
        pattern(Options("(lda", regex=True))
    assert pattern(Options("")) is None and search(TEXTS, Options("")) == ([], False)


def test_limit():
    matches, more = search({"a.asm": "nop\n" * 10}, Options("nop"), limit=4)
    assert len(matches) == 4 and more
    matches, more = search({"a.asm": "nop\n" * 4}, Options("nop"), limit=4)
    assert len(matches) == 4 and not more


def test_match_keeps_the_line():
    [m] = search(TEXTS, Options("SCREEN ="))[0]
    assert m == Match("lib.asm", 2, 0, 8, "SCREEN = $0400")


def test_excerpt():
    assert excerpt(Match("f", 1, 8, 3, "        lda #0")) == ("", "lda", " #0")
    assert excerpt(Match("f", 1, 1, 3, "\tlda\t#0")) == ("", "lda", "    #0")
    long = "x" * 100 + "HIT" + " end"
    before, hit, after = excerpt(Match("f", 1, 100, 3, long), context=10)
    assert before == "…" + "x" * 10 and hit == "HIT" and after == " end"
