"""Profiler: where a running program spends its time, from samples of the 6510's PC in VICE.

VICE's binary monitor is only looked at once a frame, so asking for the registers every few
milliseconds gives the same moment each time (the end of the frame). Instead the sampler has VICE
run a random number of instructions (``advance``) and stop, and reads where it stopped: the PC,
and the raster line and cycle, which the stop doesn't change. The stops are spread evenly over the
instructions the program runs, wherever they fall in the frame.

Each sample counts with the cycles of the instruction it stopped at, so a routine's share is of
the CPU's time, not of its instructions. The raster position also gives how much emulated time
went by between samples (always less than a frame), so the sampler keeps the program at its real
speed: the game can be played while it's measured.

``Resolver`` names where the PC is: the routine (the label it's in: a C function, an assembler
label, a KERNAL routine) and the source line. ``Profile`` adds the samples up.
"""
from __future__ import annotations

import bisect
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .analyser import cycles as _cycles
from .asm.opcodes import build_reverse_table

_OPS = build_reverse_table(include_illegal=True)

# The KERNAL routines a program's time most often goes to (mostly the interrupt's work), by their
# first address: a PC in the KERNAL is in the routine that starts at or before it.
KERNAL_ROUTINES = {
    0xE544: "clear screen", 0xE716: "screen output", 0xEA31: "IRQ handler", 0xEA81: "IRQ return",
    0xEA87: "SCNKEY keyboard scan", 0xEB48: "keyboard decode", 0xED09: "serial bus", 0xF13E: "GETIN",
    0xF1CA: "CHROUT", 0xF69B: "UDTIM clock", 0xFE43: "NMI", 0xFF48: "IRQ entry",
}
_KERNAL_STARTS = sorted(KERNAL_ROUTINES)

# Labels that are places inside a routine, not routines: cheap locals (@loop, !loop), cc65's own
# (L0012), ld65's symbols (__MAIN_START__) and macro expansions
_INNER = re.compile(r"^(@|!|L[0-9A-F]{4}$|__.*__$)|__m")


def cycles_at(memory: bytes, pc: int) -> int:
    """The base cycles of the instruction at pc (2 for a byte that isn't one)."""
    op = _OPS.get(memory[pc]) if memory else None
    return _cycles(*op)[0] if op else 2


@dataclass(frozen=True)
class Routine:
    name: str
    address: int
    where: str = ""          # the file it's in, to open ("" if none: the ROMs, a library)
    module: str = ""         # what it's part of, to show: main.c, c64.lib: popax.o, KERNAL


