import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from l64s import profiler as P
from l64s.emu.binmon import EVT_STOPPED
from l64s.emu.clines import LineSpan, LineTable

EXAMPLES = Path(__file__).parent.parent / "examples"
HAVE_CC65 = shutil.which("cl65") is not None


def _memory(code: dict[int, bytes]) -> bytes:
    m = bytearray(0x10000)
    for a, b in code.items():
        m[a:a + len(b)] = b
    return bytes(m)


# ---------------------------------------------------------------------------- naming where the PC is

def test_routine_is_the_label_before_the_pc_but_not_a_local_one():
    r = P.Resolver({0x1000: "start", 0x1010: "@loop", 0x1020: "!next", 0x1030: "update"},
                   {0x1000: ("/p/main.asm", 5), 0x1030: ("/p/main.asm", 20)})
    assert r.routine(0x1000).name == "start"
    assert r.routine(0x1015).name == "start"          # @loop and !next are inside start
    assert r.routine(0x1025).name == "start"
    u = r.routine(0x1031)
    assert (u.name, u.address, u.where, u.module) == ("update", 0x1030, "/p/main.asm", "main.asm")


def test_kernal_and_basic_rom_routines():
    r = P.Resolver({0x0810: "start"}, {0x0810: ("/p/a.asm", 1)})
    assert r.routine(0xEA31).name == "KERNAL IRQ handler"
    assert r.routine(0xEA35).name == "KERNAL IRQ handler"
    assert r.routine(0xEA90).name == "KERNAL SCNKEY keyboard scan"
    assert r.routine(0xFF48).module == "KERNAL"
    assert r.routine(0xA7E4).name == "BASIC ROM"


def test_program_code_under_the_roms_is_the_programs():
    # code at $E000 (the KERNAL banked out) with lines of the program's: its labels, not the KERNAL's
    r = P.Resolver({0xE000: "irq"}, {0xE000: ("/p/a.asm", 3), 0xE002: ("/p/a.asm", 4)})
    assert r.routine(0xE002).name == "irq"


def test_a_line_spanning_several_instructions():
    r = P.Resolver({}, {0x2000: ("/p/a.asm", 7), 0x2009: ("/p/a.asm", 8)})
    assert r.line(0x2000) == ("/p/a.asm", 7)
    assert r.line(0x2005) == ("/p/a.asm", 7)          # (a macro's line)
    assert r.line(0x2009) == ("/p/a.asm", 8)
    t = P.Resolver({}, {}, [LineTable([LineSpan(0x3000, 0x3010, "/p/m.c", 12)])])
    assert t.line(0x300F) == ("/p/m.c", 12) and t.line(0x3010) is None


def test_c_functions_by_their_ranges_static_ones_too():
    mods = [(0x4000, 0x4200, "main.c"), (0x4200, 0x4300, "music.s")]
    funcs = [(0x4000, 0x4040, "_raster"), (0x4077, 0x4082, "_wait_frame")]
    r = P.Resolver({0x4000: "_raster", 0x4200: "_music_init", 0x4250: "channels", 0x5000: "popax"},
                   {0x4000: ("/p/main.c", 60), 0x4077: ("/p/main.c", 95)}, c=True, functions=funcs,
                   modules=mods, outside="c64.lib")
    w = r.routine(0x407A)                       # not in the labels file (static), but in a function's range
    assert (w.name, w.address, w.module) == ("wait_frame()", 0x4077, "main.c")
    assert r.routine(0x4201).name == "music_init()"
    assert r.routine(0x5003).name == "popax" and r.routine(0x5003).module == "c64.lib"
    # past music.s's end, with no label of its own: not music.s's "channels"
    assert r.routine(0x4310).name == "c64.lib"
    assert r.in_program(0x407A) and not r.in_program(0xEA31)


# ---------------------------------------------------------------------------- adding the samples up

def _profile():
    # $1000 nop (2 cycles) in start; $1100 jsr (6 cycles) in update; $EA31 in the KERNAL
    mem = _memory({0x1000: b"\xea", 0x1100: b"\x20\x00\x10", 0xEA31: b"\xea"})
    r = P.Resolver({0x1000: "start", 0x1100: "update"}, {0x1000: ("/p/a.asm", 3), 0x1100: ("/p/b.asm", 9)})
    return P.Profile(r, mem)


