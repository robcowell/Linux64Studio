import os
import shutil
import time
from pathlib import Path

import pytest

from l64s.routine_timing import CPU_IRQ, JSR, KERNAL_IRQ, Call, Timing, loops_to_entry, return_point

EXAMPLES = Path(__file__).parent.parent / "examples"


def _stack(sp: int, values: list[int]) -> bytes:
    s = bytearray(256)
    for i, v in enumerate(values):
        s[(sp + 1 + i) & 0xFF] = v
    return bytes(s)


def test_a_jsrs_return():
    mem = {0x0900: 0x20, 0x0901: 0x00, 0x0902: 0x10}          # $0900 jsr $1000; returns to $0903
    stack = _stack(0xF0, [0x02, 0x09])                          # the JSR pushed $0902
    assert return_point(0x1000, 0xF0, stack, {}, lambda a: mem.get(a, 0)) == (JSR, 0x0903, 0xF2)


def test_an_interrupt_handlers_return():
    # through the KERNAL ($0314): Y, X, A, then P and the interrupted PC $0A40
    stack = _stack(0xE0, [1, 2, 3, 0x20, 0x40, 0x0A])
    assert return_point(0xC000, 0xE0, stack, {0x0314: 0xC000}, lambda a: 0) == (KERNAL_IRQ, 0x0A40, 0xE6)
    # straight from the CPU ($FFFE, the KERNAL switched out): P, then the PC
    stack = _stack(0xE0, [0x20, 0x40, 0x0A])
    assert return_point(0xC000, 0xE0, stack, {0xFFFE: 0xC000}, lambda a: 0) == (CPU_IRQ, 0x0A40, 0xE3)


def test_a_routine_reached_some_other_way():
    stack = _stack(0xF0, [0x02, 0x09])
    assert return_point(0x1000, 0xF0, stack, {}, lambda a: 0xEA) is None      # no JSR before the "return"


def test_a_routine_that_loops_to_its_first_instruction():
    # wait: lda flag / beq wait / lda #0 / sta flag / rts
    assert loops_to_entry(bytes.fromhex("ad3760f0fba9008d376060"), 0x4077)
    # lda flag / bne done / jmp start / done: rts (jmp back to the start)
    assert loops_to_entry(bytes.fromhex("ad3760d0034c0010" + "60"), 0x1000)
    # a loop inside it, not to its start: ldx #8 / loop: dex / bne loop / rts
    assert not loops_to_entry(bytes.fromhex("a208cad0fd60"), 0x1000)


def test_the_figures():
    t = Timing()
    for cycles, start in ((100, 10), (300, 12), (200, 50)):
        t.calls.append(Call(cycles, start, start + 3))
    t.counted, t.seconds = 150, 1.0
    st = t.stats()
    assert (st["min"], st["max"], st["mean"], st["median"]) == (100, 300, 200, 200)
    assert t.lines() == (10, 50, 13, 53)
    assert t.per_frame() == pytest.approx(150 / 50.125, rel=1e-3)
    h = t.histogram(4)
    assert sum(n for _a, _b, n in h) == 3 and h[0][0] == 100 and h[-1][1] >= 300
    assert "Fewest cycles: 100" in t.report("move") and "Calls a frame: 2.99" in t.report("move")
    assert Timing().stats() is None and Timing().per_frame() is None


def _vice_ok():
    return os.environ.get("L64S_VICE_TESTS") == "1" and shutil.which("x64sc") and shutil.which("cl65")


@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE and cc65) to run VICE")
def test_timing_glowcaves_routines_in_vice(tmp_path):
    from l64s.profiler import ViceRun
    from l64s.project.build import build_project
    from l64s.project.model import load_project
    from l64s.routine_timing import Timer
    shutil.copytree(EXAMPLES / "glowcave", tmp_path / "gc", ignore=shutil.ignore_patterns("build"))
    p = load_project(tmp_path / "gc" / "glowcave.l64proj")
    res = build_project(p)
    labels = res.c_debug.labels

    def measure(name):
        run = ViceRun(res.run_target(p), lambda m: Timer(m, labels[name][0], lambda t: None), lambda m: None,
                      extra_args=["-sounddev", "dummy"])
        run.start()
        time.sleep(8)
        run.stop()
        time.sleep(1.5)
        timing = run.worker.timing
        run.quit()
        return timing

    raster = measure("_raster")              # the raster interrupt's handler: twice a frame
    assert raster.how == JSR and len(raster.calls) > 100
    assert raster.per_frame() == pytest.approx(2.0, abs=0.1)
    starts = [c.start_line for c in raster.calls if c.cycles > 30]
    assert all(ln < 12 or 64 <= ln < 76 for ln in starts), starts
    top = sum(1 for ln in starts if ln < 12)                # the calls measured are a fair share of both
    assert 0.3 < top / len(starts) < 0.7, top / len(starts)
    wait = measure("_wait_frame")            # loops to its start; once a frame, waiting most of it (the title)
    assert wait.per_frame() == pytest.approx(1.0, abs=0.1)
    assert wait.stats()["max"] > 15000 and all(c.cycles < wait.frame_cycles for c in wait.calls)
