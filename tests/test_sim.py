"""The simulated C64 (emu.sim): its memory, raster line, checkpoints and stepping, the KERNAL booting
on it, transcripts run on it, its screen, and its cycle counts against VICE's."""
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from l64s.emu import simscreen
from l64s.emu.binmon import EVT_STOPPED, OP_STORE, MonitorError
from l64s.emu.sim import FRAME, Machine, SimMonitor, Stopped, basic_sys, find_roms, parse_condition

ROMS = find_roms()
HAVE_ROMS = len(ROMS) == 3
needs_roms = pytest.mark.skipif(not HAVE_ROMS, reason="VICE's C64 ROMs aren't installed")
ROOT = Path(__file__).parent.parent


def ram_only(code: bytes, at: int = 0x1000) -> Machine:
    m = Machine(roms={})
    m.memory.write(at, code)
    m.cpu.pc = at
    return m


def test_without_roms_it_is_all_ram_and_skips_kernal_calls():
    m = ram_only(bytes([0x20, 0xD2, 0xFF, 0xA9, 0x05, 0x00]))     # jsr $ffd2 / lda #5 / brk
    assert m.skip_kernal
    s = m.run()
    assert s.why == "brk" and m.cpu.pc == 0x1005 and m.cpu.a == 5
    assert m.cycles == 12 + 2                                       # the JSR and RTS it would have taken


@needs_roms
def test_the_processor_port_banks_the_roms_in_and_out():
    m = Machine()
    mem = m.memory
    mem.ram[0xA000] = mem.ram[0xE000] = mem.ram[0xD000] = 0x42
    assert mem.peek(0xA000) == ROMS["basic"][0] and mem.peek(0xE000) == ROMS["kernal"][0]
    mem.poke(0xD020, 3)                                             # I/O, not the RAM beneath
    assert mem.io[0x20] == 3 and mem.ram[0xD020] == 0
    mem.poke(0xA000, 0x99)                                          # a write under a ROM goes to RAM
    assert mem.ram[0xA000] == 0x99 and mem.peek(0xA000) == ROMS["basic"][0]
    mem.poke(1, 0x36)                                               # BASIC out
    assert mem.peek(0xA000) == 0x99 and mem.peek(0xE000) == ROMS["kernal"][0]
    mem.poke(1, 0x33)                                               # the character ROM where I/O was
    assert mem.peek(0xD000) == ROMS["chargen"][0]
    mem.poke(1, 0x34)                                               # all RAM
    assert (mem.peek(0xA000), mem.peek(0xD000), mem.peek(0xE000)) == (0x99, 0x42, 0x42)


def test_the_raster_line_counts_as_on_a_pal_c64():
    m = ram_only(bytes([0xEA]))
    mem = m.memory
    mem.poke(1, 0x37)
    m.cpu.processorCycles = 63 * 100 + 5
    assert mem.peek(0xD012) == 100 and mem.peek(0xD011) & 0x80 == 0
    m.cpu.processorCycles = 63 * 300
    assert mem.peek(0xD012) == 300 - 256 and mem.peek(0xD011) & 0x80
    # $D019's raster flag: set once the compare line has gone by, cleared by writing 1
    mem.poke(0xD012, 10)
    mem.poke(0xD019, 1)
    assert not mem.peek(0xD019) & 1
    m.cpu.processorCycles += FRAME
    mem.tick(m.cpu.processorCycles)                                 # (as the run loop does)
    assert mem.peek(0xD019) & 1
    assert mem.peek(0xDC01) == 0xFF                                 # no keys down


RASTER_IRQ = bytes([
    0x78,                    # sei
    0xA9, 0x20, 0x8D, 0xFE, 0xFF, 0xA9, 0x10, 0x8D, 0xFF, 0xFF,     # $FFFE -> $1020, the handler
    0xA9, 0x64, 0x8D, 0x12, 0xD0,                                   # line 100
    0xA9, 0x01, 0x8D, 0x1A, 0xD0,                                   # raster interrupts on
    0x58,                    # cli
    0x4C, 0x16, 0x10,        # $1016: jmp $1016
])
HANDLER = bytes([0xEE, 0x00, 0xC0, 0xA9, 0x01, 0x8D, 0x19, 0xD0, 0x40])   # inc $c000 / ack / rti


