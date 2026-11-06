"""The simulated C64 (emu.sim): its memory, raster line, checkpoints and stepping, the KERNAL booting
on it, transcripts run on it, its screen, and its cycle counts against VICE's."""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
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


# ---------------------------------------------------------------------- joysticks, keys, snapshots

def test_the_joysticks_and_the_keyboard_matrix():
    from l64s.emu.sim import JOY_BITS, key_named
    m = ram_only(bytes([0xEA]))
    mem = m.memory
    mem.poke(1, 0x35)
    mem.poke(0xDC02, 0xFF)                                          # port A: outputs (the columns)
    mem.poke(0xDC00, 0xFF)
    assert (mem.peek(0xDC00), mem.peek(0xDC01)) == (0xFF, 0xFF)     # nothing pressed
    mem.joysticks[2] = JOY_BITS["right"] | JOY_BITS["fire"]
    mem.joysticks[1] = JOY_BITS["up"]
    assert mem.peek(0xDC00) == 0xFF & ~0x18 and mem.peek(0xDC01) == 0xFE
    mem.joysticks = [0, 0, 0]
    mem.held.add(key_named("space"))                                # column 7, row 4
    assert mem.peek(0xDC01) == 0xFF                                 # its column isn't selected
    mem.poke(0xDC00, 0x7F)                                          # column 7 selected
    assert mem.peek(0xDC01) == 0xEF
    mem.poke(0xDC00, 0x00)                                          # all of them (is anything down?)
    assert mem.peek(0xDC01) == 0xEF
    with pytest.raises(MonitorError):
        key_named("hyperspace")


@needs_roms
def test_the_kernal_reads_a_key_held_down():
    from l64s.emu.sim import key_named
    m = Machine()
    m.boot()
    for k in "hi":
        m.memory.held.add(key_named(k))
        m.run(max_cycles=FRAME * 3)
        m.memory.held.clear()
        m.run(max_cycles=FRAME * 3)
    screen = bytes(m.memory.ram[0x0400:0x0400 + 40 * 8])
    assert b"\x08\x09" in screen                                    # HI, typed after READY.


JOYSTICK_GAME = """*=$0801
        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00
*=$080D
start   lda #250        ; once a frame
@wait   cmp $d012
        bne @wait
@leave  cmp $d012
        beq @leave
        lda $dc00       ; joystick 2
        and #%00001000  ; right (0 when it's pushed)
        bne start
        inc xpos
        jmp start
xpos    byte 0
"""


def _transcript(tmp_path, script, *args):
    (tmp_path / "t.asm").write_text(JOYSTICK_GAME)
    (tmp_path / "t.transcript").write_text(script)
    return subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "t.asm"),
                           str(tmp_path / "t.transcript"), *args], capture_output=True, text=True, timeout=120,
                          cwd=tmp_path).stdout


@needs_roms
def test_a_transcript_moves_the_joystick_and_holds_keys(tmp_path):
    out = _transcript(tmp_path, """run until start
wait 1
check xpos = 0
joystick 2 right
wait 1
check xpos >= #49
check xpos <= #51
joystick 2 none
show xpos
wait 1
check xpos <= #51
hold space a
release a
release
""", "--simulate")
    assert " 4 checks passed, 0 failed" in out, out
    assert "keys held: a, space" in out and "keys held: space" in out and "no keys held" in out, out


@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_vice_can_not_move_a_joystick(tmp_path):
    out = _transcript(tmp_path, "run until start\njoystick 2 right\n", "--vice-args=-sounddev dummy")
    assert "joystick needs the simulator" in out, out


def test_a_snapshot_of_the_simulator_goes_on_as_it_was(tmp_path):
    from l64s.emu.sim import load_snapshot, save_snapshot
    from l64s.snapshot import is_simulator_snapshot, read_vsf
    m = irq_machine(RASTER_IRQ)
    m.run(max_cycles=FRAME * 2 + 1234)
    m.memory.joysticks[2] = 8
    save_snapshot(m, tmp_path / "s.vsf")
    snap = read_vsf(tmp_path / "s.vsf")                             # as VICE's are read (the snapshot list)
    assert snap.simulated and is_simulator_snapshot(tmp_path / "s.vsf")
    assert snap.registers["PC"] == m.cpu.pc and snap.ram == bytes(m.memory.ram)
    other = Machine(roms={})
    assert load_snapshot(other, tmp_path / "s.vsf") == m.cpu.pc
    assert other.memory.joysticks[2] == 8
    m.run(max_cycles=FRAME * 3)
    other.run(max_cycles=FRAME * 3)
    assert (other.cycles, other.cpu.pc, bytes(other.memory.ram)) == (m.cycles, m.cpu.pc, bytes(m.memory.ram))


