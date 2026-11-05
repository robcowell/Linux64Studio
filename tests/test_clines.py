from l64s.emu.clines import FINISH, RUN, STOP, LineSpan, LineTable, decide

M = "main.c"
# main.c: line 10 at $0810-$0817, line 11 at $0818-$081F, a for loop on 12 in two pieces
# ($0820-$0823 and $0830-$0835) with line 13 between; twice() in util.c at $0900-$090F
TABLE = LineTable([LineSpan(0x810, 0x818, M, 10), LineSpan(0x818, 0x820, M, 11), LineSpan(0x820, 0x824, M, 12),
                   LineSpan(0x824, 0x830, M, 13), LineSpan(0x830, 0x836, M, 12),
                   LineSpan(0x900, 0x910, "util.c", 3)])


def test_line_at():
    assert TABLE.line_at(0x810) == (M, 10) and TABLE.line_at(0x817) == (M, 10)
    assert TABLE.line_at(0x818) == (M, 11)
    assert TABLE.line_at(0x833) == (M, 12) and TABLE.line_at(0x825) == (M, 13)
    assert TABLE.line_at(0x836) is None and TABLE.line_at(0x700) is None      # runtime code, no line
    assert TABLE.line_at(0x905) == ("util.c", 3)


def test_overlapping_spans_take_the_innermost():
    t = LineTable([LineSpan(0x1000, 0x1020, M, 5), LineSpan(0x1008, 0x100C, M, 6)])
    assert t.line_at(0x1009) == (M, 6) and t.line_at(0x1010) == (M, 5)


def test_ranges_outside_a_line():
    assert TABLE.ranges_outside((M, 12)) == [(0x810, 0x81F), (0x824, 0x82F), (0x836, 0x90F)]
    assert TABLE.ranges_outside((M, 10)) == [(0x818, 0x90F)]
    assert TABLE.ranges_outside(("util.c", 3)) == [(0x810, 0x8FF)]


def test_next_line_stops():
    assert decide(TABLE, (M, 10), 0xF0, 0x818, 0xF0, over=True, at_user_breakpoint=False) == STOP


def test_same_line_runs_on():
    # back on the line after a call it made returned (mid-line): keep going
    assert decide(TABLE, (M, 12), 0xF0, 0x832, 0xF0, over=True, at_user_breakpoint=False) == RUN


def test_step_over_finishes_a_called_c_function():
    assert decide(TABLE, (M, 11), 0xF0, 0x900, 0xEE, over=True, at_user_breakpoint=False) == FINISH


def test_step_into_stops_in_the_called_function():
    assert decide(TABLE, (M, 11), 0xF0, 0x900, 0xEE, over=False, at_user_breakpoint=False) == STOP


def test_runtime_helpers_are_finished():
    assert decide(TABLE, (M, 11), 0xF0, 0x700, 0xEE, over=True, at_user_breakpoint=False) == FINISH
    assert decide(TABLE, (M, 11), 0xF0, 0x700, 0xEE, over=False, at_user_breakpoint=False) == FINISH
    assert decide(TABLE, (M, 11), 0xF0, 0x700, 0xF0, over=True, at_user_breakpoint=False) == FINISH   # a JMP


def test_returning_to_the_caller_stops_there():
    # stepping past the end of a function lands in the caller's line, with the stack shallower
    assert decide(TABLE, ("util.c", 3), 0xEE, 0x81A, 0xF0, over=True, at_user_breakpoint=False) == STOP


def test_user_breakpoint_wins():
    assert decide(TABLE, (M, 11), 0xF0, 0x905, 0xEE, over=True, at_user_breakpoint=True) == STOP


def test_empty_table():
    assert not LineTable([]) and LineTable([]).line_at(0x810) is None


def test_from_code_with_no_line_runs_back_to_c():
    # F10 in cc65's runtime (no C line, start None): finish it, then stop on the caller's line
    assert decide(TABLE, None, 0xEE, 0x700, 0xEE, over=True, at_user_breakpoint=False) == FINISH
    assert decide(TABLE, None, 0xEE, 0x81A, 0xF0, over=True, at_user_breakpoint=False) == STOP