def irq_machine(code: bytes) -> Machine:
    m = ram_only(code)
    m.memory.poke(1, 0x35)                                          # I/O in, ROMs out
    m.memory.write(0x1020, HANDLER)
    return m


def test_a_raster_interrupt_once_a_frame():
    m = irq_machine(RASTER_IRQ)
    m.run(max_cycles=FRAME * 5)
    # once a frame (and once at the cli: the flag's been set since line 0, as on a C64, unacknowledged)
    assert m.memory.ram[0xC000] in (5, 6)
    # on line 100: the handler starts there
    cp = m.add_checkpoint(0x1020, None, 4, stop=True, temporary=False)
    assert m.run(max_cycles=FRAME * 2).checkpoint is cp
    assert m.registers()["LIN"] == 100


def test_cia_1_timer_a_interrupts():
    # $DC04/5 = $4025 (the KERNAL's 60 a second), interrupts from timer A on, start it continuous
    code = bytes([0x78, 0xA9, 0x30, 0x8D, 0xFE, 0xFF, 0xA9, 0x10, 0x8D, 0xFF, 0xFF,
                  0xA9, 0x25, 0x8D, 0x04, 0xDC, 0xA9, 0x40, 0x8D, 0x05, 0xDC,
                  0xA9, 0x81, 0x8D, 0x0D, 0xDC, 0xA9, 0x11, 0x8D, 0x0E, 0xDC, 0x58,
                  0x4C, 0x20, 0x10])                                # $1020: jmp $1020
    m = ram_only(code)
    m.memory.poke(1, 0x35)
    m.memory.write(0x1030, bytes([0xAD, 0x0D, 0xDC, 0xEE, 0x00, 0xC0, 0x40]))   # lda $dc0d (acks) / inc / rti
    m.run(max_cycles=985_248)                                       # a second
    assert 59 <= m.memory.ram[0xC000] <= 61
    assert m.memory.read(0xDC0D, 0xDC0D) == b"\0"                   # (a monitor read doesn't ack it)