@needs_roms
def test_a_transcript_starts_from_a_snapshot(tmp_path):
    from l64s.emu.sim import save_snapshot
    m = Machine()
    m.boot()
    m.memory.ram[0xC000] = 0x42
    (tmp_path / "snapshots").mkdir()
    save_snapshot(m, tmp_path / "snapshots" / "ready.vsf")
    out = _transcript(tmp_path, "restore ready\ncheck $c000 = $42\n", "--simulate")
    assert "restored ready.vsf" in out and " 1 check passed, 0 failed" in out, out


@needs_roms
@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_a_vice_snapshot_loads_into_the_simulator(tmp_path):
    from l64s.emu.sim import load_snapshot
    from l64s.snapshot import read_vsf
    (tmp_path / "t.asm").write_text(JOYSTICK_GAME)
    (tmp_path / "t.transcript").write_text("run until start\nset $c000 $42\n")
    # take one in VICE: a transcript can't, so run it with the debugger's monitor, as a snapshot is taken
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu import vice
    port = vice.free_port()
    proc = vice.launch(None, "", None, port, ["-sounddev", "dummy"])
    try:
        assert vice.wait_for_port(port, 15)
        mon = BinaryMonitor()
        mon.connect(port=port)
        time.sleep(2)
        mon.ping()
        mon.write_memory(0xC000, b"\x42")
        mon.dump(str(tmp_path / "v.vsf"))
        regs = mon.get_registers()
        mon.quit()
    finally:
        proc.terminate()
    vsf = read_vsf(tmp_path / "v.vsf")
    assert not vsf.simulated
    m = Machine()
    assert load_snapshot(m, tmp_path / "v.vsf") == regs["PC"]
    assert m.memory.ram[0xC000] == 0x42 and m.cpu.sp == regs["SP"]
    assert m.run(max_cycles=FRAME * 10).why == "halt"               # and it runs on (the KERNAL, at READY)


COLLIDE = """*=$0801
        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00
*=$080D
start   sei
        ldx #0          ; a clear screen
        lda #32
@clear  sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $06e8,x
        inx
        bne @clear
        lda #160        ; a solid character at row 10, column 10
        sta $0400+410
        ldx #15         ; sprites 0-3: x, y
@pos    lda where,x
        sta $d000,x
        dex
        bpl @pos
        lda #$80        ; their data at $2000, all solid
        ldx #3
@ptr    sta $07f8,x
        dex
        bpl @ptr
        lda #%00001111
        sta $d015
loop    jmp loop
where   byte 100,200, 110,205, 104,130, 200,130
*=$2000
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
"""
COLLIDE_CHECKS = """run until loop
wait 0.2
check $d01e = $03        ; sprites 0 and 1 overlap
check $d01f = $04        ; sprite 2 is over the solid character
check $d019 & $06 = $06  ; and both flags are set
"""


def _collide(tmp_path, *args):
    (tmp_path / "c.asm").write_text(COLLIDE)
    (tmp_path / "c.transcript").write_text(COLLIDE_CHECKS)
    return subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "c.asm"),
                           str(tmp_path / "c.transcript"), *args], capture_output=True, text=True,
                          timeout=120).stdout


@needs_roms
def test_sprite_collisions(tmp_path):
    out = _collide(tmp_path, "--simulate")
    assert " 3 checks passed, 0 failed" in out, out


@needs_roms
@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_sprite_collisions_as_in_vice(tmp_path):
    out = _collide(tmp_path, "--vice-args=-sounddev dummy")
    assert " 3 checks passed, 0 failed" in out, out


def test_reading_the_collisions_clears_them():
    m = ram_only(bytes([0xEA]))
    mem = m.memory
    mem.poke(1, 0x35)
    mem.collided_sprites = 3
    assert mem.peek(0xD01E) == 3 and mem.peek(0xD01E) == 3        # the debugger's reads don't
    assert mem.peek(0xD01E, True) == 3 and mem.peek(0xD01E) == 0  # the program's do


def test_a_sprite_rows_pixels():
    from l64s.emu.simscreen import _sprite_row
    assert _sprite_row(bytes([0x80, 0, 1]), False, False) == 1 | 1 << 23        # hires: bit 0 the leftmost
    assert _sprite_row(bytes([0x80, 0, 0]), False, True) == 3                   # twice as wide
    assert _sprite_row(bytes([0x40, 0, 0]), True, False) == 3                   # a multicolour pair: 2 pixels
    assert _sprite_row(bytes([0x00, 0, 0]), True, True) == 0
