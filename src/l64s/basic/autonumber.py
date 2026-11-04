"""Automatic BASIC line numbers (CBM prg Studio's editor): pressing Return at the end of a line
starts the next line with a number, the step after this one, or one in between when the next
line's number is closer, or none if there's no room."""
from __future__ import annotations

import re

from .tokenizer import MAX_LINE_NUMBER

_NUM = re.compile(r"^\s*(\d+)")


def line_number(line: str) -> int | None:
    m = _NUM.match(line)
    return int(m.group(1)) if m else None


def next_number(lines: list[str], at: int, step: int = 10) -> int | None:
    """The number for a new line after line `at` (0-based) of `lines`, or None for no number."""
    here = next((line_number(lines[i]) for i in range(at, -1, -1) if line_number(lines[i]) is not None), None)
    after = next((line_number(lines[i]) for i in range(at + 1, len(lines)) if line_number(lines[i]) is not None),
                 None)
    if here is None:                    # no numbered line yet above: start at the step
        if after is None or step < after:
            return step
        return after - 1 if after > 1 else None
    want = here + max(1, step)
    if after is None:
        return want if want <= MAX_LINE_NUMBER else None
    if want < after:
        return want
    mid = (here + after) // 2
    return mid if here < mid < after else None