def test_a_step_never_goes_into_an_interrupt():
    m = irq_machine(RASTER_IRQ)
    m.run(max_cycles=FRAME // 2)                                    # in the loop, interrupts on
    mon = SimMonitor(None, m)
    mon.connect()
    m.memory.vic_flags |= 1                                         # one's waiting
    for _ in range(3):
        mon.step(1)
        mon.ping()
        assert m.cpu.pc == 0x1016
    mon.resume()
    mon.ping()
    assert m.memory.ram[0xC000] >= 1                                # running, it's taken


def test_carrying_on_from_a_breakpoint_with_an_interrupt_waiting():
    m = irq_machine(RASTER_IRQ)
    cp = m.add_checkpoint(0x1016, None, 4, stop=True, temporary=False)
    assert m.run().checkpoint is cp
    before = m.memory.ram[0xC000]
    m.memory.vic_flags |= 1
    s = m.run(max_cycles=FRAME // 4)                                # the interrupt, then back: no stop there
    assert m.memory.ram[0xC000] == before + 1
    assert s.why == "checkpoint" and cp.hits >= 2                   # (the next time round, it stops)


@needs_roms
def test_the_kernal_interrupt_ticks_the_clock():
    m = Machine()
    m.boot()
    before = m.memory.ram[0xA2]
    m.run(max_cycles=985_248)                                       # a second
    assert (m.memory.ram[0xA2] - before) & 0xFF in range(58, 62)    # the jiffy clock: 60 a second


def test_cycles_are_the_6510s():
    # lda $10ff,x (crosses a page: 5) / sta $1100,x (5) / beq +0 taken (3) / lda ($fb),y crossing (6)
    m = ram_only(bytes([0xA2, 0x01, 0xBD, 0xFF, 0x10, 0x9D, 0x00, 0x11, 0xF0, 0x00, 0xB1, 0xFB, 0x00]))
    m.memory.write(0xFB, bytes([0xFF, 0x20]))
    m.cpu.y = 1
    m.run()
    assert m.cycles == 2 + 5 + 5 + 3 + 6


def test_checkpoints_conditions_and_counting():
    # loop: inx / cpx #5 / bne loop / brk
    m = ram_only(bytes([0xE8, 0xE0, 0x05, 0xD0, 0xFB, 0x00]))
    count = m.add_checkpoint(0x1000, None, 4, stop=False, temporary=False)
    stop = m.add_checkpoint(0x1003, None, 4, stop=True, temporary=False)
    stop.condition = parse_condition("X == $3")
    s = m.run()
    assert s.why == "checkpoint" and s.checkpoint is stop and m.cpu.x == 3
    assert m.run().why == "brk" and count.hits == 5
    with pytest.raises(MonitorError):
        parse_condition("A & 3")


def test_a_store_checkpoint():
    m = ram_only(bytes([0xA9, 0x07, 0x8D, 0x20, 0xD0, 0xEA, 0x00]))   # lda #7 / sta $d020 / nop / brk
    cp = m.add_checkpoint(0xD020, None, OP_STORE, stop=True, temporary=False)
    s = m.run()
    assert s.why == "checkpoint" and s.checkpoint is cp and m.cpu.pc == 0x1005


def test_step_over_and_out():
    # jsr sub / lda #1 / brk ; sub: ldx #2 / rts
    code = bytes([0x20, 0x06, 0x10, 0xA9, 0x01, 0x00, 0xA2, 0x02, 0x60])
    m = ram_only(code)
    assert m.run(until=m.step_over_until()).why == "step" and m.cpu.pc == 0x1003 and m.cpu.x == 2
    m = ram_only(code)
    m.step()                                                        # into the subroutine
    assert m.cpu.pc == 0x1006
    assert m.run(until=m.step_out_until()).why == "step" and m.cpu.pc == 0x1003


def test_an_opcode_the_6510_has_not_got_stops_it():
    m = ram_only(bytes([0xEA, 0x02]))
    assert m.run().why == "jam" and m.cpu.pc == 0x1001


def test_the_sys_in_a_basic_loader():
    line = bytes([0x0E, 0x08, 0x0A, 0x00, 0x9E, 0x20, 0x28, 0x32, 0x30, 0x36, 0x34, 0x29, 0x00, 0, 0])
    assert basic_sys(line) == 2064
    assert basic_sys(bytes([0x09, 0x08, 0x0A, 0x00, 0x99, 0x22, 0x41, 0x22, 0x00, 0, 0])) is None


@needs_roms
def test_the_kernal_boots_to_ready():
    m = Machine()
    assert m.boot()
    assert m.memory.ram[0x02A6] == 1                                # PAL, found as the KERNAL finds it
    screen = bytes(m.memory.ram[0x0400:0x0400 + 40 * 7])
    assert bytes([0x12, 0x05, 0x01, 0x04, 0x19, 0x2E]) in screen   # READY. in screen codes


def test_the_monitor_reports_a_stop_at_a_breakpoint():
    events = []
    got = threading.Event()

    def on_event(t, body):
        events.append((t, body[0] | body[1] << 8 if len(body) >= 2 else None))
        if t == EVT_STOPPED:
            got.set()
    mon = SimMonitor(on_event, ram_only(bytes([0xE8, 0x4C, 0x00, 0x10])))     # inx / jmp loop
    mon.connect()
    mon.add_checkpoint(0x1001)
    mon.resume()
    assert got.wait(5)
    assert mon.get_registers()["PC"] == 0x1001 and mon.get_registers()["X"] == 1
    mon.delete_checkpoint(1)
    got.clear()
    mon.resume()                                                    # runs for ever: a command stops it
    mon.ping()
    assert got.is_set() and mon.last_stop == "halt"
    mon.step(3)
    mon.ping()
    mon.close()


def test_the_screen_as_the_vic_ii_would_show_it():
    ram, io = bytearray(0x10000), bytearray(0x1000)
    io[0x11], io[0x16], io[0x18] = 0x1B, 0xC8, 0x14                 # text, screen $0400, characters $1000
    io[0x20], io[0x21], io[0xD00] = 14, 6, 3                        # border, background, bank 0
    chargen = bytearray(0x1000)
    chargen[8:16] = bytes([0xFF] * 8)                               # character 1: all set
    ram[0x0400] = 1
    io[0x800] = 1                                                   # white
    rgb = simscreen.render(ram, io, chargen)
    px = lambda x, y: rgb[(y * simscreen.WIDTH + x) * 3:(y * simscreen.WIDTH + x) * 3 + 3]   # noqa: E731
    bx, by = simscreen.BORDER_X, simscreen.BORDER_Y
    assert px(0, 0) == simscreen.RGB[14] and px(bx, by) == simscreen.RGB[1] and px(bx + 8, by) == simscreen.RGB[6]
    io[0x15], io[0x00], io[0x01], io[0x27] = 1, 24, 50, 2           # sprite 0, top left, red
    ram[0x07F8] = 0x80
    ram[0x2000] = 0x80
    rgb = simscreen.render(ram, io, chargen)
    assert px(bx, by) == simscreen.RGB[2]


@needs_roms
@pytest.mark.parametrize("name", ["1-basic", "2-assembler", "3-sprites", "6-screen", "7-music", "9-profiler", "10-simulator"])
def test_the_tutorials_transcripts_pass_on_the_simulator(name, tmp_path):
    """Without VICE: what the tutorials say each program does, on the simulated C64."""
    project = next((ROOT / "examples" / "tutorials" / name).glob("*.l64proj"))
    shutil.copytree(project.parent, tmp_path / "p")
    out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "p" / project.name),
                          str(tmp_path / "p" / "tests.transcript"), "--simulate"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and " 0 failed" in out.stdout, out.stdout


# Routines whose cycles VICE and the simulator must agree on: each addressing mode, page crossings,
# branches taken across a page, decimal mode, the stack, JMP ($xxFF), the KERNAL.
TIMED = """*=$c000
absx    ldx #$01
        lda $10ff,x
        lda $1000,x
        sta $10ff,x
        inc $10ff,x
        rts
absy    ldy #$80
        lda $10a0,y
        cmp $1000,y
        sta $10a0,y
        rts
indy    lda #$f0
        sta $fb
        lda #$10
        sta $fc
        ldy #$20
        lda ($fb),y
        sta ($fb),y
        ldy #$05
        lda ($fb),y
        rts
indx    ldx #$04
        lda #$00
        sta $ff
        lda ($fb,x)
        sta ($fb,x)
        rts
zp      lda $fb
        ldx #$10
        lda $f0,x
        asl $fb
        rol $fb
        lsr
        ror
        rts
stack   pha
        php
        plp
        pla
        tsx
        txs
        jsr sub
        rts
sub     rts
decimal sed
        clc
        lda #$19
        adc #$28
        sbc #$09
        cld
        rts
ind     jmp ($c4ff)               ; the 6502 takes the high byte from $c400, not $c500
back    rts
kernal  sec                       ; PLOT: read the cursor position
        jsr $fff0
        rts
loop    ldx #$00
loop1   dex
        bne loop1
        rts
*=$c400
        byte >back
*=$c4ff
        byte <back, $00
*=$c2f0
cross   ldx #$03
cross1  dex
        beq out
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        bne cross1
        nop
out     rts
"""
ROUTINES = ["absx", "absy", "indy", "indx", "zp", "stack", "decimal", "ind", "loop", "cross", "kernal"]


def _vice_ok():
    return os.environ.get("L64S_VICE_TESTS") == "1" and shutil.which("x64sc")


def _cycles(tmp_path: Path, simulate: bool) -> list[int]:
    (tmp_path / "t.asm").write_text(TIMED)
    lines = ["interrupts off", "set $d011 $0b", "wait 0.1"] + [f"call {r}" for r in ROUTINES]
    (tmp_path / "t.transcript").write_text("\n".join(lines) + "\n")
    args = ["--simulate"] if simulate else ["--vice-args=-sounddev dummy"]
    out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "t.asm"),
                          str(tmp_path / "t.transcript"), *args], capture_output=True, text=True, timeout=180)
    found = [int(n.replace(",", "")) for n in re.findall(r"returned after ([\d,]+) cycles", out.stdout)]
    assert len(found) == len(ROUTINES), out.stdout
    return found


@needs_roms
@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_cycles_agree_with_vice(tmp_path):
    (tmp_path / "v").mkdir()
    (tmp_path / "s").mkdir()
    vice, sim = _cycles(tmp_path / "v", False), _cycles(tmp_path / "s", True)
    assert dict(zip(ROUTINES, sim)) == dict(zip(ROUTINES, vice))


def test_stopped_is_an_exception_with_a_reason():
    s = Stopped("brk")
    assert s.why == "brk" and s.checkpoint is None