class Resolver:
    """Which routine and source line a PC is in.

    ``symbols``: address -> label (the program's labels); ``srcmap``: address -> (file, line) for
    the first byte of each line's code; ``line_tables``: emu.clines.LineTable-s for code whose lines
    span many bytes (C). From ld65's debug file (cc65dbg.code_ranges), ``functions``: [(start, end,
    name)] of the C functions (all of them, static ones too), and ``modules``: [(start, end, name)]
    of each module, which a label's routine doesn't run on past. ``c``: the names are cc65's (C's
    are _name)."""

    def __init__(self, symbols: dict[int, str], srcmap: dict[int, tuple[str, int]] | None = None,
                 line_tables: list | None = None, c: bool = False, functions: list | None = None,
                 modules: list | None = None, outside: str = ""):
        self.c = c
        self.outside = outside      # the name for unlabelled code that's in no module (cc65's: c64.lib)
        self.labels = sorted((a, n) for a, n in symbols.items() if n and not _INNER.search(n))
        self._starts = [a for a, _n in self.labels]
        self.srcmap = srcmap or {}
        self._src_starts = sorted(self.srcmap)
        self.line_tables = [t for t in (line_tables or []) if t]
        self.functions = sorted(f for f in (functions or []) if f[1] > f[0])
        self._fstarts = [f[0] for f in self.functions]
        self.modules = sorted(m for m in (modules or []) if m[1] > m[0])
        self._mstarts = [m[0] for m in self.modules]
        self._routines: dict[int, Routine] = {}

    def line(self, pc: int) -> tuple[str, int] | None:
        for t in self.line_tables:
            hit = t.line_at(pc)
            if hit:
                return hit
        if pc in self.srcmap:
            return self.srcmap[pc]
        i = bisect.bisect_right(self._src_starts, pc) - 1
        # a line making several instructions (a macro's): the line it starts at, if it's close
        if i >= 0 and pc - self._src_starts[i] < 0x40:
            nxt = self._src_starts[i + 1] if i + 1 < len(self._src_starts) else 0x10000
            if pc < nxt:
                return self.srcmap[self._src_starts[i]]
        return None

    def address_of(self, name: str) -> int | None:
        """Where a routine starts, from its name as it's written in the source (a label, any case if
        no label matches exactly; a C function, with or without "()"), or a $hex address."""
        name = name.strip()
        if name.startswith("$"):
            try:
                return int(name[1:], 16) & 0xFFFF
            except ValueError:
                return None
        name = name.removesuffix("()")
        wanted = [name] + (["_" + name] if self.c else [])
        for w in wanted:
            for a, n in self.labels:
                if n == w:
                    return a
            for a, _b, n in self.functions:
                if n == w:
                    return a
        low = {w.lower() for w in wanted}
        return next((a for a, n in self.labels if n.lower() in low), None)

    def in_program(self, pc: int) -> bool:
        """Is pc in the program's code (not the ROMs', nor the autostart's)?"""
        return (self._containing(self.functions, self._fstarts, pc) is not None
                or self._containing(self.modules, self._mstarts, pc) is not None or self.line(pc) is not None)

    def routine(self, pc: int) -> Routine:
        r = self._routines.get(pc)
        if r is None:
            r = self._routines[pc] = self._find(pc)
        return r

    @staticmethod
    def _containing(ranges, starts, pc):
        """The smallest of the (start, end, name) ranges holding pc."""
        best = None
        i = bisect.bisect_right(starts, pc) - 1
        while i >= 0 and starts[i] > pc - 0x4000:
            a, b, _name = ranges[i]
            if a <= pc < b and (best is None or b - a < best[1] - best[0]):
                best = ranges[i]
            i -= 1
        return best

    def _name(self, name: str) -> str:
        if self.c and name.startswith("_") and not name.startswith("__"):
            return name[1:] + "()"
        return name

    def _where(self, address: int) -> str:
        src = self.line(address)
        return src[0] if src else ""

    def _find(self, pc: int) -> Routine:
        f = self._containing(self.functions, self._fstarts, pc)
        if f:
            where = self._where(f[0])
            return Routine(self._name(f[2]), f[0], where, Path(where).name if where else "")
        mod = self._containing(self.modules, self._mstarts, pc)
        in_program = mod is not None or self.line(pc) is not None
        if pc >= 0xE000 and not in_program:
            i = bisect.bisect_right(_KERNAL_STARTS, pc) - 1
            if i >= 0:
                a = _KERNAL_STARTS[i]
                return Routine(f"KERNAL {KERNAL_ROUTINES[a]}", a, "", "KERNAL")
            return Routine("KERNAL", 0xE000, "", "KERNAL")
        if 0xA000 <= pc < 0xC000 and not in_program:
            return Routine("BASIC ROM", 0xA000, "", "BASIC")
        i = bisect.bisect_right(self._starts, pc) - 1
        low = mod[0] if mod else 0
        if i < 0 or self._starts[i] < low or (not in_program and pc - self._starts[i] > 0x1000):
            if mod:                                   # code of a module's with no label before it
                where = self._where(mod[0])
                return Routine(mod[2], mod[0], where, mod[2])
            return Routine(f"${pc & 0xFF00:04X} page", pc & 0xFF00)
        a, name = self.labels[i]
        if self.modules and mod is None and self._containing(self.modules, self._mstarts, a) is not None:
            # the label is a module's, and the PC is past its end: code nothing names
            return Routine(self.outside or f"${pc & 0xFF00:04X} page", pc & 0xFF00 if not self.outside else 0)
        where = self._where(a)
        module = mod[2] if mod else Path(where).name if where else self.outside
        return Routine(self._name(name), a, where, module)


