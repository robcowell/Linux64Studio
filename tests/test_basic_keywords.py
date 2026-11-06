import pytest

from l64s.basic.keywords import KEYWORDS, SPECIAL, describe, keyword_at, lookup
from l64s.basic.tokenizer import KEYWORDS as TOKENS
from l64s.basic.tokenizer import TOKEN, crunch


def at(line: str, word: str, nth: int = 0):
    i = -1
    for _ in range(nth + 1):
        i = line.index(word, i + 1)
    k = keyword_at(line, i)
    return k.name if k else None


def test_every_keyword_has_help():
    operators = set("+-*/^><=")
    assert [k for k in TOKENS if k not in operators and lookup(k) is None] == []
    for k in list(KEYWORDS.values()) + list(SPECIAL.values()):
        assert k.form and k.text and k.kind


def test_the_abbreviations_crunch_to_their_keywords():
    for k in KEYWORDS.values():
        if k.abbrev and k.abbrev != "?":
            assert crunch(k.abbrev)[:1] == bytes([TOKEN[k.name]]), k.name


@pytest.mark.parametrize("line, word, nth, expected", [
    ("10 fori=1to10:printi:nexti", "to", 0, "to"),      # run together, as the C64 crunches it
    ("10 fori=1to10", "for", 0, "for"),
    ("10 score=1", "or", 0, "or"),                         # the ROM crunches the OR in SCORE
    ('10 print "for"', "for", 0, None),                    # not in a string
    ("10 rem for", "for", 0, None),                        # nor a remark
    ("10 data for,goto: print", "for", 0, None),           # nor data, up to the colon
    ("10 data for: print", "print", 0, "print"),
    ('10 ?"hi"', "?", 0, "print"),
    ("10 pO53280,0", "pO", 0, "poke"),                     # an abbreviation
    ("10 print tab(5)", "tab", 0, "tab("),
    ("10 goto 100", "goto", 0, "goto"),
    ("10 x=abs(y)", "y", 0, None),                         # a variable
    ("    printx", "print", 0, "print"),                   # pBASIC: no line number
    ("10 x=ti", "ti", 0, "ti"),                            # the ROM's own variables
    ("10 t$=ti$", "ti$", 0, "ti$"),
    ("10 if st=64 then end", "st", 0, "st"),
    ("10 time=1", "ti", 0, None),                          # ti inside a longer name isn't TI
])
def test_the_keyword_under_the_cursor(line, word, nth, expected):
    assert at(line, word, nth) == expected


def test_lookup_and_text():
    assert lookup("PRINT").name == "print" and lookup("tab").name == "tab(" and lookup("get#").name == "get"
    assert lookup("?").name == "print" and lookup("nothing") is None
    text = describe(KEYWORDS["poke"])
    assert text.startswith("POKE  (statement)") and "poke <address>, <value>" in text and "pO" in text
