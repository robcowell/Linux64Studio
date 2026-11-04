import pytest

from l64s.numconv import describe, number_at, numbers, parse, to_base


def texts(line):
    return [n.text for n in numbers(line)]


def test_finds_numbers_in_cbm_syntax():
    assert texts("        lda #$12") == ["$12"]
    assert texts("        sta $D020,x   ; border 53280") == ["$D020", "53280"]
    assert texts("        and #%00011111") == ["%00011111"]
    assert texts("        byte 1, 2, $FF") == ["1", "2", "$FF"]
    assert texts("label2  lda /1") == []                      # part of a name / a macro parameter
    assert texts('        text "level 10"') == []            # inside quotes
    assert texts("        text 'a', 5") == ["5"]
    assert texts("*=$0801") == ["$0801"]


def test_number_at():
    line = "        lda #$12"
    assert number_at(line, 13).text == "$12"
    assert number_at(line, 16).text == "$12"                 # just after the last digit
    assert number_at(line, 9) is None


def test_parse_selection():
    assert parse(" $C000 ").value == 0xC000
    assert parse("%101").value == 5
    assert parse("lda #1") is None
    assert parse("$G1") is None


def test_to_base_keeps_widths():
    assert to_base(18, "hex") == "$12"
    assert to_base(18, "bin") == "%00010010"
    assert to_base(53280, "hex") == "$D020"
    assert to_base(53280, "bin") == "%1101000000100000"
    assert to_base(0x12, "hex", parse("$0012")) == "$0012"   # the original's 4 digits are kept
    assert to_base(1, "bin", parse("%0000000000000001")) == "%0000000000000001"
    assert to_base(0xD020, "dec") == "53280"
    with pytest.raises(ValueError):
        to_base(-1, "hex")


def test_describe():
    assert describe(parse("$12")) == "$12   18   %00010010"
    assert describe(parse("200")).splitlines()[1] == "signed byte: -56"
    d = describe(parse("$D020")).splitlines()
    assert d[0] == "$D020   53280   %1101000000100000"
    assert d[1] == "high byte $D0 (208), low byte $20 (32)"
    assert d[2] == "signed word: -12256"