def resolver_for(res, symbols: dict[int, str] | None = None) -> Resolver:
    """The Resolver for a build (project.build.BuildResult): its labels, lines and, for C, its
    functions and modules. ``symbols``: address -> label from the build's labels file or Kick
    Assembler's debug dump (the debugger's), for builds the built-in assembler didn't make."""
    from .emu.clines import LineTable
    symbols = dict(symbols or {})
    r = res.asm_result
    if r is not None:                         # the built-in assembler: its address labels
        for key in r.label_locs:
            if key in r.symbols and "__m" not in key:
                symbols.setdefault(r.symbols[key], r.names.get(key, key))
    tables = [LineTable(res.c_lines), LineTable(res.asm_lines)]
    if res.c_debug is not None:
        from .cc65dbg import code_ranges
        symbols.update(res.c_debug.symbols)   # (static functions too, which the labels file leaves out)
        functions, modules = code_ranges(res.c_debug)
        return Resolver(symbols, res.srcmap, tables, c=True, functions=functions, modules=modules,
                        outside="c64.lib")
    return Resolver(symbols, res.srcmap, tables)


@dataclass
class Row:
    """A line of a profile's table: a routine or a source line."""
    name: str
    share: float             # of the CPU's time, 0-1
    samples: int
    file: str = ""
    line: int = 0
    address: int = 0
    module: str = ""         # what a routine is part of (main.c, c64.lib: popax.o, KERNAL)


class Profile:
    """The samples so far, added up. Not thread-safe: the sampler hands samples over in batches."""

    def __init__(self, resolver: Resolver, memory: bytes = b"", lines_per_frame: int = 312):
        self.resolver = resolver
        self.memory = memory
        self.lines_per_frame = lines_per_frame
        self.clear()

    def clear(self):
        self.samples = 0
        self.total = 0                                    # weighted: cycles
        self.by_pc: Counter = Counter()                   # pc -> cycles
        self.count_pc: Counter = Counter()                # pc -> samples
        self.raster: list[Counter] = [Counter() for _ in range(self.lines_per_frame)]   # line -> routine -> cycles
        self.emulated = 0                                 # cycles of the program's time measured

    def add(self, pc: int, raster_line: int):
        w = cycles_at(self.memory, pc)
        self.samples += 1
        self.total += w
        self.by_pc[pc] += w
        self.count_pc[pc] += 1
        if 0 <= raster_line < self.lines_per_frame:
            self.raster[raster_line][self.resolver.routine(pc)] += w

    def routines(self) -> list[Row]:
        cyc: Counter = Counter()
        n: Counter = Counter()
        for pc, w in self.by_pc.items():
            r = self.resolver.routine(pc)
            cyc[r] += w
            n[r] += self.count_pc[pc]
        out = []
        for r, w in cyc.most_common():
            src = self.resolver.line(r.address) if r.where else None
            out.append(Row(r.name, w / self.total, n[r], r.where, src[1] if src else 0, r.address, r.module))
        return out

    def lines(self) -> list[Row]:
        """The source lines the time goes to (what has no line, such as the KERNAL, isn't listed)."""
        cyc: Counter = Counter()
        n: Counter = Counter()
        first: dict = {}
        for pc, w in self.by_pc.items():
            src = self.resolver.line(pc)
            if src is None:
                continue
            cyc[src] += w
            n[src] += self.count_pc[pc]
            first[src] = min(first.get(src, pc), pc)
        return [Row(f"{Path(f).name}:{ln}", w / self.total, n[(f, ln)], f, ln, first[(f, ln)])
                for (f, ln), w in cyc.most_common()]

    def line_shares(self) -> dict[str, dict[int, tuple[float, int]]]:
        """For the editor: {file (resolved): {line: (share of the time, samples)}}."""
        out: dict[str, dict[int, tuple[float, int]]] = {}
        for r in self.lines():
            out.setdefault(str(Path(r.file).resolve()), {})[r.line] = (r.share, r.samples)
        return out

    def raster_lines(self) -> list[list[tuple[Routine, float]]]:
        """For each raster line: the routines running on it, with their share of the line's samples."""
        out = []
        for c in self.raster:
            t = sum(c.values())
            out.append([(r, w / t) for r, w in c.most_common()] if t else [])
        return out

    def report(self, seconds: float = 0.0, top: int = 30) -> str:
        """The profile as text: the routines, then the lines."""
        out = [f"Profile: {self.samples:,} samples" + (f" over {seconds:.1f} s of the program" if seconds else ""), "",
               "Routines:"]
        for r in self.routines()[:top]:
            out.append(f"{r.share * 100:6.1f}%  {r.name:<32} {r.module}")
        out += ["", "Lines:"]
        for r in self.lines()[:top]:
            out.append(f"{r.share * 100:6.1f}%  {r.name}")
        return "\n".join(out) + "\n"

    def files(self) -> list[Row]:
        cyc: Counter = Counter()
        n: Counter = Counter()
        for pc, w in self.by_pc.items():
            src = self.resolver.line(pc)
            r = self.resolver.routine(pc)
            name = Path(src[0]).name if src else (r.module or "no source")
            cyc[name] += w
            n[name] += self.count_pc[pc]
        return [Row(name, w / self.total, n[name]) for name, w in cyc.most_common()]


