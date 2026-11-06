"""The simulated C64's CIAs (emu.sim): a 6526's timers, time-of-day clock and interrupts, for CIA 1
(its interrupt is the 6510's IRQ) and CIA 2 (its interrupt is the NMI).

Each timer counts down a cycle at a time from when it's started, or (timer B) once each time timer
A runs out; at 0 it runs out (sets its flag in the interrupt control register, $xD0D) and starts
again from its latch, or stops (one-shot). The time-of-day clock counts tenths of a second from the
mains' 50 Hz (5 or 6 to a tenth, as the control register's bit 7 says), with its alarm. Counting is
worked out when it's read, so a timer costs nothing between reads. The serial port, the timers'
outputs on port B, and counting the CNT pin aren't there; the ports are the simulator's (CIA 1's
keyboard and joysticks; CIA 2's port A, the VIC-II's bank).

The delays below (when a timer starts after the control register's written, when its flag and the
interrupt follow it running out) are those of VICE's 6526, checked against it (tests/test_sim.py).
"""
from __future__ import annotations

CLOCK = 985_248                 # a PAL C64's cycles a second
MAINS = 50                      # the time-of-day clock's input, in Hz (a PAL C64's)
START_DELAY = 3                 # a timer starts counting this many cycles after it's started
FLAG_DELAY = 0                  # its flag is set this many cycles after it runs out
CASCADE_DELAY = 1               # timer B counts timer A running out this many cycles after
IRQ_DELAY = 2                   # and the interrupt line goes low this many after the flag


class Timer:
    """One of a CIA's timers. Its count is ``value`` at cycle ``t0`` (it's counted down from there)."""

    def __init__(self):
        self.latch = self.value = 0xFFFF
        self.t0 = 0
        self.running = self.oneshot = False
        self.cascade = False            # timer B counting timer A running out, not cycles
        self.next: int | None = None    # when it next runs out (counting cycles): reads the latch then

    def count(self, t: int) -> int:
        """Its count at cycle ``t``."""
        if not self.running or self.cascade:
            return self.value
        gone = t - self.t0
        if gone <= 0:
            return self.value
        if gone < self.value:
            return self.value - gone
        if gone == self.value:
            return self.latch                           # (it runs out: loaded at once, 0 never shows)
        left = self.latch - (gone - self.value - 1) % (self.latch + 1)
        return left or self.latch

    def _schedule(self) -> None:
        self.next = self.t0 + self.value if self.running and not self.cascade else None

    def control(self, v: int, t: int, cascade: bool) -> None:
        """Its control register written at cycle ``t``: start (bit 0), one-shot (bit 3), force load
        (bit 4); ``cascade``: count timer A running out."""
        count = self.count(t)
        if v & 0x10:
            count = self.latch
        starting = v & 0x01 and not self.running
        self.oneshot, self.running, self.cascade = bool(v & 0x08), bool(v & 0x01), cascade
        self.value = count
        self.t0 = t + START_DELAY if starting else t
        self._schedule()

    def write_latch(self, high: bool, v: int, t: int) -> None:
        self.latch = (self.latch & 0x00FF) | v << 8 if high else (self.latch & 0xFF00) | v
        if high and not self.running:                   # stopped: the count is loaded too
            self.value = self.latch
            self.t0 = t

    def ran_out(self) -> bool:
        """It's just run out (``next`` reached): starts again from the latch, or stops. True if it
        stopped (one-shot)."""
        if self.cascade:
            self.value = self.latch
        else:
            self.t0, self.value = self.next + 1, self.latch     # (counting on from the cycle after)
        if self.oneshot:
            self.running = False
        self._schedule()
        return self.oneshot

    def tick(self) -> bool:
        """Timer A has run out, and this one counts that: True if this one runs out too."""
        if not (self.running and self.cascade):
            return False
        if self.value == 0:
            return True
        self.value -= 1
        return False


def _bcd_inc(v: int) -> int:
    v += 1
    return v + 6 if v & 0x0F == 0x0A else v


