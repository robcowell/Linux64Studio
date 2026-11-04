import pytest

from l64s.digitiser import FormatError, check_format, coords, format_point
from l64s.screencalc import sprite_cell


def test_coords():
    assert coords(0, 0) == (24, 50)
    assert coords(319, 199) == (343, 249)
    assert coords(300, 10, msb=True) == (68, 60)
    assert coords(5, 5, 0, 0) == (5, 5)
    # the same convention as the Screen Calculator: the point's sprite position is over that cell
    assert sprite_cell(*coords(17, 33)) == (33 // 8, 17 // 8)


def test_format():
    assert format_point("{x}, {y}", 24, 50) == "24, 50"
    assert format_point("byte ${$X}, ${$Y}", 255, 50) == "byte $FF, $32"
    assert format_point("{$x}/{$y}", 10, 300) == "0a/12c"
    assert format_point("word {x}\\nbyte {y}", 300, 60) == "word 300\nbyte 60"
    assert format_point("({x},{y})", -3, 7) == "(-3,7)"


def test_bad_format():
    for bad in ("{x}", "x, y", "{x} {z}", ""):
        with pytest.raises(FormatError):
            check_format(bad)
