"""Routine timing: every call of one routine measured exactly in VICE, in cycles, with where in the
frame it runs and how often it's called.

VICE stops at the routine's first instruction (an exec checkpoint). The stack says where the call
will return to: a JSR's return address, or for an interrupt handler (the routine an interrupt
vector points at) the interrupted instruction. A second checkpoint stops there, once the stack
pointer is back where it was before the call, which skips a return from anything the routine
calls itself. The raster line and cycle at the two stops give the cycles between them exactly,
including any interrupt that comes in meanwhile, as that's time the routine takes too. (Stopping
doesn't change the emulated machine: the time it takes isn't the program's.) The raster position
goes round once a frame, so CIA 2's timers count cycles too (emu.cycles.CycleCounter), to say how
many whole frames a call took as well.

A checkpoint that doesn't stop counts every call (unless the routine loops back to its own first
instruction: then only the calls measured are counted, and every call is measured). The program's
time comes from the second CIA's time-of-day clock, which the timer starts (and sets to the
machine's mains frequency, 50 Hz on PAL): it runs on emulated time, so the stops don't count.
Calls are measured up to ``max_rate`` a second: a routine called more often than that has the rest
counted but not measured, so the program keeps close to its speed.

``Timer`` drives a BinaryMonitor from a thread; ``Timing`` adds the calls up.
"""
from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field

from .profiler import PAL, timing_for

# How a call returns, from what's on the stack at the routine's first instruction
JSR, KERNAL_IRQ, CPU_IRQ = "jsr", "kernal-irq", "cpu-irq"


@dataclass
class Call:
    cycles: int
    start_line: int
    end_line: int


