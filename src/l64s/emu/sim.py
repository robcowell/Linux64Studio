"""Debugging without an emulator: a C64 simulated in Python, as CBM prg Studio's own debugger does.

The 6510 is py65's (documented opcodes, with their exact cycles: page crossings and branches
included). Around it is the C64's memory: 64K of RAM, with the BASIC, KERNAL and character ROMs
(VICE's copies, when installed) banked in and out by the processor port at $00/$01, as on the real
machine. So KERNAL calls run for real; without the ROMs, ``skip_kernal`` steps over them instead.

What isn't there: most of the VIC-II, SID and CIAs. $D000-$DFFF is memory that reads back what was
written, except for what makes a program's timing and interrupts work:

* the raster line ($D012, and $D011's top bit) counts as on a PAL C64, and the VIC-II's raster
  interrupt ($D012 and $D011 for the line, $D019 its flag, $D01A to switch it on) happens on it;
* CIA 1's timer A ($DC04/$DC05, started with $DC0E) counts down a cycle at a time, and interrupts
  through $DC0D, as the KERNAL's 60-a-second interrupt does;
* the sprites' collisions ($D01E, $D01F, and $D019's flags for them), worked out once a frame from
  memory as the Screen view draws it;
* the keyboard and joysticks: CIA 1's ports ($DC00, $DC01) read the keys held down (``hold``), as
  the keyboard matrix connects them to the columns selected, and the joysticks (``joystick``):
  port 2's on $DC00, port 1's on $DC01;
* the cycles the VIC-II takes from the 6510 on badlines and for sprites (``Memory.stall``);
* a read-modify-write's first write, of what it read, in the I/O area (so INC $D019 acknowledges).

The disk drive is ``emu.simdrive``'s: the KERNAL's serial bus routines are taken over at their entry
points (while the KERNAL is banked in) and answered by drive 8 (``attach_disk``).

Interrupts happen as on a C64 while the program runs (an IRQ when one of those is on and the I flag
is clear), but a single step never goes into one: a step is the instruction at the PC.

``Machine`` is the simulated C64. ``SimMonitor`` runs one with the same methods as
``binmon.BinaryMonitor`` (VICE's binary monitor), so the debugger and transcripts drive either.
"""
from __future__ import annotations

import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path

from py65.devices.mpu6502 import MPU

from .binmon import EVT_JAM, EVT_RESUMED, EVT_STOPPED, OP_EXEC, OP_LOAD, OP_STORE, Checkpoint, MonitorError

CYCLES_PER_LINE, LINES = 63, 312               # PAL
FRAME = CYCLES_PER_LINE * LINES                 # 19,656 cycles
ROM_DIRS = [Path.home() / ".local/share/vice/C64", Path("/usr/share/vice/C64"), Path("/usr/lib/vice/C64"),
            Path("/usr/local/share/vice/C64")]
ROM_FILES = {"basic": ("basic-901226-01.bin", 0x2000), "kernal": ("kernal-901227-03.bin", 0x2000),
             "chargen": ("chargen-901225-01.bin", 0x1000)}
KERNAL_TABLE = range(0xFF81, 0xFFF4)            # the KERNAL's jump table (what skip_kernal steps over)
READY_LOOP = range(0xE5CD, 0xE5D7)              # the KERNAL waiting for a key, at READY.
RTS, RTI, JSR, BRK = 0x60, 0x40, 0x20, 0x00

# The keyboard matrix: each key's column (the $DC00 bit that selects it) and row (the $DC01 bit it
# pulls low). Columns 0-7, a row each, from the C64's schematic.
_MATRIX_ROWS = [
    ["del", "return", "right", "f7", "f1", "f3", "f5", "down"],
    ["3", "w", "a", "4", "z", "s", "e", "shift"],
    ["5", "r", "d", "6", "c", "f", "t", "x"],
    ["7", "y", "g", "8", "b", "h", "u", "v"],
    ["9", "i", "j", "0", "m", "k", "o", "n"],
    ["+", "p", "l", "-", ".", ":", "@", ","],
    ["pound", "*", ";", "home", "rshift", "=", "uparrow", "/"],
    ["1", "leftarrow", "ctrl", "2", "space", "commodore", "q", "stop"],
]
KEYS = {name: (col, row) for col, names in enumerate(_MATRIX_ROWS) for row, name in enumerate(names)}
KEY_ALIASES = {"lshift": "shift", "cbm": "commodore", "c=": "commodore", "runstop": "stop", "run/stop": "stop",
               "inst/del": "del", "delete": "del", "enter": "return", " ": "space", "£": "pound",
               "crsr right": "right", "crsr down": "down", "clr/home": "home"}
JOY_BITS = {"up": 1, "down": 2, "left": 4, "right": 8, "fire": 16}


def key_named(name: str) -> tuple[int, int]:
    """A key's (column, row) in the keyboard matrix, by its name: a letter, digit or symbol, or
    space, return, del, f1, f3, f5, f7, right, down, home, shift, rshift, ctrl, commodore, stop..."""
    n = name.strip().lower()
    n = KEY_ALIASES.get(n, n)
    if n not in KEYS:
        raise MonitorError(f"There's no C64 key called {name!r}")
    return KEYS[n]


def find_roms() -> dict[str, bytes]:
    """The ROMs VICE has installed: {"basic", "kernal", "chargen"} (any not found are left out)."""
    from ..host import host_path
    out: dict[str, bytes] = {}
    for name, (file, size) in ROM_FILES.items():
        for d in ROM_DIRS:
            try:
                data = host_path(d / file).read_bytes()
            except OSError:
                continue
            if len(data) == size:
                out[name] = data
                break
    return out