# ---------------------------------------------------------------------------- sampling in VICE

PAL = (63, 312, 985248)          # cycles a line, lines a frame, cycles a second
NTSC = (65, 263, 1022727)


MIN_STEP, MAX_STEP = 50, 1300      # instructions between samples, on average: 2 * MAX_STEP of the
                                   # longest (7 cycles) is still less than a frame


class Sampler:
    """Takes samples from a BinaryMonitor's VICE, on a thread, until stop(). ``on_batch(list of
    (pc, raster line), emulated cycles)`` is called from the thread every ``batch`` samples.

    Sampling starts once the program has: when the PC is first somewhere ``is_program`` says is
    the program's (or after ``start_within`` seconds, for a program with no debug information,
    such as BASIC). ``on_start(memory, timing)`` is called then, with the 64K the CPU sees (for
    the instructions' cycles) and the machine's timing (PAL or NTSC).

    The program runs at its real speed (``real_time``), or as fast as the sampling allows. Each
    stop costs a millisecond or so, so the instructions between samples (a random number, so that
    the samples don't fall in step with a loop) average ``mean_step``, which grows while the
    program falls behind its real speed and shrinks while there's time to spare: as many samples
    as can be taken without slowing the program down."""

    def __init__(self, monitor, on_batch, is_program=None, on_start=None, mean_step: int = 300,
                 batch: int = 200, real_time: bool = True, start_within: float = 10.0):
        self.monitor = monitor
        self.on_batch = on_batch
        self.is_program = is_program or (lambda pc: True)
        self.on_start = on_start
        self.start_within = start_within
        self.timing = PAL
        self.started = False
        self.mean_step = mean_step
        self.batch = batch
        self.real_time = real_time
        self._stop = threading.Event()
        self._stopped = threading.Event()        # VICE says it's stopped (after an advance)
        self.error: str | None = None
        self.thread: threading.Thread | None = None

    def vice_event(self, rtype: int, body: bytes):
        """Pass the monitor's events here (its on_event)."""
        from .emu.binmon import EVT_STOPPED
        if rtype == EVT_STOPPED or rtype == -1:
            self._stopped.set()

    def start(self):
        self.thread = threading.Thread(target=self.run, name="profiler", daemon=True)
        self.thread.start()

    def stop_soon(self):
        """Stop at the next sample (without waiting for it)."""
        self._stop.set()

    def stop(self):
        self._stop.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(3)

    def run(self):
        import random

        from .emu.binmon import MonitorError
        rnd = random.Random()
        m = self.monitor
        out: list[tuple[int, int]] = []
        emulated = 0                                # cycles since the last batch
        prev = None
        t0, done, slept = time.monotonic(), 0, 0.0  # the batch's start: wall time, emulated cycles
        try:
            if not self._wait_for_program():
                return ""
            per_line, lines, clock = self.timing
            frame = per_line * lines
            t0 = time.monotonic()
            while not self._stop.is_set() and m.connected:
                regs = self._advance(rnd.randint(1, 2 * self.mean_step))
                line, cyc = regs.get("LIN", 0), regs.get("CYC", 0)
                out.append((regs.get("PC", 0), line))
                pos = line * per_line + cyc
                if prev is not None:
                    emulated += (pos - prev) % frame          # less than a frame went by
                prev = pos
                if self.real_time:
                    ahead = (emulated - done) / clock - (time.monotonic() - t0)
                    if ahead > 0.002:
                        time.sleep(ahead)
                        slept += ahead
                    elif ahead < -0.25:                       # far behind (VICE was busy): from now on
                        t0, done = time.monotonic(), emulated
                if len(out) >= self.batch:
                    if self.real_time:
                        wall = time.monotonic() - t0
                        if emulated / clock < 0.97 * wall:    # slower than the real thing
                            self.mean_step = min(MAX_STEP, int(self.mean_step * 1.3) + 1)
                        elif slept > 0.2 * wall:              # time to spare: sample more often
                            self.mean_step = max(MIN_STEP, int(self.mean_step * 0.85))
                    self.on_batch(out, emulated)
                    out, emulated = [], 0
                    t0, done, slept = time.monotonic(), 0, 0.0
        except (MonitorError, OSError, ConnectionError) as e:
            if m.connected and not self._stop.is_set():
                self.error = str(e)
        finally:
            if out:
                self.on_batch(out, emulated)
            self._resume()
        return f"VICE stopped answering: {self.error}" if self.error else ""

    def _advance(self, count: int) -> dict[str, int]:
        """Run count instructions; the registers where VICE stopped."""
        from .emu.binmon import MonitorError
        self._stopped.clear()
        self.monitor.step(count)
        if not self._stopped.wait(3):
            raise MonitorError("VICE didn't stop after running the program")
        return self.monitor.get_registers()

    def _wait_for_program(self) -> bool:
        """Run (as fast as VICE goes) until the program's started. False if stopped first."""
        m = self.monitor
        deadline = time.monotonic() + self.start_within
        while not self._stop.is_set() and m.connected:
            pc = self._advance(MAX_STEP).get("PC", 0)
            if self.is_program(pc) or time.monotonic() > deadline:
                memory = m.read_memory(0, 0xFFFF)
                self.timing = timing_for(memory[0x02A6])
                self.started = True
                if self.on_start:
                    self.on_start(memory, self.timing)
                return True
        return False

    def _resume(self):
        from .emu.binmon import MonitorError
        m = self.monitor
        if m.connected:
            try:
                m.resume()
            except (MonitorError, OSError):
                pass