@dataclass
class Timing:
    """The measured calls of one routine."""
    calls: list[Call] = field(default_factory=list)
    counted: int = 0                  # every call, measured or not
    seconds: float = 0.0              # how long the program ran meanwhile
    timing: tuple = PAL               # (cycles a line, lines a frame, cycles a second)
    how: str = ""                     # JSR, KERNAL_IRQ, CPU_IRQ

    def clear(self):
        self.calls, self.counted, self.seconds = [], 0, 0.0

    @property
    def frame_cycles(self) -> int:
        return self.timing[0] * self.timing[1]

    @property
    def frames(self) -> float:
        return self.seconds * self.timing[2] / self.frame_cycles

    def per_frame(self) -> float | None:
        return self.counted / self.frames if self.frames > 0.5 else None

    def stats(self) -> dict[str, float] | None:
        """fewest, most, mean and median cycles a call (None before the first)."""
        c = [x.cycles for x in self.calls]
        if not c:
            return None
        return {"min": min(c), "max": max(c), "mean": statistics.fmean(c), "median": statistics.median(c)}

    def lines(self) -> tuple[int, int, int, int] | None:
        """(earliest start line, latest start line, earliest end line, latest end line)."""
        if not self.calls:
            return None
        s = [x.start_line for x in self.calls]
        e = [x.end_line for x in self.calls]
        return min(s), max(s), min(e), max(e)

    def histogram(self, bins: int = 24) -> list[tuple[int, int, int]]:
        """[(from cycles, to cycles, calls)] over the range measured."""
        c = [x.cycles for x in self.calls]
        if not c:
            return []
        lo, hi = min(c), max(c)
        width = max(1, -(-(hi - lo + 1) // bins))
        counts = [0] * (-(-(hi - lo + 1) // width))
        for x in c:
            counts[(x - lo) // width] += 1
        return [(lo + i * width, lo + (i + 1) * width - 1, n) for i, n in enumerate(counts)]

    def report(self, name: str) -> str:
        st = self.stats()
        out = [f"Timing of {name}: {len(self.calls):,} calls measured, {self.counted:,} counted"]
        if self.per_frame() is not None:
            out.append(f"Calls a frame: {self.per_frame():.2f}")
        if st:
            line = self.timing[0]
            for k, label in (("min", "Fewest"), ("mean", "Average"), ("median", "Median"), ("max", "Most")):
                out.append(f"{label} cycles: {st[k]:,.0f} ({st[k] / line:.1f} raster lines, "
                           f"{100 * st[k] / self.frame_cycles:.1f}% of a frame)")
            s0, s1, e0, e1 = self.lines()
            out.append(f"Starts on raster lines {s0}-{s1}, ends on {e0}-{e1}")
        return "\n".join(out) + "\n"


def call_cycles(in_frame: int, counted: int, frame: int) -> int:
    """A call's cycles: ``in_frame`` from the raster positions (exact, but less than a frame), with as
    many whole frames as ``counted`` (CIA 2's timers: the cycles, give or take a few) says went by."""
    return in_frame + max(0, round((counted - in_frame) / frame)) * frame


def return_point(entry: int, sp: int, stack: bytes, vectors: dict[int, int], memory_at) -> tuple[str, int, int] | None:
    """Where a call of the routine at ``entry`` returns to, from the state at its first instruction:
    (how, return address, the stack pointer once it's back), or None if it isn't called by a JSR nor
    as an interrupt handler. ``stack``: $0100-$01FF; ``vectors``: {vector address: what it points
    at} for $0314, $0316, $0318 (the KERNAL's) and $FFFA, $FFFE (the CPU's); ``memory_at(a)``: a
    byte of memory."""
    def word(a):
        return stack[a & 0xFF] | stack[(a + 1) & 0xFF] << 8
    if entry in (vectors.get(0x0314), vectors.get(0x0316), vectors.get(0x0318)):
        # through the KERNAL's handler: it pushed A, X, Y after the CPU pushed PC and P
        return KERNAL_IRQ, word(sp + 5), (sp + 6) & 0xFF
    if entry in (vectors.get(0xFFFE), vectors.get(0xFFFA)):
        return CPU_IRQ, word(sp + 2), (sp + 3) & 0xFF                  # P, then PC
    ret = (word(sp + 1) + 1) & 0xFFFF
    if memory_at((ret - 3) & 0xFFFF) == 0x20:                          # a JSR just before it
        return JSR, ret, (sp + 2) & 0xFF
    return None


def loops_to_entry(code: bytes, entry: int, limit: int = 512) -> bool:
    """Does the routine at ``entry`` (``code``: its bytes from there on) branch or jump back to its
    own first instruction (a loop round the whole routine)? Then hits of the first instruction
    aren't all calls. Reads instructions up to the first RTS, RTI or JMP that isn't back to it."""
    from .asm.opcodes import MODE_SIZE, build_reverse_table
    ops = build_reverse_table(include_illegal=True)
    i = 0
    while i < min(limit, len(code)):
        op = ops.get(code[i])
        if op is None:
            return False
        mnem, mode = op
        size = MODE_SIZE[mode]
        if i + size > len(code):
            return False
        if mode == "rel":
            off = code[i + 1] - 256 if code[i + 1] > 127 else code[i + 1]
            if i + 2 + off == 0:
                return True
        elif mnem == "jmp" and mode == "abs":
            if (code[i + 1] | code[i + 2] << 8) == entry:
                return True
            return False
        elif mnem in ("rts", "rti"):
            return False
        i += size
    return False


class TimerError(Exception):
    pass


class Timer:
    """Measures calls of the routine at ``entry`` in a connected BinaryMonitor's VICE, until
    stop_soon(): a ViceRun's worker. ``on_update(timing)`` is called from its thread as calls come
    in (every ``every`` seconds or so)."""

    def __init__(self, monitor, entry: int, on_update, max_rate: float = 60.0, every: float = 0.5,
                 max_stops: float = 300.0):
        self.monitor, self.entry = monitor, entry
        self.on_update = on_update
        self.max_rate, self.every = max_rate, every
        self.max_stops = max_stops      # calls a second above which skipped calls don't stop either
        self.busy = False
        self.chance = 1.0               # of a call being measured
        self.timing = Timing()
        self._stop = threading.Event()
        self._stopped = threading.Event()
        self._checkpoints: set[int] = set()
        self._cia_controls: bytes | None = None
        self._counter = None            # emu.cycles.CycleCounter: whole frames, for calls that long
        import random
        self._rnd = random.Random()
        self.count_all = True           # False: only the measured calls are counted (it loops to its start)

    def vice_event(self, rtype: int, body: bytes):
        from .emu.binmon import EVT_STOPPED
        if rtype in (EVT_STOPPED, -1):
            self._stopped.set()

    def stop_soon(self):
        self._stop.set()

    def _add(self, address: int, stop: bool = True) -> int:
        cid = self.monitor.add_checkpoint(address, stop=stop).id
        self._checkpoints.add(cid)
        return cid

    def _delete(self, cid: int):
        self.monitor.delete_checkpoint(cid)
        self._checkpoints.discard(cid)

    def run(self) -> str:
        from .emu.binmon import MonitorError
        m = self.monitor
        t = self.timing
        message = ""
        try:
            counter = None              # counts every call (not if the routine loops to its first instruction)
            measure = self._add(self.entry)
            measuring, known_timing = True, False
            exit_cp = None              # (checkpoint, stack pointer once back, start position, start line)
            next_measure = last_update = 0.0
            self._resume()
            while not self._stop.is_set() and m.connected:
                wait = self.every
                if not measuring and exit_cp is None:            # to switch measuring back on in time
                    wait = max(0.0, min(wait, next_measure - time.monotonic()))
                stopped = self._stopped.wait(wait) if wait > 0 else False
                if not stopped:                         # nothing for a while: stop it to read the count
                    m.ping()
                    self._stopped.wait(1)
                regs = m.get_registers()
                pc, sp, line = regs.get("PC", 0), regs.get("SP", 0), regs.get("LIN", 0)
                now = time.monotonic()
                if stopped and exit_cp is None and pc == self.entry and measuring:
                    if not known_timing:                # (the KERNAL's PAL flag, set by now)
                        t.timing, known_timing = timing_for(m.read_memory(0x02A6, 0x02A6)[0]), True
                        self._start_clock(t.timing is PAL)
                        from .emu.cycles import CycleCounter
                        self._counter = CycleCounter(m)
                        self._counter.start()
                        code = m.read_memory(self.entry, min(0xFFFF, self.entry + 511))
                        if not loops_to_entry(code, self.entry):
                            counter = self._add(self.entry, stop=False)
                            t.counted = 1           # (this call, which it didn't see)
                        self.count_all = counter is not None
                    if counter is not None and self._rnd.random() > self.chance:
                        # not this call (to keep to max_rate, a call in so many chosen at random, so
                        # those measured are a fair share of them, wherever they are): let it run. A routine called so often
                        # that even these stops would slow the program has its stop switched off
                        # for a while instead (switched on again when VICE next stops: at the end
                        # of a frame, so the calls measured are those after it)
                        if self.busy:
                            m.enable_checkpoint(measure, False)
                            measuring = False
                        self._resume()
                        continue
                    where = self._return_point(sp)
                    if where is None:
                        raise TimerError("It isn't called with JSR or as an interrupt handler, so where it "
                                         "returns to isn't known")
                    t.how, ret, back_sp = where
                    pos = line * t.timing[0] + regs.get("CYC", 0)
                    exit_cp = (self._add(ret), back_sp, pos, line, self._counter.read())
                    m.enable_checkpoint(measure, False)
                    measuring = False
                elif stopped and exit_cp is not None and sp == exit_cp[1] and pc != self.entry:
                    cid, _sp, start, start_line, count = exit_cp
                    pos = line * t.timing[0] + regs.get("CYC", 0)
                    t.calls.append(Call(call_cycles((pos - start) % t.frame_cycles,
                                                    (count - self._counter.read()) & 0xFFFFFFFF, t.frame_cycles),
                                        start_line, line))
                    self._delete(cid)
                    exit_cp = None
                    if counter is None:
                        # it loops to its start: measure every call (switched on now, while it isn't
                        # running, the next stop at its start is a call, not a time round the loop)
                        t.counted = len(t.calls)
                        next_measure = now
                    else:
                        next_measure = now
                    if not self.busy:
                        m.enable_checkpoint(measure, True)
                        measuring = True
                if not measuring and exit_cp is None and now >= next_measure:
                    m.enable_checkpoint(measure, True)
                    measuring = True
                if now - last_update >= self.every:
                    before = (t.counted, t.seconds)
                    self._read_counts(counter, known_timing)
                    if counter is not None and t.seconds > before[1]:
                        rate = (t.counted - before[0]) / (t.seconds - before[1])     # calls a second
                        self.busy = rate > self.max_stops
                        self.chance = min(1.0, self.max_rate / rate) if rate > 0 else 1.0
                    last_update = now
                    self.on_update(t)
                self._resume()
            if m.connected:
                m.ping()                                    # (stops VICE)
                self._read_counts(counter, known_timing)    # the count and the clock at the same moment
        except TimerError as e:
            message = str(e)
        except (MonitorError, OSError, ConnectionError) as e:
            if m.connected and not self._stop.is_set():
                message = f"VICE stopped answering: {e}"
        finally:
            self._finish()
        self.on_update(t)
        return message

    def _read_counts(self, counter: int | None, clock: bool):
        import struct

        from .emu.binmon import CMD_CHECKPOINT_GET, parse_checkpoint
        if counter is not None:
            _, r = self.monitor.request(CMD_CHECKPOINT_GET, struct.pack("<I", counter))
            self.timing.counted = parse_checkpoint(r).hit_count + 1
        if clock:
            self.timing.seconds = self._clock_seconds()

    def _resume(self) -> float:
        self._stopped.clear()
        self.monitor.resume()
        return time.monotonic()

    # The second CIA's time-of-day clock, for the program's time ($DD08 tenths, $DD09 seconds,
    # $DD0A minutes, $DD0B hours, in BCD; bit 7 of $DD0E: 50 Hz, of $DD0F: writes set the alarm)
    def _start_clock(self, pal: bool):
        m = self.monitor
        self._cia_controls = m.read_memory(0xDD0E, 0xDD0F)
        cra, crb = self._cia_controls
        m.write_memory(0xDD0E, bytes([(cra | 0x80) if pal else (cra & 0x7F)]), side_effects=True)
        m.write_memory(0xDD0F, bytes([crb & 0x7F]), side_effects=True)
        for reg, value in ((0xDD0B, 0x01), (0xDD0A, 0), (0xDD09, 0), (0xDD08, 0)):   # the hours stop it, the tenths start it
            m.write_memory(reg, bytes([value]), side_effects=True)

    def _clock_seconds(self) -> float:
        tenths, sec, mins, hours = self.monitor.read_memory(0xDD08, 0xDD0B)
        bcd = lambda v: (v >> 4) * 10 + (v & 0x0F)      # noqa: E731
        return (bcd(hours & 0x1F) - 1) * 3600 + bcd(mins) * 60 + bcd(sec) + bcd(tenths) / 10

    def _return_point(self, sp: int):
        m = self.monitor
        stack = m.read_memory(0x0100, 0x01FF)
        low = m.read_memory(0x0314, 0x0319)
        high = m.read_memory(0xFFFA, 0xFFFF)
        vectors = {0x0314: low[0] | low[1] << 8, 0x0316: low[2] | low[3] << 8, 0x0318: low[4] | low[5] << 8,
                   0xFFFA: high[0] | high[1] << 8, 0xFFFE: high[4] | high[5] << 8}
        return return_point(self.entry, sp, stack, vectors, lambda a: m.read_memory(a, a)[0])

    def _finish(self):
        """Take the checkpoints away, so the program runs on undisturbed."""
        from .emu.binmon import MonitorError
        m = self.monitor
        if not m.connected:
            return
        try:
            m.ping()                                     # (stops VICE, if it's running)
            for cid in list(self._checkpoints):
                self._delete(cid)
            if self._counter is not None:
                self._counter.stop()
            if self._cia_controls is not None:           # CIA 2's clock settings as they were
                m.write_memory(0xDD0E, self._cia_controls[:1], side_effects=True)
                m.write_memory(0xDD0F, self._cia_controls[1:], side_effects=True)
            self._resume()
        except (MonitorError, OSError):
            pass
