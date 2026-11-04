"""Automatic BASIC line numbers."""
from l64s.basic.autonumber import next_number


def test_at_the_end():
    assert next_number(["10 print 1"], 0) == 20
    assert next_number(["10 print 1", "20 print 2"], 1, step=5) == 25
    assert next_number(["63995 end"], 0) is None


def test_between_lines():
    lines = ["10 print 1", "20 print 2"]
    assert next_number(lines, 0) == 15                     # CBM prg Studio: in between, if possible
    assert next_number(lines, 0, step=5) == 15
    assert next_number(lines, 0, step=2) == 12
    assert next_number(["10 a", "11 b"], 0) is None         # no room
    assert next_number(["10 a", "", "20 b"], 1) == 15       # a blank line goes by the line above


def test_no_numbers_yet():
    assert next_number([""], 0) == 10
    assert next_number(["rem", "20 x"], 0) == 10
    assert next_number(["x", "1 y"], 0) is None
