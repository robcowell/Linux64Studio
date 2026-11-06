"""Counting the C64's cycles from outside, through VICE's binary monitor.

``CycleCounter`` makes CIA 2's two timers one 32-bit count of every cycle: timer A counts the
cycles down from $FFFF, and timer B counts timer A's underflows. VICE's emulation, and so the
count, stops while the monitor has it stopped, so the difference between two readings is exactly
the cycles the program ran between them, however long. It changes CIA 2: its control registers
are put back by ``stop()``, but the timers' latches are left at $FFFF (a program using CIA 2's
timers itself would see that).

``raster_cycles`` is the other way, which changes nothing: the cycles between two raster
positions, exact as long as less than a frame went by (one instruction, say).
"""
from __future__ import annotations

PAL = (63, 312)          # cycles a line, lines a frame
NTSC = (65, 263)


class CycleCounter:
    def __init__(self, monitor):
        self.monitor = monitor
        self._controls: bytes | None = None

    @property
    def running(self) -> bool:
        return self._controls is not None

    def start(self) -> int:
        """Set the timers counting (VICE must be stopped); the count now."""
        m = self.monitor
        if self._controls is None:
            self._controls = m.read_memory(0xDD0E, 0xDD0F)
        tod = m.read_memory(0xDD0E, 0xDD0E)[0] & 0x80      # (the time-of-day clock's 50/60 Hz: kept)
        m.write_memory(0xDD0E, bytes([tod, 0]), side_effects=True)             # both stopped
        m.write_memory(0xDD04, b"\xff\xff\xff\xff", side_effects=True)         # latches: $FFFF
        m.write_memory(0xDD0F, bytes([0x51]), side_effects=True)                # B counts A's underflows
        m.write_memory(0xDD0E, bytes([0x11 | tod]), side_effects=True)          # A counts cycles
        return self.read()

    def read(self) -> int:
        """The count (it goes down): the cycles between two readings are the first minus the second."""
        t = self.monitor.read_memory(0xDD04, 0xDD07)
        return (t[2] | t[3] << 8) << 16 | (t[0] | t[1] << 8)

    def stop(self):
        """Put CIA 2's control registers back as they were."""
        if self._controls is not None:
            self.monitor.write_memory(0xDD0E, self._controls, side_effects=True)
            self._controls = None


def raster_cycles(before: tuple[int, int], after: tuple[int, int], timing=PAL) -> int:
    """Cycles between two (raster line, cycle in the line) positions, less than a frame apart."""
    per_line, lines = timing
    frame = per_line * lines
    return ((after[0] * per_line + after[1]) - (before[0] * per_line + before[1])) % frame
