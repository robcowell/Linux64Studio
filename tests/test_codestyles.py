"""Control code styles: Linux64Studio's, BasText and Tok64 (VICE's petcat)."""
import shutil
import subprocess

import pytest

from l64s.basic.codestyles import STYLES, code_text, string_text
from l64s.basic.screencodes import text_to_petscii, to_basic
from l64s.basic.tokenizer import detokenize, tokenize


@pytest.mark.parametrize("style", list(STYLES))
def test_every_code_reads_back(style):
    for c in range(256):
        if c == 0x0D and style == "tok64":
            continue
        assert list(text_to_petscii(code_text(c, style))) == [c], (style, c, code_text(c, style))


@pytest.mark.parametrize("style", list(STYLES))
def test_strings_read_back(style):
    data = bytes([0x93, 0x05, 0x11, 0x11, 0x11, 0x1D, 0x41, 0x41, 0x41, 0x20, 0x20, 0x20, 0xC1, 0xB0, 0xB0,
                  0x5C, 0xFF, 0x22, 0x12, 0x41])
    assert text_to_petscii(string_text(data, style)) == data


def test_examples():
    s = bytes([0x93, 0x9E, 0x11, 0x11, 0x11, 0x11, 0x1D, 0x1D, 0x1D, 0x1D, 0x48, 0x49])
    assert string_text(s, "standard") == "{clear}{yellow}{4 down}{4 right}hi"
    assert string_text(s, "bastext") == "{clear}{yellow}{down*4}{right*4}hi"
    assert string_text(s, "tok64") == "{clr}{yel}{down*4}{rght*4}hi"
    assert string_text(b"AAA", "bastext") == "{a*3}"                       # CBM prg Studio's own example
    assert code_text(0xB0, "bastext") == "{cm a}" and code_text(0xA9, "bastext") == "{sh pound}"
    assert code_text(0x01, "bastext") == "{ct a}" and code_text(0x60, "bastext") == "{096}"
    assert code_text(0xB0, "tok64") == "{CBM-A}" and code_text(0x5C, "tok64") == "\\"
    assert to_basic(s, 10, "tok64") == '10 print "{clr}{yel}{down*4}{rght*4}hi";'


def test_listing_in_each_style():
    prg = tokenize('10 print "{clear}{cbm-a}{3 down}x"\n').prg()
    assert detokenize(prg) == '10 print "{clear}{cbm-a}{3 down}x"\n'
    assert detokenize(prg, style="tok64") == '10 print "{clr}{CBM-A}{down*3}x"\n'
    assert detokenize(prg, style="bastext") == '10 print "{clear}{cm a}{down*3}x"\n'
    for style in STYLES:                                                    # and they tokenise back the same
        assert tokenize(detokenize(prg, style=style)).prg() == prg


@pytest.mark.skipif(not shutil.which("petcat"), reason="needs VICE's petcat")
def test_tok64_is_what_petcat_writes(tmp_path):
    f = tmp_path / "one.seq"
    for c in range(256):
        if c in (0x0D, 0x22):     # a new line; and a quote, which in a string would end it ({$22})
            continue
        f.write_bytes(bytes([c]))
        out = subprocess.run(["petcat", "-nh", "-text", "-c", "--", str(f)], capture_output=True).stdout
        assert out.decode("latin-1").strip("\n") == code_text(c, "tok64"), c