def test_shares_are_of_cycles_not_of_samples():
    p = _profile()
    for _ in range(3):
        p.add(0x1000, 10)                        # 3 samples x 2 cycles
    p.add(0x1100, 100)                           # 1 sample x 6 cycles
    rows = p.routines()
    assert [(r.name, r.samples) for r in rows] == [("start", 3), ("update", 1)]
    assert rows[0].share == pytest.approx(0.5) and rows[1].share == pytest.approx(0.5)
    assert (rows[1].file, rows[1].line, rows[1].module) == ("/p/b.asm", 9, "b.asm")


def test_lines_files_and_the_frame():
    p = _profile()
    p.add(0x1000, 10)
    p.add(0x1100, 10)
    p.add(0xEA31, 0)
    assert [(r.name, r.line) for r in p.lines()] == [("b.asm:9", 9), ("a.asm:3", 3)]   # the KERNAL has no line
    assert {r.name for r in p.files()} == {"a.asm", "b.asm", "KERNAL"}
    frame = p.raster_lines()
    assert len(frame) == 312 and frame[5] == []
    assert {r.name: round(s, 2) for r, s in frame[10]} == {"update": 0.75, "start": 0.25}
    assert "update" in p.report(2.0) and "b.asm:9" in p.report()
    p.clear()
    assert p.samples == 0 and p.routines() == [] and p.raster_lines()[10] == []


# ---------------------------------------------------------------------------- sampling