def timing_for(pal_flag: int) -> tuple[int, int, int]:
    """The machine's timing from the KERNAL's PAL/NTSC flag ($02A6: 1 for PAL)."""
    return PAL if pal_flag else NTSC



class ViceRun:
    """A program running in VICE (started for this), with a worker on its monitor: a Sampler or a
    routine_timing.Timer, anything with ``vice_event(type, body)``, ``run() -> message`` (on this
    run's thread; "" when all went well) and ``stop_soon()``. ``on_end(message)`` comes from the
    thread when the worker's done: "" if stop() ended it."""

    def __init__(self, target, make_worker, on_end, emulator: str = "", extra_args: list[str] | None = None):
        self.target, self.make_worker, self.on_end = target, make_worker, on_end
        self.emulator, self.extra_args = emulator, list(extra_args or [])
        self.proc = None
        self.monitor = None
        self.worker = None
        self._stopping = False

    def start(self):
        """Launch VICE (raises FileNotFoundError without it), and run the worker on a thread."""
        from .emu import vice
        from .emu.binmon import BinaryMonitor
        port = vice.free_port()
        self.proc = vice.launch(self.target, self.emulator, None, port, self.extra_args)
        self.monitor = BinaryMonitor(self._event)
        self.worker = self.make_worker(self.monitor)
        threading.Thread(target=self._work, args=(port,), name="vice-run", daemon=True).start()

    def _event(self, rtype, body):
        if self.worker:
            self.worker.vice_event(rtype, body)

    def _work(self, port: int):
        from .emu import vice
        from .emu.binmon import MonitorError
        if not vice.wait_for_port(port, 15):
            self.on_end("VICE didn't open its monitor port")
            return
        try:
            self.monitor.connect(port=port)
        except (OSError, MonitorError) as e:
            self.on_end(f"Couldn't talk to VICE: {e}")
            return
        msg = self.worker.run()
        if self._stopping:
            msg = ""
        elif not msg and not self.monitor.connected:
            msg = "VICE was closed"
        self.monitor.close()            # (VICE carries on running the program)
        self.on_end(msg)

    def stop(self):
        """Stop the worker. VICE carries on running the program."""
        self._stopping = True
        if self.worker:
            self.worker.stop_soon()

    def quit(self):
        """Stop the worker and close VICE."""
        self.stop()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class ProfileRun(ViceRun):
    """VICE with a Sampler: ``on_start(memory, timing)`` when the program's started, ``on_batch(samples,
    emulated cycles)``, ``on_end(message)``, all from a thread."""

    def __init__(self, target, resolver: Resolver, on_start, on_batch, on_end, emulator: str = "",
                 extra_args: list[str] | None = None):
        super().__init__(target, lambda m: Sampler(m, on_batch, resolver.in_program, on_start), on_end,
                         emulator, extra_args)

    @property
    def sampler(self) -> Sampler | None:
        return self.worker
