"""Stepping by C line (cc65 builds), as a C debugger does it, on top of VICE's instruction-level
monitor.

A step runs at full speed: VICE gets temporary exec checkpoints over the C code *outside* the line
being stepped, so loops within the line run without stopping, and the program stops as soon as it
leaves the line. At each stop ``decide`` says what to do next:

* in another C line: that's the step done (for Step Over, only at the same call depth or shallower:
  a C function the line calls is run to its end instead);
* in code with no C line (cc65's runtime helpers, the KERNAL): run until it returns, and look again;
* at one of the user's breakpoints: stop there, as any debugger does.

The C call depth comes from the 6502's stack pointer: a JSR pushes two bytes, so code the line
called runs with a lower SP than the line itself. (cc65 keeps C's locals on its own stack, so SP
moves only for calls and interrupts.)
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

# What to do after a stop
STOP = "stop"          # the step is done: show where it is
RUN = "run"            # resume with checkpoints over the C code outside the current line
FINISH = "finish"      # run until the code returns (VICE's "execute until return")


@dataclass(frozen=True)
class LineSpan:
    start: int          # first address
    end: int            # one past the last
    file: str
    line: int


class LineTable:
    """Which C line each address belongs to."""

    def __init__(self, spans: list[LineSpan]):
        self.spans = sorted((s for s in spans if s.end > s.start), key=lambda s: s.start)
        self._starts = [s.start for s in self.spans]
        self._by_line: dict[tuple[str, int], list[LineSpan]] = {}
        for s in self.spans:
            self._by_line.setdefault((s.file, s.line), []).append(s)

    def __bool__(self) -> bool:
        return bool(self.spans)

    def line_at(self, pc: int) -> tuple[str, int] | None:
        i = bisect.bisect_right(self._starts, pc) - 1
        # spans can overlap (a line's code inside another's); the latest-starting one is the most exact
        while i >= 0:
            s = self.spans[i]
            if s.start <= pc < s.end:
                return s.file, s.line
            if self._starts[i] < pc - 0x100:          # no span is that long: stop looking
                break
            i -= 1
        return None

    def ranges_outside(self, line: tuple[str, int]) -> list[tuple[int, int]]:
        """The C code not in ``line``, as inclusive (first, last) address ranges for checkpoints."""
        lo, hi = self.spans[0].start, max(s.end for s in self.spans) - 1
        holes = sorted((s.start, s.end - 1) for s in self._by_line.get(line, []))
        out, at = [], lo
        for a, b in holes:
            if a > at:
                out.append((at, a - 1))
            at = max(at, b + 1)
        if at <= hi:
            out.append((at, hi))
        return out


def decide(table: LineTable, start: tuple[str, int], start_sp: int, pc: int, sp: int, over: bool,
           at_user_breakpoint: bool) -> str:
    """What to do at a stop while stepping from C line ``start`` (left with the stack at
    ``start_sp``). ``over``: Step Over (calls run to their end) rather than Step Into."""
    if at_user_breakpoint:
        return STOP
    here = table.line_at(pc)
    deeper = sp < start_sp                  # inside something the line called
    if here is None:
        # cc65's runtime helpers and the KERNAL have no C lines. Called from this line (or a deeper
        # one): finish them. Reached without a call (a JMP to a helper at the end of a function, say):
        # finishing returns to the caller, which is where the step should go on from too.
        return FINISH
    if here == start and not deeper:
        return RUN                          # still on the line (e.g. back from a call it made)
    if deeper and over:
        return FINISH                       # a C function the line called: run it to its end
    return STOP