class Memory:
    """The 64K the 6510 sees. Writes go to RAM, or to I/O while it's banked in (writes under the ROMs
    go to the RAM beneath them, as on a C64)."""

    def __init__(self, roms: dict[str, bytes], clock):
        self.ram = bytearray(0x10000)
        self.io = bytearray(0x1000)
        self.basic, self.kernal, self.chargen = roms.get("basic"), roms.get("kernal"), roms.get("chargen")
        self.clock = clock                     # () -> cycles so far (for the raster line)
        # the VIC-II's interrupt flags ($D019's low bits: 1 is the raster), and when the raster next
        # reaches the compare line (None: a line past the frame's end, never)
        self.vic_flags = 0
        self.next_raster: int | None = 0
        # CIA 1's timer A: its latch, whether it's running (and one-shot), its count at cycle t0, when
        # it next runs out; and the CIA's interrupt flags and mask ($DC0D)
        self.ta_latch, self.ta_value, self.ta_t0 = 0xFFFF, 0xFFFF, 0
        self.ta_running, self.ta_oneshot = False, False
        self.ta_next: int | None = None
        self.cia_flags, self.cia_mask = 0, 0
        # what's pressed: the joysticks in ports 1 and 2 (JOY_BITS), and the keys held (column, row)
        self.joysticks = [0, 0, 0]
        self.held: set[tuple[int, int]] = set()
        # sprite collisions ($D01E, $D01F), worked out once a frame and kept until they're read
        self.collided_sprites = self.collided_background = 0
        self.next_frame = FRAME
        # the VIC-II's registers (and the bank) as this frame started, and the writes since, with the
        # raster line of each [(line, register, value)]; and the last whole frame's (simscreen)
        from .simscreen import Rows, registers_now
        self.frame_start = registers_now(self.io)
        self.frame_log: list[tuple[int, int, int]] = []
        # each character row's screen codes and colours, as the VIC-II read them on its badline this
        # frame ({row: (codes, colours)}); the rows being counted (simscreen.Rows), and when the next
        # line's read happens (14 cycles into it, as the VIC-II's reads start at its 15th)
        self.fetched: dict[int, tuple[bytes, bytes]] = {}
        self.rows = Rows()
        self.next_line = 14
        # when the VIC-II has the bus (``stall``): the windows decided so far [(BA low from, to, the bus
        # taken from, to)], in cycles; the next point where it decides more (a badline at cycle 12 of a
        # line, the sprites' DMA at 55); each sprite's lines of DMA left; the screen switched on at line 48
        self.windows: list[tuple[int, int, int, int]] = []
        self.next_decision = 0
        self.decisions = 0                     # (which of the line's two is next: 0 badline, 1 sprites)
        self.dma_left = [0] * 8
        self.den = False
        self.quiet_until = 0
        self.resync_vic(0)
        self.last_frame: tuple[bytes, list, dict] | None = None
        self.ram[0], self.ram[1] = 0x2F, 0x37
        self.watch: dict[int, int] = {}        # address -> OP_LOAD | OP_STORE (load/store checkpoints)
        self.rmw = False                       # the instruction running reads, modifies and writes memory
        self.rmw_read: tuple[int, int] | None = None   # (address, value) it read in the I/O area
        self.touched: list[tuple[int, int]] = []   # (address, op) of watched accesses, for the run loop
        self._bank()

    def __len__(self) -> int:
        return 0x10000

    def port(self) -> int:
        """The processor port as the banking sees it: bits set as inputs read as 1 (pulled up)."""
        ddr = self.ram[0]
        return (self.ram[1] & ddr) | (~ddr & 0xFF)

    def _bank(self) -> None:
        p = self.port() & 7
        self.basic_in = self.basic is not None and p & 3 == 3
        self.kernal_in = self.kernal is not None and p & 2 != 0
        self.io_in = p & 3 != 0 and p & 4 != 0
        self.char_in = p & 3 != 0 and p & 4 == 0

    # ------------------------------------------------------------------ the CPU's accesses
    def __getitem__(self, a: int) -> int:
        if self.watch and a in self.watch and self.watch[a] & OP_LOAD:
            self.touched.append((a, OP_LOAD))
        v = self.peek(a, True)
        if self.rmw and 0xD000 <= a < 0xE000:
            self.rmw_read = (a, v)
        return v

    def __setitem__(self, a: int, v: int) -> None:
        if self.watch and a in self.watch and self.watch[a] & OP_STORE:
            self.touched.append((a, OP_STORE))
        if self.rmw_read is not None and self.rmw_read[0] == a and self.io_in:
            # a read-modify-write writes what it read back first, then the result (py65 does only the
            # second): so INC $D019 acknowledges the VIC-II's interrupt, as on a C64
            self.poke(a, self.rmw_read[1], True)
        self.rmw_read = None
        self.poke(a, v, True)

    def peek(self, a: int, cpu: bool = False) -> int:
        if a < 0xA000:
            return self.ram[a]
        if a < 0xC000:
            return self.basic[a - 0xA000] if self.basic_in else self.ram[a]
        if a < 0xD000:
            return self.ram[a]
        if a < 0xE000:
            if self.io_in:
                return self._io_read(a, cpu)
            if self.char_in and self.chargen is not None:
                return self.chargen[a - 0xD000]
            return self.ram[a]
        return self.kernal[a - 0xE000] if self.kernal_in else self.ram[a]

    def poke(self, a: int, v: int, cpu: bool = False) -> None:
        v &= 0xFF
        if 0xD000 <= a < 0xE000 and self.io_in:
            self._io_write(a & 0xFFF, v)
            return
        self.ram[a] = v
        if a < 2:
            self._bank()

    def _io_read(self, a: int, cpu: bool) -> int:
        r = a & 0xFFF
        if r == 0x012:
            return self.line() & 0xFF
        if r == 0x011:
            return (self.io[r] & 0x7F) | ((self.line() & 0x100) >> 1)
        if r == 0x019:
            return 0x70 | self.vic_flags | (0x80 if self.vic_irq() else 0)
        if r in (0x01E, 0x01F):
            v = self.collided_sprites if r == 0x01E else self.collided_background
            if cpu:                                     # reading clears them
                if r == 0x01E:
                    self.collided_sprites = 0
                else:
                    self.collided_background = 0
            return v
        if r == 0xC00:
            return self._port_a() & ~self.joysticks[2] & 0xFF
        if r == 0xC01:
            return self._keyboard_rows() & ~self.joysticks[1] & 0xFF
        if r == 0xC04:
            return self.ta_count() & 0xFF
        if r == 0xC05:
            return self.ta_count() >> 8
        if r == 0xC0D:
            v = self.cia_flags | (0x80 if self.cia_irq() else 0)
            if cpu:
                self.cia_flags = 0                     # reading clears them
            return v
        if r == 0xD0D:
            return 0
        if 0x800 <= r < 0xC00:
            return self.io[r] & 0x0F | 0xF0           # colour RAM is four bits
        return self.io[r]

    def _port_a(self) -> int:
        """CIA 1's port A as driven: the column bits it outputs, and 1s on its inputs."""
        return (self.io[0xC00] | ~self.io[0xC02]) & 0xFF

    def _keyboard_rows(self) -> int:
        """Port B: a row's bit is 0 if a key held in it is in a column port A selects (drives 0)."""
        if not self.held:
            return 0xFF
        cols = ~self._port_a() & ~self.joysticks[2] & 0xFF     # (a joystick on port 2 selects too)
        rows = 0xFF
        for col, row in self.held:
            if cols >> col & 1:
                rows &= ~(1 << row)
        return rows & 0xFF

    def _io_write(self, r: int, v: int) -> None:
        if r < 0x2F:                                    # the VIC-II's: kept by line, for the Screen
            self.frame_log.append((self.line(), r, v))
        elif r == 0xD00:
            self.frame_log.append((self.line(), 0x2F, v))
        if r == 0x019:
            self.vic_flags &= ~v & 0x0F                # writing 1 clears a flag
            return
        if r == 0xC04:
            self.ta_latch = (self.ta_latch & 0xFF00) | v
        elif r == 0xC05:
            self.ta_latch = (self.ta_latch & 0x00FF) | v << 8
            if not self.ta_running:                     # stopped: the count is loaded too
                self.ta_value = self.ta_latch
        elif r == 0xC0D:
            if v & 0x80:
                self.cia_mask |= v & 0x1F
            else:
                self.cia_mask &= ~v & 0x1F
        elif r == 0xC0E:
            self._ta_control(v)
            v &= 0xEF                                   # (the force-load bit isn't kept)
        self.io[r] = v
        if r in (0x011, 0x012):
            self.schedule_raster()

    # ------------------------------------------------------------------ the raster line
    def line(self) -> int:
        return (self.clock() // CYCLES_PER_LINE) % LINES

    def compare_line(self) -> int:
        return self.io[0x12] | (self.io[0x11] & 0x80) << 1

    def schedule_raster(self) -> None:
        """When the raster next starts the compare line."""
        target = self.compare_line()
        if target >= LINES:
            self.next_raster = None
            return
        now = self.clock()
        t = now - now % FRAME + target * CYCLES_PER_LINE
        self.next_raster = t if t > now else t + FRAME

    def vic_irq(self) -> bool:
        return bool(self.vic_flags & self.io[0x1A] & 0x0F)

    # ------------------------------------------------------------------ CIA 1's timer A
    def ta_count(self) -> int:
        """Timer A's count now."""
        if not self.ta_running:
            return self.ta_value
        gone = self.clock() - self.ta_t0
        if gone <= self.ta_value:
            return self.ta_value - gone
        period = self.ta_latch + 1
        return self.ta_latch - (gone - self.ta_value - 1) % period

    def _ta_control(self, v: int) -> None:
        count = self.ta_count()
        if v & 0x10:                                    # force load
            count = self.ta_latch
        self.ta_oneshot = bool(v & 0x08)
        self.ta_running = bool(v & 0x01)
        self.ta_value, self.ta_t0 = count, self.clock()
        self.ta_next = self.ta_t0 + count + 1 if self.ta_running else None

    def cia_irq(self) -> bool:
        return bool(self.cia_flags & self.cia_mask)

    def tick(self, now: int) -> None:
        """What's happened by cycle ``now``: the raster reaching the compare line, timer A running out, a
        frame drawn (and its sprites' collisions)."""
        if now >= self.next_line:
            self._lines_to(now)
        if now >= self.next_frame:
            self.next_frame += FRAME * ((now - self.next_frame) // FRAME + 1)
            self._end_frame()
        if self.next_raster is not None and now >= self.next_raster:
            self.vic_flags |= 1
            self.next_raster += FRAME * ((now - self.next_raster) // FRAME + 1)
        if self.ta_next is not None and now >= self.ta_next:
            self.cia_flags |= 1
            if self.ta_oneshot:
                self.ta_running, self.ta_value, self.ta_next = False, self.ta_latch, None
                self.io[0xC0E] &= 0xFE
            else:
                period = self.ta_latch + 1
                self.ta_next += period * ((now - self.ta_next) // period + 1)

    def _lines_to(self, now: int) -> None:
        """The VIC-II's reads of the lines it's reached by ``now``: on a badline, the row's screen and
        colour memory."""
        from .simscreen import fetch_row, registers_now
        if now - self.next_line > FRAME:                # (a jump in time: a snapshot restored, say)
            self.next_line = now - now % CYCLES_PER_LINE + 14
            self.rows = type(self.rows)()
        while now >= self.next_line:
            line = (self.next_line // CYCLES_PER_LINE) % LINES
            if line == 0:
                self.fetched = {}
            where, bad = self.rows.line(line, self.io[0x11])
            if bad:
                self.fetched[where[0]] = fetch_row(self.ram, self.io, self.chargen, registers_now(self.io), where[0])
            self.next_line += CYCLES_PER_LINE

    def _end_frame(self) -> None:
        """A frame's been drawn: keep its registers line by line and its rows as read, and work out its
        sprite collisions."""
        from .simscreen import frame_lines, registers_now
        self.last_frame = (self.frame_start, self.frame_log, self.fetched)
        if self.frame_log and any(r == 0x15 and v for _l, r, v in self.frame_log) or self.frame_start[0x15]:
            self._collide(frame_lines(self.frame_start, self.frame_log), self.fetched)
        self.frame_start = registers_now(self.io)
        self.frame_log = []

    def screen_frame(self, whole: bool) -> tuple[list[bytes], dict]:
        """For the Screen: the registers on each raster line, and the rows as the VIC-II read them
        (simscreen.render's ``lines`` and ``fetched``). ``whole``: the last whole frame's (as the program
        runs, a steady picture); else this frame's up to the raster line, with the registers and memory
        as they are now below it (stopped: what a change just made does)."""
        from .simscreen import frame_lines, registers_now
        if whole and self.last_frame is not None:
            start, log, fetched = self.last_frame
            return frame_lines(start, log), fetched
        return frame_lines(self.frame_start, self.frame_log, registers_now(self.io), self.line()), self.fetched

    def _collide(self, lines, fetched) -> None:
        """The frame's sprite collisions, added to those not yet read. The first since a read sets
        $D019's flag (bit 2 for sprites, bit 1 for the background), as the VIC-II does."""
        from .simscreen import collisions
        ss, sb = collisions(self.ram, self.io, self.chargen, lines, fetched)
        if ss and not self.collided_sprites:
            self.vic_flags |= 4
        if sb and not self.collided_background:
            self.vic_flags |= 2
        self.collided_sprites |= ss
        self.collided_background |= sb

    # ------------------------------------------------------------------ the VIC-II taking the bus
    # On a badline the VIC-II reads the row's screen and colour memory in cycles 15-54 (counting a line's
    # cycles from 1, as Christian Bauer's "The MOS 6567/6569 video controller" does), and for each sprite
    # with DMA on, its data in two cycles from cycle 58 (sprite 0) to cycle 10 of the next line (sprite
    # 7). Three cycles before, it pulls BA low: the 6510 stops at its next read, and carries on when the
    # VIC-II is done; writes go on until the bus is taken. Cycle k of line L is cycle L * 63 + k - 1.

    def resync_vic(self, now: int) -> None:
        """Start the VIC-II's bus decisions afresh from cycle ``now`` (at power-on, or after a jump in
        time, a snapshot restored)."""
        self.windows = []
        self.dma_left = [0] * 8
        line_start = now - now % CYCLES_PER_LINE
        self.next_decision, self.decisions = line_start + 11, 0
        if self.next_decision < now:
            self.next_decision, self.decisions = line_start + 54, 1
            if self.next_decision < now:
                self.next_decision, self.decisions = line_start + CYCLES_PER_LINE + 11, 0
        self.quiet_until = self.next_decision

    def _decide(self) -> None:
        """The VIC-II's next decision: is this line a badline (cycle 12), or which sprites read their data
        after cycle 55. With the registers as they are now."""
        at = self.next_decision
        start = at - at % CYCLES_PER_LINE
        line = (at // CYCLES_PER_LINE) % LINES
        io = self.io
        if self.decisions == 0:
            if line == 48:
                self.den = bool(io[0x11] & 0x10)
            if self.den and 48 <= line <= 247 and (line & 7) == (io[0x11] & 7):
                self.windows.append((start + 11, start + 54, start + 14, start + 54))
            self.next_decision, self.decisions = start + 54, 1
        else:
            for n in range(8):
                if not self.dma_left[n] and io[0x15] >> n & 1 and io[1 + 2 * n] == line & 0xFF:
                    self.dma_left[n] = 42 if io[0x17] >> n & 1 else 21
                if self.dma_left[n]:
                    self.dma_left[n] -= 1
                    s = start + 57 + 2 * n
                    self.windows.append((s - 3, s + 2, s, s + 2))
            self.next_decision, self.decisions = start + CYCLES_PER_LINE + 11, 0

    def stall(self, t0: int, n: int, writes: tuple[int, ...]) -> int:
        """The cycles an instruction (or an interrupt) of ``n`` cycles from ``t0`` waits for the VIC-II:
        ``writes``, which of its cycles are writes (the rest read)."""
        if t0 + n <= self.quiet_until:
            return 0
        self.windows = [w for w in self.windows if w[1] > t0]
        cur = t0
        for i in range(n):
            write = i in writes
            while True:
                while cur >= self.next_decision:
                    self._decide()
                for w in self.windows:
                    if (w[2] <= cur < w[3]) if write else (w[0] <= cur < w[1]):
                        cur = w[3] if write else w[1]
                        break
                else:
                    break
            cur += 1
        self.quiet_until = min([self.next_decision] + [w[0] for w in self.windows if w[1] > cur])
        return cur - t0 - n

    def irq(self) -> bool:
        """Whether something's asking for an interrupt."""
        return self.vic_irq() or self.cia_irq()

    def read(self, start: int, end: int) -> bytes:
        return bytes(self.peek(a) for a in range(start, end + 1))

    def write(self, start: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.poke((start + i) & 0xFFFF, b)


class CPU(MPU):
    """py65's 6502, its cycles counted from power-on."""


ILLEGAL = frozenset(op for op in range(256) if CPU.instruct[op].__name__ == "inst_not_implemented")


def _writes(op: int, n: int) -> tuple[int, ...]:
    """Which of an instruction's ``n`` cycles are writes: a store's last, a read-modify-write's last two
    (it writes the old value back, then the new), a push's, JSR's two pushes, BRK's three."""
    name, mode = CPU.disassemble[op]
    if name in ("STA", "STX", "STY", "PHA", "PHP"):
        return (n - 1,)
    if name in ("ASL", "LSR", "ROL", "ROR", "INC", "DEC") and mode not in ("acc", "imp"):
        return (n - 2, n - 1)
    if name == "JSR":
        return (3, 4)
    if name == "BRK":
        return (2, 3, 4)
    return ()


WRITES = [_writes(op, CPU.cycletime[op]) for op in range(256)]
RMW = frozenset(op for op in range(256) if len(WRITES[op]) == 2 and CPU.disassemble[op][0] != "JSR")   # (only reads' cycles vary)
IRQ_WRITES = (2, 3, 4)                  # an interrupt: two reads, three pushes, the vector's two reads


@dataclass
class _Checkpoint:
    id: int
    start: int
    end: int
    stop: bool
    enabled: bool
    op: int
    temporary: bool
    hits: int = 0
    condition: object = None              # (register, op, value) or None

    def info(self, hit: bool = False) -> Checkpoint:
        return Checkpoint(self.id, hit, self.start, self.end, self.stop, self.enabled, self.op, self.temporary,
                          self.hits)


_COND = re.compile(r"^\s*(A|X|Y|SP|PC)\s*(==|!=|>=|<=|>|<)\s*\$?([0-9A-Fa-f]+)\s*$", re.I)
_TESTS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, ">=": lambda a, b: a >= b,
          "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b}


def parse_condition(text: str):
    """A breakpoint's condition, as the assembler's BREAKPOINT directive writes it for VICE ("X == $14")."""
    m = _COND.match(text)
    if not m:
        raise MonitorError(f"The simulator can't test the condition {text!r} (only A, X, Y, SP or PC "
                           "compared with a number)")
    return m.group(1).upper(), _TESTS[m.group(2)], int(m.group(3), 16)


class Stopped(Exception):
    """Why a run stopped: 'checkpoint', 'brk', 'jam' (an illegal opcode), 'step', 'return', 'halt'."""

    def __init__(self, why: str, checkpoint: _Checkpoint | None = None):
        super().__init__(why)
        self.why, self.checkpoint = why, checkpoint


class Machine:
    """A simulated C64. ``roms``: from ``find_roms()``, or {} for RAM only."""

    def __init__(self, roms: dict[str, bytes] | None = None):
        self.roms = find_roms() if roms is None else roms
        self.skip_kernal = "kernal" not in self.roms      # step over KERNAL calls (no KERNAL to run)
        from .simdrive import ROUTINES, Bus
        self.bus = Bus()                                  # the serial bus, with drive 8 on it (emu.simdrive)
        self._serial = frozenset(ROUTINES)
        self.power_on()

    @property
    def drive(self):
        """Drive 8 (an ``emu.simdrive.Drive``)."""
        return self.bus.drives[8]

    def attach_disk(self, disk) -> None:
        """Put a disk in drive 8: a disk image's path, a ``DiskImage``, or None to take it out."""
        from ..disk.image import DiskImage
        self.drive.image = DiskImage.load(disk) if disk is not None and not isinstance(disk, DiskImage) else disk
        self.drive.changed = False

    def power_on(self) -> None:
        self.bus.reset()
        self.memory = Memory(self.roms, lambda: self.cpu.processorCycles)
        self.cpu = CPU(memory=self.memory, pc=0)
        self.cpu.processorCycles = 0
        self.cpu.pc = self.cpu.WordAt(0xFFFC) if self.memory.kernal_in else 0x0000
        self.cpu.sp = 0xFD
        self.cpu.p = 0x24
        self.checkpoints: dict[int, _Checkpoint] = {}
        self._next_id = 1
        self._index()
        self.stopped_at: int | None = None     # the PC a checkpoint last stopped the machine at
        # where a run started from a checkpoint's stop: the checkpoints there aren't tried again until
        # its instruction has run (an interrupt first, and back, doesn't stop there again)
        self.resume_at: int | None = None

    @property
    def cycles(self) -> int:
        return self.cpu.processorCycles

    @property
    def has_kernal(self) -> bool:
        return "kernal" in self.roms

    # ------------------------------------------------------------------ registers
    def registers(self) -> dict[str, int]:
        c, cyc = self.cpu, self.cpu.processorCycles
        return {"PC": c.pc, "A": c.a, "X": c.x, "Y": c.y, "SP": c.sp, "00": self.memory.ram[0],
                "01": self.memory.ram[1], "FL": c.p | 0x20, "LIN": (cyc // CYCLES_PER_LINE) % LINES,
                "CYC": cyc % CYCLES_PER_LINE}

    def set_register(self, name: str, value: int) -> None:
        c = self.cpu
        if name == "PC":
            c.pc = value & 0xFFFF
        elif name in ("A", "X", "Y", "SP"):
            setattr(c, name.lower(), value & 0xFF)
        elif name in ("FL", "P"):
            c.p = (value & 0xFF) | 0x20
        elif name in ("00", "01"):
            self.memory.poke(int(name), value)
        else:
            raise MonitorError(f"Unknown register {name}")

    # ------------------------------------------------------------------ checkpoints
    def add_checkpoint(self, start: int, end: int | None, op: int, stop: bool, temporary: bool) -> _Checkpoint:
        cp = _Checkpoint(self._next_id, start, start if end is None else end, stop, True, op, temporary)
        self._next_id += 1
        self.checkpoints[cp.id] = cp
        self._index()
        return cp

    def delete_checkpoint(self, cid: int) -> None:
        if self.checkpoints.pop(cid, None) is None:
            raise MonitorError(f"There's no checkpoint {cid}")
        self._index()

    def _index(self) -> None:
        """Which addresses have an exec checkpoint, and which a load or store one (for speed)."""
        self.exec_at: dict[int, list[_Checkpoint]] = {}
        watch: dict[int, int] = {}
        for cp in self.checkpoints.values():
            if not cp.enabled:
                continue
            for a in range(cp.start, cp.end + 1):
                if cp.op & OP_EXEC:
                    self.exec_at.setdefault(a, []).append(cp)
                if cp.op & (OP_LOAD | OP_STORE):
                    watch[a] = watch.get(a, 0) | (cp.op & (OP_LOAD | OP_STORE))
        self.memory.watch = watch

    def enable_checkpoint(self, cid: int, enabled: bool) -> None:
        cp = self.checkpoints.get(cid)
        if cp is None:
            raise MonitorError(f"There's no checkpoint {cid}")
        cp.enabled = enabled
        self._index()

    def _holds(self, cp: _Checkpoint) -> bool:
        if cp.condition is None:
            return True
        reg, test, value = cp.condition
        return test(self.registers()[reg], value)

    def _hit(self, cps: list[_Checkpoint]) -> _Checkpoint | None:
        """Count the checkpoints that are hit; the first that stops, if any."""
        stopper = None
        for cp in list(cps):
            if not self._holds(cp):
                continue
            cp.hits += 1
            if cp.temporary:
                self.checkpoints.pop(cp.id, None)
                self._index()
            if cp.stop and stopper is None:
                stopper = cp
        return stopper

    # ------------------------------------------------------------------ running
    def step(self, check: bool = True, interrupts: bool = False) -> None:
        """Run one instruction. Raises Stopped if it can't, or a checkpoint stops the machine first
        (``check``: look for an exec checkpoint at the PC before running). With ``interrupts``, an
        interrupt that's waiting (and the I flag clear) is taken instead: the 6510 goes to its handler
        through $FFFE, in 7 cycles."""
        c = self.cpu
        m = self.memory
        m.tick(c.processorCycles)
        if interrupts and not c.p & 0x04 and m.irq():
            t0 = c.processorCycles
            c.irq()
            c.processorCycles += m.stall(t0, 7, IRQ_WRITES)
            return
        pc = c.pc
        if check and pc in self.exec_at and pc != self.resume_at:
            cp = self._hit(self.exec_at[pc])
            if cp is not None:
                raise Stopped("checkpoint", cp)
        if pc in self._serial and m.kernal_in:
            # a KERNAL serial bus routine: done at the level of its commands and bytes, with the drive
            # (emu.simdrive) at the other end, then returned from
            self.bus.routine(pc, c, m.ram)
            sp = c.sp
            back = m.ram[0x100 + ((sp + 1) & 0xFF)] | m.ram[0x100 + ((sp + 2) & 0xFF)] << 8
            c.sp = (sp + 2) & 0xFF
            c.pc = (back + 1) & 0xFFFF
            c.processorCycles += 40                       # (about the routine's own work, and its RTS)
            if pc == self.resume_at:
                self.resume_at = None
            return
        op = self.memory.peek(pc)
        if op in ILLEGAL:
            raise Stopped("jam")
        if op == BRK:
            raise Stopped("brk")
        if self.skip_kernal and op == JSR:
            target = self.memory.peek((pc + 1) & 0xFFFF) | self.memory.peek((pc + 2) & 0xFFFF) << 8
            if target in KERNAL_TABLE:
                c.pc = (pc + 3) & 0xFFFF            # (as if the call returned at once)
                c.processorCycles += 12            # its JSR and RTS
                return
        t0 = c.processorCycles
        m.rmw = op in RMW
        m.rmw_read = None
        c.step()
        m.rmw = False
        c.processorCycles += m.stall(t0, c.processorCycles - t0, WRITES[op])
        if pc == self.resume_at:
            self.resume_at = None
        if m.touched:
            touched, m.touched = m.touched, []
            stopper = None
            for a, kind in touched:
                cps = [cp for cp in self.checkpoints.values() if cp.enabled and cp.op & kind and
                       cp.start <= a <= cp.end]
                stopper = stopper or self._hit(cps)
            if stopper is not None:
                raise Stopped("checkpoint", stopper)

    def run(self, max_cycles: int | None = None, halt: threading.Event | None = None, until=None,
            interrupts: bool = True, pace=None) -> Stopped:
        """Run until something stops the machine, and say what. ``until()``, tried after each
        instruction, stops it when true (why 'step'); ``halt`` being set stops it too ('halt'). Where a
        checkpoint stopped it last, its instruction runs without the checkpoints there being tried
        again (they were hit already). ``interrupts``: take them as they come."""
        end = None if max_cycles is None else self.cycles + max_cycles
        self.resume_at = self.cpu.pc if self.stopped_at == self.cpu.pc else None
        self.stopped_at = None
        n = 0
        try:
            while True:
                self.step(True, interrupts)
                if until is not None and until():
                    return Stopped("step")
                n += 1
                if n & 0x3FF == 0:
                    if pace is not None:
                        pace(self.cycles)
                    if halt is not None and halt.is_set():
                        return Stopped("halt")
                    if end is not None and self.cycles >= end:
                        return Stopped("halt")
        except Stopped as s:
            if s.why == "checkpoint" and s.checkpoint.op & OP_EXEC:
                self.stopped_at = self.cpu.pc
            return s

    def step_over_until(self):
        """The test for stepping over the instruction at the PC: a JSR runs until it returns."""
        c = self.cpu
        if self.memory.peek(c.pc) != JSR:
            return lambda: True
        back, sp = (c.pc + 3) & 0xFFFF, c.sp
        return lambda: c.pc == back and c.sp == sp

    def step_out_until(self):
        """Run until the routine the PC is in returns (an RTS or RTI from this level of the stack)."""
        c, mem = self.cpu, self.memory
        sp0 = c.sp

        def returns() -> bool:                           # the instruction about to run returns from here
            return mem.peek(c.pc) in (RTS, RTI) and c.sp >= sp0
        state = {"returning": returns()}

        def done() -> bool:
            if state["returning"]:
                return True                              # it has run
            state["returning"] = returns()
            return False
        return done

    # ------------------------------------------------------------------ BASIC
    def boot(self, max_cycles: int = 4_000_000) -> bool:
        """Run the KERNAL's reset until BASIC is READY. False if there's no KERNAL or it doesn't get there."""
        if not self.has_kernal:
            return False
        c = self.cpu
        stopped = self.run(max_cycles, until=lambda: c.pc in READY_LOOP)
        return stopped.why == "step"

    def load(self, prg: bytes) -> int:
        """Put a .prg in memory as LOAD puts it (BASIC's pointers too, at $0801). Returns its address."""
        if len(prg) < 3:
            raise MonitorError("The program is empty")
        start = prg[0] | prg[1] << 8
        self.memory.write(start, prg[2:])
        if start == 0x0801:
            end = start + len(prg) - 2
            self.memory.write(0x002D, bytes([end & 0xFF, end >> 8]) * 3)
        return start

    def type_keys(self, keys: bytes) -> None:
        """Into the KERNAL's keyboard buffer (ten at most)."""
        self.memory.write(0x0277, keys[:10])
        self.memory.poke(0x00C6, min(10, len(keys)))


class SimMonitor:
    """A ``Machine`` behind ``binmon.BinaryMonitor``'s methods, so the debugger and transcripts drive it
    as they drive VICE. As with VICE, any command while it's running stops it first (reporting the
    stop); ``resume``, ``step`` and ``step_out`` run it on a thread of its own, and report the stop
    when it comes. Events go to ``on_event(type, body)`` from whichever thread has them."""

    simulator = True

    def __init__(self, on_event=None, machine: Machine | None = None):
        self.on_event = on_event
        self.machine = machine or Machine()
        self.connected = False
        self.reg_names = {i: n for i, n in enumerate(["PC", "A", "X", "Y", "SP", "00", "01", "FL", "LIN", "CYC"])}
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_stop = ""                      # why the last run stopped (brk, jam, checkpoint, ...)
        self.real_speed = False                  # run no faster than a PAL C64 (the debugger's), or flat out

    # -------------------------------------------------------------- connection
    def connect(self, *args, **kw) -> None:
        self.connected = True

    def close(self) -> None:
        self._stop_running(report=False)
        self.connected = False

    def _event(self, etype: int, body: bytes = b"") -> None:
        if self.on_event:
            self.on_event(etype, body)

    def _report_stop(self, why: str = "") -> None:
        pc = self.machine.cpu.pc
        self._event(EVT_JAM if why == "jam" else EVT_STOPPED, struct.pack("<H", pc))

    @property
    def running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def _stop_running(self, report: bool = True) -> None:
        """Stop a run that's going on (as a VICE command would), reporting the stop."""
        t = self._thread
        if t is None:
            return
        self._halt.set()
        t.join()
        self._thread = None
        if report and self.last_stop == "halt":
            self._report_stop()

    def _start(self, until=None, interrupts: bool = True) -> None:
        if not self.connected:
            raise MonitorError("The simulator isn't running")
        self._stop_running()
        self._halt.clear()
        self._event(EVT_RESUMED, struct.pack("<H", self.machine.cpu.pc))

        pace = self._pacer()

        def go():
            s = self.machine.run(halt=self._halt, until=until, interrupts=interrupts, pace=pace)
            self.last_stop = s.why
            if s.why != "halt":
                self._thread = None
                self._report_stop(s.why)
        self.last_stop = ""
        self._thread = threading.Thread(target=go, name="l64s-sim", daemon=True)
        self._thread.start()

    def _pacer(self):
        """Keeps a run to a PAL C64's speed while ``real_speed`` is on (it can change as it runs): it sleeps
        whenever the C64's time gets ahead of the clock's."""
        import time
        since: list = []

        def pace(cycles: int) -> None:
            if not self.real_speed:
                since.clear()
                return
            now = time.monotonic()
            if not since:
                since[:] = [now, cycles]
                return
            ahead = (cycles - since[1]) / 985_248 - (now - since[0])
            if ahead > 0.002:
                self._halt.wait(ahead)
        return pace

    # -------------------------------------------------------------- commands
    def request(self, cmd: int, body: bytes = b"", timeout: float = 5.0):
        raise MonitorError("The simulator doesn't take VICE's monitor commands")

    def ping(self) -> None:
        self._stop_running()

    def resume(self) -> None:
        self._start()

    def quit(self) -> None:
        self.close()

    def reset(self, hard: bool = False) -> None:
        self._stop_running()
        self.machine.power_on()
        self.machine.boot()

    def read_memory(self, start: int, end: int, side_effects: bool = False) -> bytes:
        self._stop_running()
        return self.machine.memory.read(start, end)

    def write_memory(self, start: int, data: bytes, side_effects: bool = False) -> None:
        if not data or start + len(data) > 0x10000:
            raise MonitorError("Write must be 1 or more bytes inside $0000-$FFFF")
        self._stop_running()
        self.machine.memory.write(start, data)

    def registers_available(self) -> dict[int, str]:
        return dict(self.reg_names)

    def get_registers(self) -> dict[str, int]:
        self._stop_running()
        return self.machine.registers()

    def set_register(self, name: str, value: int) -> None:
        self._stop_running()
        self.machine.set_register(name, value)

    def add_checkpoint(self, start: int, end: int | None = None, op: int = OP_EXEC,
                       stop: bool = True, temporary: bool = False) -> Checkpoint:
        self._stop_running()
        return self.machine.add_checkpoint(start, end, op, stop, temporary).info()

    def set_condition(self, cid: int, condition: str) -> None:
        self._stop_running()
        cp = self.machine.checkpoints.get(cid)
        if cp is None:
            raise MonitorError(f"There's no checkpoint {cid}")
        cp.condition = parse_condition(condition)

    def delete_checkpoint(self, cid: int) -> None:
        self._stop_running()
        self.machine.delete_checkpoint(cid)

    def enable_checkpoint(self, cid: int, enabled: bool) -> None:
        self._stop_running()
        self.machine.enable_checkpoint(cid, enabled)

    def checkpoint_hits(self, cid: int) -> int:
        cp = self.machine.checkpoints.get(cid)
        return cp.hits if cp else 0

    def step(self, count: int = 1, over: bool = False) -> None:
        """Run ``count`` instructions (over: a JSR counts as one, its subroutine run too)."""
        self._stop_running()
        m = self.machine
        left = {"n": max(1, count), "test": m.step_over_until() if over else None}

        def until():
            t = left["test"]
            if t is not None and not t():
                return False
            left["n"] -= 1
            if left["n"] <= 0:
                return True
            left["test"] = m.step_over_until() if over else None
            return False
        # a step is the instruction at the PC: no interrupt. Over a JSR, the subroutine runs, with them
        self._start(until, interrupts=over and m.memory.peek(m.cpu.pc) == JSR)

    def step_out(self) -> None:
        self._stop_running()
        self._start(self.machine.step_out_until())

    def dump(self, path: str, save_roms: bool = False, save_disks: bool = False) -> None:
        """Save the machine as a snapshot (see save_snapshot)."""
        self._stop_running()
        save_snapshot(self.machine, Path(path))

    def undump(self, path: str) -> int:
        """Load a snapshot (see load_snapshot); the PC it was taken at."""
        self._stop_running()
        try:
            return load_snapshot(self.machine, Path(path))
        except (OSError, ValueError) as e:
            raise MonitorError(str(e)) from None

    def autostart(self, path: str, run: bool = True) -> None:
        raise MonitorError("The simulator doesn't autostart")

    @property
    def cycles(self) -> int:
        """The cycles run since power-on (exact)."""
        return self.machine.cycles


class SimRun:
    """A worker (a transcript's Runner, say) on a simulated C64, as ``profiler.ViceRun`` runs one on
    VICE: ``start()``, ``stop()``, ``quit()``, ``worker``, ``monitor``; ``on_end(message)`` from the
    worker's thread when it's done ("" if stop() ended it)."""

    def __init__(self, make_worker, on_end, machine: Machine | None = None):
        self.make_worker, self.on_end = make_worker, on_end
        self.machine = machine
        self.monitor: SimMonitor | None = None
        self.worker = None
        self._stopping = False

    def start(self):
        self.monitor = SimMonitor(self._event, self.machine)
        self.monitor.connect()
        self.worker = self.make_worker(self.monitor)
        threading.Thread(target=self._work, name="l64s-sim-run", daemon=True).start()

    def _event(self, rtype, body):
        if self.worker:
            self.worker.vice_event(rtype, body)

    def _work(self):
        msg = self.worker.run()
        if self._stopping:
            msg = ""
        self.monitor.close()
        self.on_end(msg)

    def stop(self):
        self._stopping = True
        if self.worker:
            self.worker.stop_soon()

    def quit(self):
        self.stop()


def basic_sys(program: bytes) -> int | None:
    """The address in a BASIC loader's SYS (its first line), from the program's bytes at $0801."""
    m = re.search(rb"\x9e\s*\(?\s*(\d+)", program[4:program.find(b"\0", 4) if b"\0" in program[4:] else None])
    return int(m.group(1)) if m and int(m.group(1)) <= 0xFFFF else None


# ---------------------------------------------------------------------- snapshots
# A snapshot of the simulator is a .vsf with VICE's MAINCPU and C64MEM modules, so the snapshot
# manager shows and compares it like VICE's, and a module of its own (snapshot.SIM_MODULE) with the
# I/O area and the chips' state. VICE can't load one (it has none of its chips' modules); a VICE
# snapshot loads into the simulator as its RAM and registers.

_STATE = ("vic_flags", "next_raster", "ta_latch", "ta_value", "ta_t0", "ta_running", "ta_oneshot", "ta_next",
          "cia_flags", "cia_mask", "joysticks", "collided_sprites", "collided_background", "next_frame",
          "frame_log")


def _module(name: str, major: int, minor: int, body: bytes) -> bytes:
    return name.encode("ascii").ljust(16, b"\0") + bytes([major, minor]) + struct.pack("<I", 22 + len(body)) + body


def save_snapshot(machine: Machine, path: Path) -> None:
    import json

    from ..snapshot import MAGIC, SIM_MODULE, VERSION_MAGIC
    c, mem = machine.cpu, machine.memory
    cpu = struct.pack("<QBBBBHB", c.processorCycles, c.a, c.x, c.y, c.sp, c.pc, (c.p | 0x20) & 0xFF)
    ram = bytes([mem.ram[1], mem.ram[0], 0, 0]) + bytes(mem.ram)       # the processor port, then RAM
    state = {k: getattr(mem, k) for k in _STATE}
    state["held"] = sorted(mem.held)
    state["frame_start"] = list(mem.frame_start)
    state["skip_kernal"] = machine.skip_kernal
    sim = bytes(mem.io) + json.dumps(state).encode()
    head = MAGIC + bytes([2, 0]) + b"C64SC".ljust(16, b"\0") + VERSION_MAGIC + bytes(8)
    path.write_bytes(head + _module("MAINCPU", 1, 1, cpu) + _module("C64MEM", 0, 0, ram)
                     + _module(SIM_MODULE, 1, 0, sim))


def load_snapshot(machine: Machine, path: Path) -> int:
    """Put a snapshot's machine in this one: all of it from the simulator's own, the RAM, registers and
    processor port from VICE's (whose chips aren't simulated: the I/O area is left as it was). The
    checkpoints stay. Returns the PC."""
    import json

    from ..snapshot import SIM_MODULE, read_vsf
    snap = read_vsf(path)
    mem, c = machine.memory, machine.cpu
    mem.ram[:] = snap.ram
    port = snap.module_data["C64MEM"][:2]
    mem.ram[1], mem.ram[0] = port[0], port[1]
    mem._bank()
    r = snap.registers
    c.a, c.x, c.y, c.sp, c.pc, c.p = r["A"], r["X"], r["Y"], r["SP"], r["PC"], r["FL"] | 0x20
    c.processorCycles = snap.clock
    if snap.simulated:
        data = snap.module_data[SIM_MODULE]
        mem.io[:] = data[:0x1000]
        state = json.loads(data[0x1000:].decode())
        for k in _STATE:
            if k in state:
                setattr(mem, k, state[k])
        mem.held = {tuple(k) for k in state.get("held", [])}
        mem.frame_log = [tuple(x) for x in mem.frame_log]
        if "frame_start" in state:
            mem.frame_start = bytes(state["frame_start"])
        machine.skip_kernal = state.get("skip_kernal", machine.skip_kernal)
    else:
        from .simscreen import registers_now
        mem.schedule_raster()
        mem.frame_start, mem.frame_log, mem.last_frame = registers_now(mem.io), [], None
    mem.resync_vic(c.processorCycles)
    mem.next_line = c.processorCycles - c.processorCycles % CYCLES_PER_LINE + 14
    machine.stopped_at = machine.resume_at = None
    return c.pc