class Cia:
    """A 6526: ``read``/``write`` its registers (0-15) at a cycle, ``update`` to a cycle (its timers
    running out, its clock ticking), and ``line(t)``, whether its interrupt is asserted then."""

    def __init__(self):
        self.a, self.b = Timer(), Timer()
        self.cra = self.crb = 0
        self.flags = self.mask = 0
        self.flags_at = 0               # when the flags last became interrupting (for IRQ_DELAY)
        self.pending: list[tuple[int, int]] = []    # (cycle, flag): flags set from then
        self.counts: list[int] = []     # when timer B counts timer A's running out (counting it)
        # the time-of-day clock: tenths, seconds, minutes, hours (BCD, bit 7 of hours PM); the alarm;
        # the copy a read of the hours latches (until tenths are read); stopped by writing the hours
        # (until tenths are written); the mains' next tick, and ticks to the next tenth
        self.tod = [0, 0, 0, 0x01]
        self.alarm = [0, 0, 0, 0]
        self.latched: list[int] | None = None
        self.tod_running = True
        self.tod_ticks = 0
        self.mains = 0                  # mains ticks so far
        self.next_tick = self._mains_at(1)
        self.due = 0                    # the cycle of the next thing to happen (update has nothing before)

    @staticmethod
    def _mains_at(n: int) -> int:
        return n * CLOCK // MAINS

    # -------------------------------------------------------------- time
    def resync(self, t: int) -> None:
        """Time has jumped to cycle ``t`` (a snapshot restored): the clock's mains ticks from there."""
        self.mains = t * MAINS // CLOCK
        self.next_tick = self._mains_at(self.mains + 1)
        self._plan()

    def update(self, t: int) -> None:
        """Everything that's happened by cycle ``t``."""
        if t < self.due:
            return
        while True:
            a, b = self.a.next, self.b.next
            c = self.counts[0] if self.counts else None
            soonest = min(x for x in (a, b, c, self.next_tick) if x is not None)
            if soonest > t:
                break
            if a == soonest:
                self.pending.append((a + FLAG_DELAY, 0x01))
                if self.a.ran_out():
                    self.cra &= 0xFE
                if self.b.running and self.b.cascade:
                    self.counts.append(a + CASCADE_DELAY)
            elif c == soonest:
                self.counts.pop(0)
                if self.b.tick():                       # (B counting A: it runs out)
                    self._b_ran_out(c)
            elif b == soonest:
                self._b_ran_out(b)
            else:
                self._tod_tick()
                self.mains += 1
                self.next_tick = self._mains_at(self.mains + 1)
        if self.pending:
            keep = []
            for at, flag in self.pending:
                if at <= t:
                    if not self.flags & self.mask and flag & self.mask:
                        self.flags_at = at
                    self.flags |= flag
                else:
                    keep.append((at, flag))
            self.pending = keep
        self._plan()

    def _plan(self) -> None:
        """When update next has something to do."""
        due = [self.next_tick] + [at for at, _f in self.pending] + self.counts[:1]
        if self.a.next is not None:
            due.append(self.a.next)
        if self.b.next is not None:
            due.append(self.b.next)
        if self.flags & self.mask:
            due.append(self.flags_at + IRQ_DELAY)
        self.due = min(due)

    def _b_ran_out(self, at: int) -> None:
        self.pending.append((at + FLAG_DELAY, 0x02))
        if self.b.ran_out():
            self.crb &= 0xFE

    def line(self, t: int) -> bool:
        """Whether the interrupt (IRQ or NMI) is asserted at cycle ``t``."""
        if t >= self.due:
            self.update(t)
        if not self.flags & self.mask:
            return False
        return bool(self.flags & self.mask) and t >= self.flags_at + IRQ_DELAY

    # -------------------------------------------------------------- the time-of-day clock
    def _tod_tick(self) -> None:
        if not self.tod_running:
            return
        self.tod_ticks += 1
        if self.tod_ticks < (5 if self.cra & 0x80 else 6):
            return
        self.tod_ticks = 0
        tenths, sec, mins, hrs = self.tod
        tenths = (tenths + 1) & 0x0F
        if tenths == 10:
            tenths = 0
            sec = _bcd_inc(sec)
            if sec == 0x60:
                sec = 0
                mins = _bcd_inc(mins)
                if mins == 0x60:
                    mins = 0
                    pm, h = hrs & 0x80, hrs & 0x1F
                    if h == 0x11:
                        pm ^= 0x80                      # 11 to 12 changes AM and PM
                    h = 0x01 if h == 0x12 else _bcd_inc(h)
                    hrs = pm | h
        self.tod = [tenths, sec, mins, hrs]
        if self.tod == self.alarm:
            self.pending.append((self.next_tick, 0x04))

    # -------------------------------------------------------------- registers
    def read(self, r: int, t: int, clear: bool = True) -> int:
        """Register ``r`` (0-15, ports aside) read at cycle ``t``; ``clear``: as the 6510 reads it
        (reading the interrupt flags clears them; reading the clock's hours latches it)."""
        self.update(t)
        if r == 4:
            return self.a.count(t) & 0xFF
        if r == 5:
            return self.a.count(t) >> 8
        if r == 6:
            return self.b.count(t) & 0xFF
        if r == 7:
            return self.b.count(t) >> 8
        if 8 <= r <= 11:
            tod = self.latched or self.tod
            v = tod[r - 8]
            if clear and r == 11:
                self.latched = list(self.tod)
            elif clear and r == 8:
                self.latched = None
            return v
        if r == 13:
            v = self.flags | (0x80 if self.line(t) else 0)
            if clear:
                self.flags = 0
            return v
        if r == 14:
            return self.cra
        if r == 15:
            return self.crb
        return 0

    def write(self, r: int, v: int, t: int) -> None:
        self.update(t)
        if r in (4, 5):
            self.a.write_latch(r == 5, v, t)
        elif r in (6, 7):
            self.b.write_latch(r == 7, v, t)
        elif 8 <= r <= 11:
            v &= (0x0F, 0x7F, 0x7F, 0x9F)[r - 8]
            if self.crb & 0x80:
                self.alarm[r - 8] = v
            else:
                self.tod[r - 8] = v
                if r == 11:
                    self.tod_running = False            # stopped until the tenths are written
                elif r == 8:
                    self.tod_running, self.tod_ticks = True, 0
        elif r == 13:
            if v & 0x80:
                self.mask |= v & 0x1F
            else:
                self.mask &= ~v & 0x1F
            if self.flags & self.mask:
                self.flags_at = t
        elif r == 14:
            self.a.control(v, t, False)
            self.cra = v & 0xEF                         # (the force-load bit isn't kept)
        elif r == 15:
            self.b.control(v, t, v & 0x60 in (0x40, 0x60))
            self.crb = v & 0xEF
        self._plan()

    # -------------------------------------------------------------- snapshots
    def state(self) -> dict:
        timers = [{k: getattr(x, k) for k in ("latch", "value", "t0", "running", "oneshot", "cascade", "next")}
                  for x in (self.a, self.b)]
        return {"timers": timers, "cra": self.cra, "crb": self.crb, "flags": self.flags, "mask": self.mask,
                "flags_at": self.flags_at, "pending": self.pending, "counts": self.counts, "tod": self.tod,
                "alarm": self.alarm,
                "latched": self.latched, "tod_running": self.tod_running, "tod_ticks": self.tod_ticks,
                "mains": self.mains, "next_tick": self.next_tick}

    def restore(self, s: dict) -> None:
        for x, d in zip((self.a, self.b), s["timers"]):
            for k, v in d.items():
                setattr(x, k, v)
        for k in ("cra", "crb", "flags", "mask", "flags_at", "tod", "alarm", "latched", "tod_running",
                  "tod_ticks", "mains", "next_tick"):
            setattr(self, k, s[k])
        self.pending = [tuple(p) for p in s["pending"]]
        self.counts = list(s.get("counts", []))
        self._plan()
