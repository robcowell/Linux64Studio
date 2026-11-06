"""Transcripts: scripts that set up the machine, run the program's routines in VICE and check what
they did, as CBM prg Studio's debugger transcripts do (its commands work here too), but on
VICE's whole C64, so code that touches the VIC-II, SID or CIAs can be tested.

A transcript is a text file (.transcript), a command a line::

    ; does add16 add?
    set num1 $34 $12
    set num2 $01 $00
    call add16
    check word result = $1235
    check cycles < 60

``Runner`` runs one in a ViceRun: VICE is started with no program (the project's disk image in drive
8, if it writes one), the program is put into memory
once BASIC is READY (as LOAD would), and each command then runs in turn. Bare numbers are hex,
as in the debugger ($ may be written too); #12 is decimal, %1010 binary. Where an address goes, a
label of the program's may (a C function or variable too), with +n or -n.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

from .emu.cycles import CycleCounter
from .emu.values import ValueError_, flags_text, parse_bytes, parse_number

REGISTERS = {"a": "A", "x": "X", "y": "Y", "sp": "SP", "pc": "PC", "p": "FL", "fl": "FL"}
FLAGS = {"n": 7, "v": 6, "b": 4, "d": 3, "i": 2, "z": 1, "c": 0}
OPS = {"=": lambda a, b: a == b, "==": lambda a, b: a == b, "<>": lambda a, b: a != b, "!=": lambda a, b: a != b,
       "<": lambda a, b: a < b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}
VERBS = {"run", "until", "call", "goto", "set", "fill", "check", "show", "watch", "step", "stepover",
         "wait", "type", "joystick", "hold", "release", "restore", "interrupts", "clearregs", "resetstack", "skipkernal", "end", "break", "timeout",
         *REGISTERS}

READY_LOOP = range(0xE5CD, 0xE5D7)        # the KERNAL waiting for a key, at READY.
KEYBUF, KEYCOUNT, KEYBUF_SIZE = 0x0277, 0x00C6, 10      # the KERNAL's keyboard buffer
TRAP = 0x0000                              # where a call returns to: its RTS goes to $0000
PAL_HZ = 985_248                           # a PAL C64's cycles a second


class TranscriptError(Exception):
    pass


@dataclass(frozen=True)
class Command:
    line: int           # 1-based
    verb: str
    args: str
    text: str           # the line as written


@dataclass
class Outcome:
    line: int
    text: str           # the command
    ok: bool | None     # a check passed (True) or failed (False); None: anything else
    message: str


def parse(text: str) -> list[Command]:
    """The commands, a line each (comments start with ; or //; blank lines are skipped). Raises
    TranscriptError for a line that isn't a command, naming it."""
    out = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("//"):
            continue
        line = re.split(r"\s;", line, maxsplit=1)[0].strip()     # a comment after the command
        m = re.match(r"([A-Za-z]+)\s*(.*)$", line)
        verb = m.group(1).lower() if m else ""
        if verb not in VERBS:
            raise TranscriptError(f"Line {n}: '{line}' isn't a transcript command")
        out.append(Command(n, verb, m.group(2).strip(), line))
    return out


class Stop(Exception):
    """The transcript stops here (end, break, or a command that can't go on)."""


class Runner:
    """Runs a transcript in VICE: a ViceRun's worker (vice_event, run, stop_soon).

    ``program``: the .prg's bytes (with its load address); ``symbols``: name -> address for labels
    (profiler.Resolver.symbol_table); ``on_outcome(Outcome)``: each command's result, from the
    thread as it comes."""

    def __init__(self, monitor, commands: list[Command], program: bytes, symbols: dict[str, int], on_outcome,
                 timeout: float = 10.0, overlays: list[tuple[int, bytes]] | None = None, folder=None):
        self.monitor, self.commands, self.program = monitor, commands, program
        self.overlays = overlays or []          # memory to load too (overlays.load_all)
        self.folder = folder                    # the project's (for snapshots a restore names)
        self.symbols, self.on_outcome = symbols, on_outcome
        self.timeout = timeout
        self.outcomes: list[Outcome] = []
        self.cycles: int | None = None              # the last call's
        self.call_offset = 0                        # the timers' own cycles, found by timing an RTS
        self._wrote_registers = False               # since VICE last ran (see _settle)
        self._stopped = threading.Event()
        self._stop = threading.Event()
        self._running = False
        # on the simulated C64 (emu.sim) rather than VICE: cycles come from it, exactly, and time is its own
        self.simulated = getattr(monitor, "simulator", False)

    # ------------------------------------------------------------------ the worker's side
    def vice_event(self, rtype: int, body: bytes):
        from .emu.binmon import EVT_STOPPED
        if rtype in (EVT_STOPPED, -1):
            self._stopped.set()

    def stop_soon(self):
        self._stop.set()
        self._stopped.set()

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.ok is True)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.ok is False)

    def run(self) -> str:
        from .emu.binmon import MonitorError
        try:
            self._ready()
            self._load()
            self._calibrate()
            for c in self.commands:
                if self._stop.is_set():
                    return "Stopped"
                try:
                    self._do(c)
                except Stop as e:
                    if str(e):
                        self._say(c, None, str(e))
                    break
                except (ValueError_, TranscriptError) as e:
                    self._say(c, False, str(e))
                    break
        except (MonitorError, OSError, ConnectionError) as e:
            if self.simulated:
                return f"The simulator stopped: {e}"
            return "VICE was closed" if not self.monitor.connected else f"VICE stopped answering: {e}"
        except TranscriptError as e:
            return str(e)
        return ""

    def _say(self, c: Command, ok: bool | None, message: str):
        o = Outcome(c.line, c.text, ok, message)
        self.outcomes.append(o)
        self.on_outcome(o)

    # ------------------------------------------------------------------ the machine
    def _stop_vice(self):
        """Stop VICE if it's running (a command stops it, at the end of a frame)."""
        if self._running:
            self._stopped.clear()
            self.monitor.ping()
            self._stopped.wait(1)
            self._running = False

    def _resume(self):
        self._stopped.clear()
        self.monitor.resume()
        self._running = True
        self._wrote_registers = False

    def _regs(self) -> dict[str, int]:
        self._stop_vice()
        return self.monitor.get_registers()

    def _set_register(self, name: str, value: int):
        self._stop_vice()
        self.monitor.set_register(name, value)
        self._wrote_registers = True            # (the next instruction would run twice: see _settle)

    def _land(self, pc: int):
        """Make the PC pc, with its instruction to run once (emu.regs)."""
        from .emu.regs import land

        def run():
            self._resume()
            if not self._stopped.wait(self.timeout):
                self._stop_vice()
                raise TranscriptError(f"Couldn't get the PC to ${pc:04X}")
            self._running = False
        self._stop_vice()
        land(self.monitor, pc, run)
        self._wrote_registers = False

    def _settle(self):
        """Before the program goes on: registers written since it stopped would make VICE run the
        instruction at the PC twice, so land on it first."""
        if self._wrote_registers:
            self._land(self._regs()["PC"])

    def _step(self, count: int, over: bool):
        m = self.monitor
        self._settle()
        self._stop_vice()
        self._stopped.clear()
        m.step(count, over=over)
        self._stopped.wait(self.timeout)

    def _ready(self):
        """Wait for BASIC's READY (VICE has just started). The simulator boots there, if it has the ROMs."""
        if self.simulated:
            self.monitor.machine.boot()
            return
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not self._stop.is_set():
            self._resume()
            time.sleep(0.25)
            if self._regs()["PC"] in READY_LOOP:
                return
        raise TranscriptError("The C64 didn't get to READY in VICE")

    def _load(self):
        """The program into memory, as LOAD puts it there (BASIC's pointers too, at $0801)."""
        p = self.program
        if len(p) < 3:
            raise TranscriptError("The program is empty")
        start = p[0] | p[1] << 8
        end = start + len(p) - 2
        self.monitor.write_memory(start, p[2:])
        self.load_address = start
        if start == 0x0801:                           # VARTAB, ARYTAB and STREND: the end of the program
            ptr = bytes([end & 0xFF, end >> 8])
            self.monitor.write_memory(0x002D, ptr * 3)
        for address, data in self.overlays:          # the project's memory before debugging
            self.monitor.write_memory(address, data, side_effects=0xD000 <= address <= 0xDFFF)

    def _calibrate(self):
        """How many cycles the timers add to a call: time an RTS (6 cycles) in the KERNAL."""
        m = self.monitor
        if self.simulated:
            self.call_offset = 0                     # (its count is exact)
            return
        kernal = m.read_memory(0xE000, 0xFFFF)
        rts = 0xE000 + kernal.index(0x60)
        self.cycles = None
        fl = m.get_registers()["FL"]
        self._set_register("FL", fl | 0x04)          # (no interrupt in the middle of it)
        self._call(rts)
        self._set_register("FL", fl)
        self.call_offset = self.cycles - 6
        self.cycles = None

    def _until(self, address: int, sp: int | None = None, what: str = "", failure: str = ""):
        """Run until the PC reaches the address (with this stack pointer, if given). ``failure``: the
        message if it isn't reached in time."""
        m = self.monitor
        self._settle()
        cid = m.add_checkpoint(address).id
        try:
            deadline = time.monotonic() + self.timeout
            self._resume()
            while True:
                left = deadline - time.monotonic()
                if left <= 0 or not self._stopped.wait(left):
                    self._stop_vice()
                    raise TranscriptError((failure or f"{what or f'${address:04X}'} wasn't reached") +
                                          f" in {self.timeout:g} s")
                if self._stop.is_set():
                    raise Stop("")
                self._running = False
                r = m.get_registers()
                if r["PC"] == address and (sp is None or r["SP"] == sp):
                    return r
                why = getattr(m, "last_stop", "")
                if why in ("brk", "jam"):                # the simulator stops at those (VICE goes on)
                    what_ = "a BRK" if why == "brk" else "an instruction the 6510 hasn't got"
                    raise TranscriptError(f"The simulator stopped at {what_}, at ${r['PC']:04X}")
                self._resume()                       # (there, but deeper: a recursive call, say)
        finally:
            self._stop_vice()
            m.delete_checkpoint(cid)

    def _call(self, address: int, name: str = ""):
        """JSR to the routine, run it until it returns, and count its cycles (CIA 2's timers, as a
        32-bit count of cycles, for the length of the call). The PC is put back afterwards."""
        m = self.monitor
        regs = self._regs()
        pc, sp = regs["PC"], regs["SP"]
        m.write_memory(0x0100 + ((sp - 1) & 0xFF), bytes([(TRAP - 1) & 0xFF, ((TRAP - 1) >> 8) & 0xFF]))
        self._set_register("SP", (sp - 2) & 0xFF)
        self._land(address)
        failure = f"The call to {name or f'${address:04X}'} didn't return"
        if self.simulated:
            start = m.cycles
            try:
                self._until(TRAP, sp, failure=failure)
                self.cycles = m.cycles - start
            finally:
                self._set_register("PC", pc)
            return
        # the counter last, once the registers are set (VICE's step after a register write takes time)
        counter = CycleCounter(m)
        start = counter.start()
        try:
            self._until(TRAP, sp, failure=failure)
            self.cycles = (start - counter.read()) - self.call_offset
        finally:
            counter.stop()
            self._set_register("PC", pc)

    # ------------------------------------------------------------------ the commands
    def _address(self, text: str) -> int:
        v = parse_number(text, self.symbols)
        if not 0 <= v <= 0xFFFF:
            raise TranscriptError(f"{text} is outside $0000-$FFFF")
        return v

    def _do(self, c: Command):  # noqa: C901 (a command each)
        m, verb, args = self.monitor, c.verb, c.args
        if verb in REGISTERS:
            value = parse_number(args.lstrip("=").strip(), self.symbols)
            self._set_register(REGISTERS[verb], value)
            self._say(c, None, f"{REGISTERS[verb].replace('FL', 'P')} = ${value:0{4 if verb == 'pc' else 2}X}")
        elif verb == "set":
            where, _, data = args.partition(" ")
            address, values = self._address(where), parse_bytes(data, self.symbols)
            self._stop_vice()
            m.write_memory(address, values, side_effects=0xD000 <= address <= 0xDFFF)
            self._say(c, None, f"${address:04X}: {values.hex(' ')}")
        elif verb == "fill":
            parts = args.split()
            if len(parts) != 3:
                raise TranscriptError("fill <address> <count> <byte>")
            address, count, byte = self._address(parts[0]), parse_number(parts[1]), parse_number(parts[2])
            self._stop_vice()
            m.write_memory(address, bytes([byte & 0xFF]) * count)
            self._say(c, None, f"${address:04X}-${address + count - 1:04X} filled with ${byte & 0xFF:02X}")
        elif verb == "call":
            address = self._address(args)
            self._call(address, args)
            r = self._regs()
            self._say(c, None, f"returned after {self.cycles:,} cycles: A=${r['A']:02X} X=${r['X']:02X} "
                               f"Y=${r['Y']:02X} {flags_text(r['FL'])}")
        elif verb == "run":
            m2 = re.fullmatch(r"(?:until\s+(.+))?", args, re.I)
            if m2 is None:
                raise TranscriptError("run, or run until <address>")
            if self._regs()["PC"] not in READY_LOOP:
                raise TranscriptError("run starts the program from READY, so it can only be the first thing run")
            if self.load_address != 0x0801:
                raise TranscriptError(f"The program loads at ${self.load_address:04X}, not $0801: use call or goto "
                                      "with its start")
            m.write_memory(0x0277, bytes([0x52, 0x55, 0x4E, 0x0D]))    # RUN and Return, typed
            m.write_memory(0x00C6, bytes([4]))
            if m2.group(1):
                r = self._until(self._address(m2.group(1)), what=m2.group(1))
                self._say(c, None, f"stopped at ${r['PC']:04X}")
            else:
                self._settle()
                self._resume()
                self._say(c, None, "running")
        elif verb == "until":
            r = self._until(self._address(args), what=args)
            self._say(c, None, f"stopped at ${r['PC']:04X}")
        elif verb == "goto":
            address = self._address(args)
            self._land(address)
            self._say(c, None, f"PC = ${address:04X}")
        elif verb == "wait":
            try:
                seconds = float(args.removesuffix("s"))
            except ValueError:
                raise TranscriptError("wait <seconds>, such as wait 0.5") from None
            self._settle()
            if self.simulated:                       # the C64's own time: a PAL second of cycles
                self._stop_vice()
                m.machine.run(int(seconds * PAL_HZ))
            else:
                self._resume()
                time.sleep(seconds)
            r = self._regs()
            self._say(c, None, f"ran {seconds:g} s; stopped at ${r['PC']:04X}")
        elif verb == "type":
            keys = keys_of(args)
            self._settle()
            for i in range(0, len(keys), KEYBUF_SIZE):
                self._keys_read(f"the keys before {args}")
                chunk = keys[i:i + KEYBUF_SIZE]
                self._stop_vice()
                m.write_memory(KEYBUF, chunk)
                m.write_memory(KEYCOUNT, bytes([len(chunk)]))
            self._keys_read(args)
            self._say(c, None, f"typed {len(keys)} key{'s' if len(keys) != 1 else ''}")
        elif verb == "joystick":
            self._joystick(args)
            self._say(c, None, f"joystick {args}")
        elif verb in ("hold", "release"):
            held = self._keys(verb, args)
            self._say(c, None, f"keys held: {', '.join(held)}" if held else "no keys held")
        elif verb == "restore":
            path = self._snapshot(args)
            from .snapshot import is_simulator_snapshot
            if not self.simulated and is_simulator_snapshot(path):
                raise TranscriptError(f"{path.name} was taken on the simulator: run the transcript without VICE")
            self._stop_vice()
            pc = m.undump(str(path))
            self._wrote_registers = False
            self._say(c, None, f"restored {path.name}: PC = ${pc:04X}")
        elif verb in ("step", "stepover"):
            n = parse_number(args) if args else 1
            self._step(n, verb == "stepover")
            r = m.get_registers()
            self._say(c, None, f"PC = ${r['PC']:04X}")
        elif verb == "interrupts":
            on = args.lower() in ("on", "1", "yes")
            if args.lower() not in ("on", "off", "1", "0", "yes", "no"):
                raise TranscriptError("interrupts on, or interrupts off")
            fl = self._regs()["FL"]
            self._set_register("FL", (fl & ~0x04) if on else (fl | 0x04))
            self._say(c, None, "interrupts on (I flag clear)" if on else "interrupts off (I flag set)")
        elif verb == "clearregs":
            for r in ("A", "X", "Y"):
                self._set_register(r, 0)
            self._set_register("FL", 0x20)
            self._say(c, None, "A, X, Y and the flags cleared")
        elif verb == "resetstack":
            self._set_register("SP", 0xFF)
            self._say(c, None, "SP = $FF")
        elif verb == "timeout":
            self.timeout = float(args.removesuffix("s"))
            self._say(c, None, f"calls and runs time out after {self.timeout:g} s")
        elif verb == "skipkernal":
            if self.simulated:
                on = args.lower() not in ("off", "0", "no")
                self._stop_vice()
                m.machine.skip_kernal = on
                self._say(c, None, "KERNAL calls are stepped over" if on else "KERNAL calls run")
            else:
                self._say(c, None, "(not needed: VICE has the real KERNAL)")
        elif verb in ("show", "watch"):
            self._say(c, None, self._show(args))
        elif verb == "check":
            ok, message = self._check(args)
            self._say(c, ok, message)
        elif verb == "end":
            raise Stop("")
        elif verb == "break":
            raise Stop("break: the transcript stops here")

    def _simulator(self, what: str):
        if not self.simulated:
            raise TranscriptError(f"{what} needs the simulator (Run Transcript Without VICE, or l64test "
                                  "--simulate): VICE's monitor can't hold a key down or move a joystick")
        self._stop_vice()
        return self.monitor.machine.memory

    def _joystick(self, args: str):
        """joystick <port> <up|down|left|right|fire ...|none>: what's pressed from now on."""
        from .emu.sim import JOY_BITS
        words = args.lower().split()
        if not words or words[0] not in ("1", "2"):
            raise TranscriptError("joystick 1 or 2, then up, down, left, right, fire, or none")
        bits = 0
        for w in words[1:]:
            if w == "none":
                continue
            if w not in JOY_BITS:
                raise TranscriptError(f"{w}? A joystick's up, down, left, right or fire (or none)")
            bits |= JOY_BITS[w]
        self._simulator("joystick").joysticks[int(words[0])] = bits

    def _keys(self, verb: str, args: str) -> list[str]:
        """hold <keys>: held down from now on (a C64 key's name each: a, space, return, f1, shift...);
        release <keys>, or release on its own for all of them."""
        from .emu.sim import KEYS, MonitorError, key_named
        mem = self._simulator(verb)
        names = args.split()
        try:
            keys = [key_named(n) for n in names]
        except MonitorError as e:
            raise TranscriptError(str(e)) from None
        if verb == "hold":
            if not keys:
                raise TranscriptError("hold which keys? (a, space, return, f1, shift...)")
            mem.held |= set(keys)
        elif keys:
            mem.held -= set(keys)
        else:
            mem.held.clear()
        by_key = {v: k for k, v in KEYS.items()}
        return sorted(by_key[k] for k in mem.held)

    def _snapshot(self, args: str):
        """A snapshot named in a restore: a .vsf's path, or a name in the project's snapshots folder."""
        from pathlib import Path
        name = args.strip().strip('"')
        if not name:
            raise TranscriptError("restore <snapshot>: its file, or its name in the project's snapshots folder")
        folder = Path(self.folder) if self.folder else Path.cwd()
        tries = [Path(name).expanduser(), folder / name, folder / "snapshots" / name,
                 folder / "snapshots" / f"{name}.vsf", folder / f"{name}.vsf"]
        for p in tries:
            if p.is_file():
                return p
        raise TranscriptError(f"There's no snapshot {name} (looked in {folder} and its snapshots folder)")

    def _keys_read(self, what: str):
        """Let the program run until it has read every key in the keyboard buffer."""
        deadline = time.monotonic() + self.timeout
        while True:
            self._stop_vice()
            if self.monitor.read_memory(KEYCOUNT, KEYCOUNT)[0] == 0:
                return
            if time.monotonic() > deadline:
                raise TranscriptError(f"The program didn't read {what} in {self.timeout:g} s (is it waiting "
                                      "for a key, with INPUT or GET?)")
            self._resume()
            time.sleep(0.05)

    def _value_of(self, subject: str) -> tuple[str, int | bytes]:
        """What a check or show looks at: a register, a flag, cycles, word <address>, or memory."""
        s = subject.strip()
        low = s.lower()
        if low in REGISTERS:
            name = REGISTERS[low]
            return name.replace("FL", "P"), self._regs()[name]
        if low in FLAGS:
            return f"flag {low.upper()}", (self._regs()["FL"] >> FLAGS[low]) & 1
        if low == "cycles":
            if self.cycles is None:
                raise TranscriptError("check cycles comes after a call")
            return "cycles", self.cycles
        if low.startswith("word "):
            address = self._address(s[5:])
            self._stop_vice()
            b = self.monitor.read_memory(address, address + 1)
            return f"the word at ${address:04X}", b[0] | b[1] << 8
        address = self._address(s)
        return f"${address:04X}", address

    def _check(self, args: str) -> tuple[bool, str]:
        m = re.match(r"(.+?)\s*(==|<>|!=|<=|>=|=|<|>)\s*(.+)$", args)
        if not m:
            raise TranscriptError("check <register, flag, cycles, word <address> or address> <op> <value>")
        subject, op, expected = m.groups()
        mask = None
        if "&" in subject:                            # check $d021 & $0f = 0: some of the bits
            subject, _, mask_text = subject.partition("&")
            mask = parse_number(mask_text, self.symbols)
        label, value = self._value_of(subject)
        low = subject.strip().lower()
        if mask is not None:
            if not (low in REGISTERS or low.startswith("word ")):
                self._stop_vice()
                value = self.monitor.read_memory(value, value)[0]
            want = parse_number(expected, self.symbols)
            got = value & mask
            ok = OPS[op](got, want)
            text = f"{label} and ${mask:02X} is ${got:02X}"
            return ok, text if ok else f"{text}, not {op} {expected.strip()}"
        if low in REGISTERS or low in FLAGS or low == "cycles" or low.startswith("word "):
            want = parse_number(expected, self.symbols)
            ok = OPS[op](value, want)
            shown = f"{value:,}" if low == "cycles" else f"${value:0{4 if low in ('pc',) or low.startswith('word ') else 2}X}"
            return ok, (f"{label} is {shown}" if ok else f"{label} is {shown}, not {op} {expected.strip()}")
        # memory: one byte, or a run of bytes (= and <> only)
        want_bytes = parse_bytes(expected, self.symbols)
        self._stop_vice()
        got = self.monitor.read_memory(value, value + len(want_bytes) - 1)
        if len(want_bytes) == 1:
            ok = OPS[op](got[0], want_bytes[0])
            text = f"{label} is ${got[0]:02X}"
            if not ok and 0xD020 <= value <= 0xD02E and got[0] & 0xF0 == 0xF0:
                text += f" (a colour register's top 4 bits read as 1: check {subject.strip()} & $0f)"
            return ok, text if ok else f"{text}, not {op} {expected.strip()}"
        if op not in ("=", "==", "<>", "!="):
            raise TranscriptError("Several bytes can only be checked with = or <>")
        ok = OPS[op](bytes(got), want_bytes)
        return ok, (f"{label}: {bytes(got).hex(' ')}" if ok else
                    f"{label}: {bytes(got).hex(' ')}, not {op} {want_bytes.hex(' ')}")

    def _show(self, args: str) -> str:
        parts = args.split()
        if not parts:
            r = self._regs()
            return (f"PC=${r['PC']:04X} A=${r['A']:02X} X=${r['X']:02X} Y=${r['Y']:02X} SP=${r['SP']:02X} "
                    f"{flags_text(r['FL'])}")
        count = parse_number(parts[1]) if len(parts) > 1 else 1
        label, value = self._value_of(parts[0])
        if isinstance(value, int) and parts[0].lower() not in REGISTERS and parts[0].lower() not in FLAGS \
                and parts[0].lower() != "cycles" and not parts[0].lower().startswith("word"):
            self._stop_vice()
            b = self.monitor.read_memory(value, value + max(1, count) - 1)
            return f"{label}: {bytes(b).hex(' ')}"
        return f"{label} = {value:,}" if parts[0].lower() == "cycles" else f"{label} = ${value:02X}"