class FakeVice:
    """A binary monitor whose program runs one instruction per address: after stepping n, the PC
    has moved on n bytes, and the raster on 4n cycles."""

    def __init__(self, start_pc=0xE5CD, program_at=None):
        self.pc, self.cycles = start_pc, 0
        self.program_at = program_at            # where the PC jumps once "started"
        self.connected = True
        self.on_event = None
        self.steps = 0
        self.resumed = False

    def step(self, n, over=False):
        self.steps += 1
        if self.program_at and self.steps == 3:
            self.pc = self.program_at
        else:
            self.pc = (self.pc + n) & 0xFFFF if self.pc >= 0xE000 else 0x1000 + (self.pc - 0x1000 + n) % 0x100
        self.cycles += 4 * n
        threading.Thread(target=self.on_event, args=(EVT_STOPPED, b"")).start()

    def get_registers(self):
        pos = self.cycles % (63 * 312)
        return {"PC": self.pc, "LIN": pos // 63, "CYC": pos % 63}

    def read_memory(self, a, b):
        m = bytearray(0x10000)
        m[0x02A6] = 1                           # PAL
        return bytes(m[a:b + 1])

    def resume(self):
        self.resumed = True


def test_sampler_waits_for_the_program_then_samples_it():
    vice = FakeVice(program_at=0x1000)
    got, started = [], []
    s = P.Sampler(vice, lambda samples, cyc: got.append((list(samples), cyc)),
                  is_program=lambda pc: 0x1000 <= pc < 0x1100,
                  on_start=lambda mem, timing: started.append(timing), batch=50, real_time=False)
    vice.on_event = s.vice_event
    s.start()
    deadline = time.monotonic() + 10
    while sum(len(b) for b, _c in got) < 200 and time.monotonic() < deadline:
        time.sleep(0.01)
    s.stop()
    assert started == [P.PAL]
    samples = [pc for b, _c in got for pc, _line in b]
    assert len(samples) >= 200 and all(0x1000 <= pc < 0x1100 for pc in samples)    # none from before it started
    assert all(0 <= line < 312 for b, _c in got for _pc, line in b)
    assert all(c > 0 for _b, c in got) and vice.resumed                # the emulated time; VICE goes on


def test_sampler_starts_anyway_for_a_program_it_cant_place():
    vice = FakeVice()
    started = []
    s = P.Sampler(vice, lambda *_: None, is_program=lambda pc: False, on_start=lambda m, t: started.append(t),
                  real_time=False, start_within=0.2)
    vice.on_event = s.vice_event
    s.start()
    deadline = time.monotonic() + 5
    while not started and time.monotonic() < deadline:
        time.sleep(0.01)
    s.stop()
    assert started == [P.PAL]


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_a_c_builds_resolver(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import load_project
    shutil.copytree(EXAMPLES / "glowcave", tmp_path / "gc", ignore=shutil.ignore_patterns("build"))
    res = build_project(load_project(tmp_path / "gc" / "glowcave.l64proj"))
    assert res.ok, res.log
    r = P.resolver_for(res)
    wait = res.c_debug.labels["_wait_frame"][0]
    assert r.routine(wait + 2).name == "wait_frame()"             # a static function
    assert r.routine(wait + 2).where.endswith("main.c")
    assert r.in_program(res.c_addresses["main"]) and not r.in_program(0xEA31)


def _vice_ok():
    return os.environ.get("L64S_VICE_TESTS") == "1" and shutil.which("x64sc") and HAVE_CC65


@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE and cc65) to run VICE")
def test_profiling_glowcave_in_vice(tmp_path):
    """Glowcave's attract mode, measured in VICE: the main loop waits for the frame most of the
    time, the raster interrupt runs at lines 0 and 64, and the game keeps its real speed."""
    from l64s.project.build import build_project
    from l64s.project.model import load_project
    shutil.copytree(EXAMPLES / "glowcave", tmp_path / "gc", ignore=shutil.ignore_patterns("build"))
    p = load_project(tmp_path / "gc" / "glowcave.l64proj")
    res = build_project(p)
    resolver = P.resolver_for(res)
    state = {"profile": None, "cycles": 0, "end": None}

    def start(mem, timing):
        state["profile"] = P.Profile(resolver, mem, timing[1])

    def batch(samples, cycles):
        for pc, line in samples:
            state["profile"].add(pc, line)
        state["cycles"] += cycles

    run = P.ProfileRun(res.run_target(p), resolver, start, batch, lambda m: state.update(end=m),
                       extra_args=["-sounddev", "dummy"])
    run.start()
    try:
        deadline = time.monotonic() + 40
        while (state["profile"] is None or state["profile"].samples < 6000) and time.monotonic() < deadline:
            time.sleep(0.2)
            assert state["end"] is None, state["end"]
        t0, c0 = time.monotonic(), state["cycles"]
        time.sleep(3)
        speed = (state["cycles"] - c0) / P.PAL[2] / (time.monotonic() - t0)
    finally:
        run.quit()
    prof = state["profile"]
    # (more than 5,000 stops: VICE's log, a line a stop, no longer fills a pipe and stops it dead)
    assert prof.samples >= 6000
    top = prof.routines()[0]
    assert top.name == "wait_frame()" and top.share > 0.4
    irq = [sum(s for r, s in prof.raster_lines()[ln] if r.name in ("clevel_irq", "raster()", "callirq_y"))
           for ln in range(312)]
    assert max(irq[0:8]) > 0.3 and max(irq[64:72]) > 0.3 and max(irq[150:250]) < 0.3
    assert 0.8 < speed < 1.2, speed


def test_line_shares_for_the_editor(tmp_path):
    f = tmp_path / "a.asm"
    f.write_text("")
    mem = _memory({0x1000: b"\xea", 0x1001: b"\xea"})
    r = P.Resolver({0x1000: "start"}, {0x1000: (str(f), 3), 0x1001: (str(f), 4)})
    p = P.Profile(r, mem)
    for pc in (0x1000, 0x1000, 0x1000, 0x1001):
        p.add(pc, 0)
    assert p.line_shares() == {str(f.resolve()): {3: (0.75, 3), 4: (0.25, 1)}}


def test_the_editors_figures_and_tints():
    pytest.importorskip("gi")
    from l64s.ui.profile_gutter import figure, heat_level
    assert figure(0.6624) == "66%" and figure(0.0144) == "1.4%" and figure(0.0004) == ""
    assert heat_level(0.66) == 0 and heat_level(0.05) == 1 and heat_level(0.015) == 2
    assert heat_level(0.004) == 3 and heat_level(0.001) is None