TEMPLATE = """; {name}: a transcript. Run it with Debugger > Run Transcript: VICE starts, the program is
; loaded (not run), and each line below runs in turn. Failed checks show in Build Output.
;
;   run until <label>        start the program (as RUN would) and stop when it gets there
;   call <label>             call a routine (JSR) and run it until it returns
;   a $20  x 0  y #10        set a register (bare numbers are hex; #10 is decimal)
;   set <address> <bytes>    put bytes in memory ("text" as screen codes, 'text' as PETSCII)
;   check a = $20            check a register, flag (c, z, n, v), cycles (the last call's),
;   check <address> = <bytes>    memory, or word <address>; & masks bits: check $d020 & $0f = 0
;   show <address> [count]   show memory (or a register) in the results
;   type "50{{return}}"       type keys for the program to read (INPUT, GET): then wait for its answer
;   joystick 2 right fire    hold space    release      (on the simulator: Run Transcript Without VICE)
;   restore <snapshot>       start from a snapshot in the project's snapshots folder
;   wait <seconds>  step [n]  until <label>  goto <label>  interrupts on|off  timeout <seconds>

run until start
"""


def keys_of(args: str) -> bytes:
    """The keys of a type command: "text" in listing notation, letters unshifted and capitals shifted
    (as in a BASIC listing's strings), with {codes}: {return}, {clear}, {down}, {f1}, {$0d}..."""
    from .basic.petscii import ControlCodeError, char_to_petscii, parse_control
    m = re.fullmatch(r'"(.*)"', args.strip())
    if not m:
        raise TranscriptError('type "text", with {return} for Return: type "50{return}"')
    out = bytearray()
    text = m.group(1)
    i = 0
    try:
        while i < len(text):
            if text[i] == "{":
                end = text.find("}", i)
                if end < 0:
                    raise TranscriptError("A { without its }")
                out += bytes(parse_control(text[i + 1:end]))
                i = end + 1
            else:
                out.append(char_to_petscii(text[i], True))
                i += 1
    except ControlCodeError as e:
        raise TranscriptError(str(e)) from None
    if not out:
        raise TranscriptError("Nothing to type")
    return bytes(out)


def disk_args(res) -> list[str]:
    """VICE's options to put the build's disk image in drive 8, if it wrote one, so the program can
    load files from it."""
    return ["-8", str(res.disk)] if getattr(res, "disk", None) else []


def sim_machine(res):
    """A simulated C64 (emu.sim) with the build's disk image in drive 8, if it wrote one (a copy:
    what the program writes to it stays in the simulator)."""
    from .emu.sim import Machine
    m = Machine()
    if getattr(res, "disk", None):
        m.attach_disk(res.disk)
    return m


def summary(runner: Runner, message: str = "") -> str:
    p, f = runner.passed, runner.failed
    text = f"{p} check{'s' if p != 1 else ''} passed, {f} failed"
    return text + (f". {message}" if message else "")


def main(argv: list[str] | None = None) -> int:
    """l64test: build a project and run transcripts in VICE. The exit status is the number of
    failed checks (capped at 100), 101 if a transcript couldn't run."""
    import argparse
    from pathlib import Path

    from .profiler import ViceRun, resolver_for
    from .project.build import build_all, build_project
    from .project.model import load_project
    from .settings import Settings
    ap = argparse.ArgumentParser(prog="l64test", description="Run transcripts against a project's program in VICE")
    ap.add_argument("project", help="the project (.l64proj, .cbmprj, .code-workspace) or source file")
    ap.add_argument("transcripts", nargs="+", help=".transcript files")
    ap.add_argument("--vice-args", default="", help="extra options for x64sc (e.g. -sounddev dummy)")
    ap.add_argument("--simulate", action="store_true",
                    help="run them on the simulated C64 (a 6510 with the ROMs, the CIAs and much of the VIC-II, "
                         "no SID), not VICE")
    args = ap.parse_args(argv)
    st = Settings.load()
    project = load_project(Path(args.project))
    if project.programs:                          # several programs: all of them, for the disk image
        res, _each = build_all(project, kickass_jar=st.kickass_jar, java=st.java, goattracker_dir=st.goattracker_dir)
    else:
        res = build_project(project, kickass_jar=st.kickass_jar, java=st.java, goattracker_dir=st.goattracker_dir)
    if not res.ok:
        print(res.log)
        return 101
    resolver = resolver_for(res)
    from .overlays import OverlayError, load_all
    try:
        memory = load_all(project.directory, project.debug_memory)
    except OverlayError as e:
        print(f"Memory before debugging: {e}")
        return 101
    failed = 0
    for t in args.transcripts:
        try:
            commands = parse(Path(t).read_text())
        except (OSError, TranscriptError) as e:
            print(f"{t}: {e}")
            return 101
        done: list[str] = []
        mark = {True: "pass", False: "FAIL", None: "    "}
        def worker(m, commands=commands, t=t, mark=mark):
            return Runner(m, commands, res.prg.read_bytes(), resolver.symbol_table(),
                          lambda o: print(f"{t}:{o.line}: {mark[o.ok]} {o.text}: {o.message}"), overlays=memory,
                          folder=project.directory)
        if args.simulate:
            from .emu.sim import SimRun
            run = SimRun(worker, done.append, sim_machine(res))
        else:
            run = ViceRun(None, worker, done.append, st.emulator, args.vice_args.split() + disk_args(res))
        run.start()
        while not done:
            time.sleep(0.1)
        run.quit()
        print(f"{t}: {summary(run.worker, done[0])}")
        if done[0]:
            return 101
        failed += run.worker.failed
    return min(failed, 100)


if __name__ == "__main__":
    raise SystemExit(main())
