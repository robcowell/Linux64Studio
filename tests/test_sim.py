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
@pytest.mark.parametrize("name", ["1-basic", "2-assembler", "3-sprites", "6-screen", "7-music", "8-disk", "9-profiler",
                                  "10-simulator", "11-raster", "12-scroll", "13-joystick", "13-joystick play",
                                  "14-sound", "15-kickass"])
def test_the_tutorials_transcripts_pass_on_the_simulator(name, tmp_path):
    """Without VICE: what the tutorials say each program does, on the simulated C64 (and tutorial 13's
    play.transcript, which only the simulator can run: it pushes the joystick)."""
    from l64s.project.build import default_kickass_jar
    from l64s.sid.goattracker import find_tool
    name, _, which = name.partition(" ")
    if name == "7-music" and find_tool("gt2reloc") is None:
        pytest.skip("GoatTracker's gt2reloc isn't installed (it packs the song)")
    if name == "15-kickass" and not (default_kickass_jar() and shutil.which("java")):
        pytest.skip("Kick Assembler (or Java) isn't installed")
    project = next((ROOT / "examples" / "tutorials" / name).glob("*.l64proj"))
    shutil.copytree(project.parent, tmp_path / "p")
    out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "p" / project.name),
                          str(tmp_path / "p" / f"{which or 'tests'}.transcript"), "--simulate"],
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
    from l64s.emu.simscreen import _pattern, _sprite_colours

    def row(data, multi, wide):
        return _pattern(0, _sprite_colours(bytes(data), multi, wide, 1, 2, 3))
    assert row([0x80, 0, 1], False, False) == 1 | 1 << 23        # hires: bit 0 the leftmost
    assert row([0x80, 0, 0], False, True) == 3                   # twice as wide
    assert row([0x40, 0, 0], True, False) == 3                   # a multicolour pair: 2 pixels
    assert row([0x00, 0, 0], True, True) == 0


SPLIT = """*=$0801
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
        lda #$80        ; sprites 0 and 1: solid, at x 100
        sta $07f8
        sta $07f9
        lda #100
        sta $d000
        sta $d002
        lda #60         ; sprite 1 at y 60, where sprite 0 is first
        sta $d003
        lda #3
        sta $d015
frame   lda #20         ; line 20: sprite 0 at y 60, a black border
@w1     cmp $d012
        bne @w1
        lda #60
        sta $d001
        lda #0
        sta $d020
        lda #100        ; line 100: sprite 0 again further down, at 150, and a red border
@w2     cmp $d012
        bne @w2
        lda #150
        sta $d001
        lda #2
        sta $d020
        lda #200        ; line 200: the border black again
@w3     cmp $d012
        bne @w3
        lda #0
        sta $d020
loop    jmp frame
*=$2000
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
"""


@needs_roms
def test_a_raster_split_and_a_multiplexed_sprite_on_the_screen(tmp_path):
    from l64s.emu.sim import Machine
    (tmp_path / "s.asm").write_text(SPLIT)
    from l64s.asm.cli import main as l64asm
    assert l64asm([str(tmp_path / "s.asm"), "-o", str(tmp_path / "s.prg")]) == 0
    m = Machine()
    m.boot()
    m.load((tmp_path / "s.prg").read_bytes())
    m.type_keys(b"RUN\r")
    m.run(max_cycles=FRAME * 10)
    mem = m.memory
    rgb = simscreen.render(mem.ram, mem.io, mem.chargen, *mem.screen_frame(whole=True))
    px = lambda x, line: rgb[((line - simscreen.FIRST_LINE) * simscreen.WIDTH + x) * 3:][:3]   # noqa: E731
    assert px(2, 60) == simscreen.RGB[0] and px(2, 120) == simscreen.RGB[2] and px(2, 220) == simscreen.RGB[0]
    sx = simscreen.BORDER_X + 100 - 24 + 4                         # inside the sprites, across
    white = simscreen.RGB[mem.io[0x27] & 15]
    assert px(sx, 65) == white and px(sx, 155) == white            # sprite 0 twice
    assert px(sx, 110) != white
    assert mem.collided_sprites == 3                               # sprite 1 met sprite 0's first showing


@needs_roms
@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_a_multiplexed_sprites_collision_as_in_vice(tmp_path):
    (tmp_path / "s.asm").write_text(SPLIT)
    (tmp_path / "s.transcript").write_text("run until loop\nwait 0.2\ncheck $d01e = $03\n")
    for args in (["--simulate"], ["--vice-args=-sounddev dummy"]):
        out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "s.asm"),
                              str(tmp_path / "s.transcript"), *args], capture_output=True, text=True,
                             timeout=120).stdout
        assert " 1 check passed, 0 failed" in out, (args, out)


# The Screen against VICE's picture: tests/fixtures/simscreen's programs, each drawing a steady frame
# with something the Screen must draw as the VIC-II does. Each picture's digest is of the Screen's
# colour numbers, which test_the_screen_as_vice_shows_it found the same as VICE's, pixel for pixel.
SCREENS = {"text": "529803ea0cdf9e9f", "bitmap": "26bde9335693e4bd", "border": "4ff71abd85139fb4"}


def _screen_program(name: str, tmp_path) -> Path:
    from l64s.asm.cli import main as l64asm
    prg = tmp_path / f"{name}.prg"
    assert l64asm([str(ROOT / "tests" / "fixtures" / "simscreen" / f"{name}.asm"), "-o", str(prg)]) == 0
    return prg


def _simulated_screen(prg: Path) -> list[list[int]]:
    m = Machine()
    m.boot()
    m.load(prg.read_bytes())
    m.type_keys(b"RUN\r")
    m.run(max_cycles=FRAME * 30)
    m.run(max_cycles=FRAME, until=lambda: m.memory.line() == 200)     # (past the changes the frames make)
    mem = m.memory
    return simscreen.indices(mem.ram, mem.io, mem.chargen, *mem.screen_frame(whole=True))


def _digest(picture: list[list[int]]) -> str:
    import hashlib
    return hashlib.sha256(bytes(c for row in picture for c in row)).hexdigest()[:16]


@needs_roms
@pytest.mark.parametrize("name", sorted(SCREENS))
def test_the_screens_picture_is_vices(name, tmp_path):
    assert _digest(_simulated_screen(_screen_program(name, tmp_path))) == SCREENS[name]


@needs_roms
@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
@pytest.mark.parametrize("name", sorted(SCREENS))
def test_the_screen_as_vice_shows_it(name, tmp_path):
    from l64s.emu import vice
    from l64s.emu.binmon import BinaryMonitor
    prg = _screen_program(name, tmp_path)
    ours = _simulated_screen(prg)
    port = vice.free_port()
    proc = vice.launch(prg, "", None, port, ["-sounddev", "dummy"])
    try:
        assert vice.wait_for_port(port, 15)
        mon = BinaryMonitor()
        mon.connect(port=port)
        time.sleep(3)
        mon.ping()
        mon.resume()
        time.sleep(2)
        width, _height, wx, wy, pixels = mon.display()
        mon.quit()
    finally:
        proc.terminate()
    differ = []
    for py, row in enumerate(ours):
        line = simscreen.FIRST_LINE + py
        for px, c in enumerate(row):
            if px < 4:                                     # (left of what VICE draws)
                continue
            x = wx + 4 + px - simscreen.BORDER_X           # the display window's left is at wx + 4
            y = wy - 1 + line - simscreen.TOP_LINE         # and its top at wy - 1
            if pixels[y * width + x] & 15 != c:
                differ.append((px, line, c, pixels[y * width + x] & 15))
    assert not differ, f"{len(differ)} pixels differ (x, line, ours, VICE's): {differ[:10]}"
    assert _digest(ours) == SCREENS[name]


# ---------------------------------------------------------------------- the VIC-II taking the bus

def _bus(d011=0x1B):
    """A simulated C64's memory with the screen on (or as d011 says), a frame's start just gone."""
    m = Machine(roms={})
    mem = m.memory
    mem.io[0x11] = d011
    mem.resync_vic(40 * 63)
    return mem


def test_a_read_on_a_badline_waits_for_the_vic_ii_and_a_write_doesnt_at_first():
    from l64s.emu.sim import WRITES
    mem = _bus()
    line = 51 * 63                                     # (51 & 7 == 3: a badline)
    assert mem.stall(line + 11, 2, ()) == 43           # reads from cycle 12: wait until cycle 55
    assert mem.stall(line + 8, 4, WRITES[0x8D]) == 0   # STA abs: its write at cycle 12 goes ahead
    mem = _bus()
    assert mem.stall(line + 9, 4, WRITES[0x8D]) == 43  # but a read in cycle 12 waits
    mem = _bus()
    assert mem.stall(line + 12, 6, WRITES[0xEE]) == 42  # INC abs from cycle 13: waits until 55
    mem = _bus()
    assert mem.stall(52 * 63 + 11, 4, ()) == 0         # not a badline
    mem = _bus(0x0B)
    assert mem.stall(line + 11, 4, ()) == 0            # the screen off: none


def test_a_sprite_takes_two_cycles_and_three_before_them():
    mem = _bus(0x0B)
    mem.io[0x15], mem.io[0x01] = 1, 100                # sprite 0 at Y 100
    t = 100 * 63 + 54                                  # cycle 55 of its line: BA goes low
    assert mem.stall(t, 2, ()) == 5                    # reads wait out cycles 55-59
    mem.io[0x15] = 0
    mem = _bus(0x0B)
    mem.io[0x15], mem.io[0x01], mem.io[0x17] = 1, 100, 1
    total = sum(mem.stall(t + 63 * k, 2, ()) for k in range(45))
    assert total == 42 * 5                             # twice as tall: 42 lines of DMA


def test_inc_d019_acknowledges_the_vic_iis_interrupt():
    m = ram_only(bytes([0xEE, 0x19, 0xD0]))            # inc $d019
    m.memory.poke(1, 0x35)                             # (I/O in)
    m.memory.vic_flags = 1
    m.step()
    assert m.memory.vic_flags == 0                     # its first write, of what it read, clears it


# A program run to `mark` in VICE, then VICE's state is copied into the simulator, and both run on
# to `done`, about 1.9 frames later (the screen on, eight sprites, a raster interrupt): the raster
# position there must be the same, to the cycle.
TIMING = """*=$0801
        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00
*=$080D
start   sei
        lda #$7f
        sta $dc0d
        lda $dc0d
        lda #{d011}
        sta $d011
        ldx #15
@pos    lda where,x
        sta $d000,x
        dex
        bpl @pos
        lda #%10100101  ; 0, 2, 5 and 7 twice as tall
        sta $d017
        lda #{sprites}
        sta $d015
        lda #<handler
        sta $0314
        lda #>handler
        sta $0315
        lda #100
        sta $d012
        lda #{irq}
        sta $d01a
frame   lda #250        ; (where no sprite has DMA on: the copy doesn't carry it)
@w      cmp $d012
        bne @w
mark    nop
        cli
        ldy #3
outer   ldx #0
work    lda $1000
        sta $1001
        inc $1002
        jsr sub
        pha
        pla
        lda ($fb),y
        sta $1100,x
        dex
        bne work
        dey
        bne outer
done    nop
        sei
        jmp frame
sub     rts
where   byte 30,40, 60,41, 90,100, 120,101, 150,170, 180,200, 210,10, 240,195
handler inc $d019
        jmp $ea81
"""
TIMINGS = {"badlines": ("$1b", "0", "0"), "scrolled 0": ("$18", "0", "0"), "sprites": ("$0b", "$ff", "0"),
           "all": ("$1b", "$ff", "1"), "scrolled 7": ("$1f", "$ff", "1")}


def _from_vice(tmp_path, source: str, memory: tuple[int, int] | None = None):
    """Run ``source`` in VICE to its ``mark``, copy VICE's state into the simulator (the RAM, the 6510,
    the raster position, the VIC-II's registers and interrupt flags; the program sets up the CIAs
    afresh after ``mark``), and run both on to ``done``. Returns the cycles each took to get there
    (as a raster position: mod a frame), and each one's ``memory`` (first, last) then."""
    from l64s.asm.cli import main as l64asm
    from l64s.emu import vice
    from l64s.emu.binmon import EVT_STOPPED, BinaryMonitor
    from l64s.emu.sim import CYCLES_PER_LINE, load_snapshot
    (tmp_path / "t.asm").write_text(source)
    assert l64asm([str(tmp_path / "t.asm"), "-o", str(tmp_path / "t.prg"), "-l", str(tmp_path / "t.vs"), "-q"]) == 0
    labels = {p[2].lstrip("."): int(p[1].split(":")[-1], 16) for p in
              (line.split() for line in (tmp_path / "t.vs").read_text().splitlines()) if len(p) >= 3}
    stopped = threading.Event()
    mon = BinaryMonitor(lambda t, _b: stopped.set() if t == EVT_STOPPED else None)
    port = vice.free_port()
    proc = vice.launch(tmp_path / "t.prg", "", None, port, ["-sounddev", "dummy", "-warp"])
    try:
        assert vice.wait_for_port(port, 15)
        mon.connect(port=port)
        time.sleep(2)

        def run_to(label):
            cp = mon.add_checkpoint(labels[label])
            stopped.clear()
            mon.resume()
            assert stopped.wait(20)
            mon.delete_checkpoint(cp.id)
            return mon.get_registers()
        at_mark = run_to("mark")
        mon.dump(str(tmp_path / "mark.vsf"))
        vic = mon.read_memory(0xD000, 0xD02E)
        at_done = run_to("done")
        vice_memory = mon.read_memory(*memory) if memory else b""
        mon.quit()
    finally:
        proc.terminate()

    def position(r):
        return r["LIN"] * CYCLES_PER_LINE + r["CYC"]
    m = Machine()
    load_snapshot(m, tmp_path / "mark.vsf")
    mem, c = m.memory, m.cpu
    t = c.processorCycles - c.processorCycles % FRAME + position(at_mark)     # VICE's raster position
    c.processorCycles = t
    mem.io[0:0x2F] = vic
    mem.io[0x11] &= 0x7F                               # (read, $D011 and $D012 are the raster line;
    mem.io[0x12] = labels.get("compare", 100)          # written, the interrupt's)
    mem.vic_flags = vic[0x19] & 0x0F
    mem.resync_vic(t)
    mem.schedule_raster()
    mem.next_frame = t - t % FRAME + FRAME
    mem.next_line = t - t % CYCLES_PER_LINE + 14
    mem.due = 0
    m.run(max_cycles=FRAME * 3, until=lambda: c.pc == labels["done"])
    sim_memory = bytes(mem.ram[memory[0]:memory[1] + 1]) if memory else b""
    return ((position(at_done) - position(at_mark)) % FRAME, (position(m.registers()) - position(at_mark)) % FRAME,
            vice_memory, sim_memory)


@needs_roms
@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
@pytest.mark.parametrize("name", sorted(TIMINGS))
def test_the_cycles_the_vic_ii_takes_as_in_vice(name, tmp_path):
    d011, sprites, irq = TIMINGS[name]
    vice_took, sim_took, _v, _s = _from_vice(tmp_path, TIMING.format(d011=d011, sprites=sprites, irq=irq))
    assert sim_took == vice_took


# ---------------------------------------------------------------------- the CIAs

def _cia():
    from l64s.emu.simcia import Cia
    return Cia()


def test_a_timer_starts_three_cycles_on_and_reads_its_latch_where_it_would_read_0():
    c = _cia()
    c.write(4, 10, 0)
    c.write(5, 0, 0)
    c.write(14, 0x19, 100)                              # one-shot, loaded, started at cycle 100
    counts = [c.read(4, 100 + d, clear=False) for d in range(16)]
    assert counts[:4] == [10, 10, 10, 10] and counts[4:13] == [9, 8, 7, 6, 5, 4, 3, 2, 1]
    assert counts[13:] == [10, 10, 10]                  # ran out at 113 (one-shot: stopped)
    assert not c.cra & 1
    c = _cia()
    c.write(4, 10, 0)
    c.write(5, 0, 0)
    c.write(14, 0x19, 100)
    assert c.read(13, 112, clear=False) == 0 and c.read(13, 113, clear=False) == 1   # its flag, as it runs out


def test_a_continuous_timer_runs_out_every_latch_plus_1_cycles():
    c = _cia()
    c.write(4, 4, 0)
    c.write(5, 0, 0)
    c.write(14, 0x11, 0)                               # continuous: 4 ... 1, then 4 twice
    assert [c.read(4, t, clear=False) for t in range(3, 15)] == [4, 3, 2, 1, 4, 4, 3, 2, 1, 4, 4, 3]


def test_timer_b_counts_timer_a_running_out():
    c = _cia()
    for r, v in ((4, 9), (5, 0), (6, 2), (7, 0)):
        c.write(r, v, 0)
    c.write(14, 0x11, 0)
    c.write(15, 0x51, 0)                               # B: counts A running out, from 2
    c.update(3 + 9 + 10 * 2 + 1)                       # A's third time
    assert c.flags & 2 and c.read(6, 3 + 9 + 10 * 2 + 1, clear=False) == 2   # B ran out, and reloaded


def test_reading_the_flags_clears_them_and_the_mask_says_which_interrupt():
    c = _cia()
    c.write(4, 5, 0)
    c.write(5, 0, 0)
    c.write(14, 0x19, 0)
    assert not c.line(100)                             # flag set, but not let through
    c.write(13, 0x81, 100)
    assert c.line(102) and c.read(13, 102) == 0x81
    assert c.read(13, 103) == 0 and not c.line(104)


def test_the_time_of_day_clock():
    from l64s.emu.simcia import CLOCK
    c = _cia()
    c.write(14, 0x80, 0)                               # 50 Hz
    for r, v in ((11, 0x91), (10, 0x59), (9, 0x59), (8, 0x09)):  # 11:59:59.9 PM
        c.write(r, v, 0)
    c.write(15, 0x80, 0)                               # the alarm: 12:00:00.1 AM
    for r, v in ((11, 0x12), (10, 0), (9, 0), (8, 1)):
        c.write(r, v, 0)
    c.write(15, 0, 0)
    t = CLOCK // 10 + 1000
    assert [c.read(r, t, clear=False) for r in (11, 10, 9, 8)] == [0x12, 0, 0, 0]   # midnight
    t = 2 * CLOCK // 10 + 1000
    assert c.read(11, t) == 0x12 and c.flags & 4      # the alarm; reading the hours latches...
    later = 5 * CLOCK // 10 + 1000
    assert c.read(8, later) == 1                       # ...until the tenths are read
    assert c.read(8, later, clear=False) == 4
    c.write(11, 0x01, later)                           # writing the hours stops it
    assert c.read(8, 2 * CLOCK, clear=False) == 4
    c.write(8, 0, 2 * CLOCK)                           # until the tenths are written
    assert c.read(8, 2 * CLOCK + CLOCK // 10 + 1000, clear=False) == 1


def test_cia_2s_interrupt_is_an_nmi_taken_once_until_acknowledged():
    m = ram_only(bytes([0xEA] * 16 + [0x4C, 0x00, 0x10]))     # nops, jmp $1000
    mem = m.memory
    mem.poke(1, 0x35)
    mem.ram[0xFFFA:0xFFFC] = bytes([0x00, 0x20])       # the NMI's handler at $2000: a loop
    mem.ram[0x2000:0x2003] = bytes([0x4C, 0x00, 0x20])
    for r, v in ((0xDD04, 20), (0xDD05, 0), (0xDD0D, 0x81), (0xDD0E, 0x11)):
        mem.poke(r, v)
    m.run(max_cycles=60, interrupts=True)
    assert 0x2000 <= m.cpu.pc < 0x2003
    sp = m.cpu.sp
    m.run(max_cycles=200, interrupts=True)            # its line stays low: no more NMIs
    assert m.cpu.sp == sp


@needs_roms
def test_run_stop_and_restore_stop_a_basic_program():
    from l64s.emu.sim import key_named
    m = Machine()
    assert m.boot()
    for chunk in (b"10 GOTO 10", b"\rRUN\r"):
        m.type_keys(chunk)
        m.run(max_cycles=FRAME * 5)
    m.run(max_cycles=FRAME * 10)
    assert not 0xE5CD <= m.cpu.pc <= 0xE5D6            # running
    m.memory.held |= {key_named("stop"), key_named("restore")}
    m.run(max_cycles=FRAME * 10)
    m.memory.held.clear()
    assert m.run(max_cycles=FRAME * 50, until=lambda: 0xE5CD <= m.cpu.pc <= 0xE5D6).why == "step"


# CIA 2's timers, flags and NMIs against VICE's: after `mark` the program starts timer A (every 1000
# cycles) and timer B (counting A), samples them and the flags as fast as it can, then has NMIs from
# timer A (the handler keeping timer A as it starts) with the screen on. The samples must be VICE's.
CIA_SAMPLES = """*=$0801
        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00
*=$080D
start   sei
        lda #$7f
        sta $dc0d
        lda $dc0d
        lda #$0b        ; the screen off at first
        sta $d011
        lda #<nmi
        sta $0318
        lda #>nmi
        sta $0319
frame   lda #250
@w      cmp $d012
        bne @w
mark    nop
        lda #$7f        ; CIA 2: no interrupts, the flags cleared
        sta $dd0d
        lda $dd0d
        lda #0
        sta $dd0e
        sta $dd0f
        sta count
        lda #<1000      ; timer A: 1000 cycles; B: counts A running out, from 3
        sta $dd04
        lda #>1000
        sta $dd05
        lda #3
        sta $dd06
        lda #0
        sta $dd07
        lda #$11        ; A started (loaded)
        sta $dd0e
        lda #$51        ; B started, counting A
        sta $dd0f
        ldx #0
@s      lda $dd04       ; timer A, B and the flags, as fast as it goes
        sta $4000,x
        lda $dd05
        sta $4100,x
        lda $dd06
        sta $4200,x
        lda $dd0d
        sta $4300,x
        inx
        bne @s
        lda #$1b        ; the screen on, and NMIs from timer A
        sta $d011
        lda #$81
        sta $dd0d
        ldx #0
@t      lda $dd06
        sta $4400,x
        inx
        bne @t
        lda #$7f
        sta $dd0d
done    nop
        jmp frame
nmi     pha
        txa
        pha
        ldx count
        lda $dd04       ; timer A as the handler starts
        sta $4500,x
        lda $dd0d       ; (acknowledged)
        sta $4600,x
        inc count
        pla
        tax
        pla
        rti
count   byte 0
"""


def _cia_timing_program() -> str:
    """For each delay d (0, 2-24), a one-shot timer of 10 started, d cycles waited, then CIA 2's flags,
    timer A's low and high byte read: into $4000+d, $4100+d, $4200+d."""
    lines = ["*=$0801", "        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00", "*=$080D",
             "start   sei", "        lda #$7f", "        sta $dc0d", "        lda $dc0d", "        lda #$0b", "        sta $d011",
             "        lda #$7f", "        sta $dd0d", "frame   lda #250", "@w      cmp $d012", "        bne @w", "mark    nop"]
    for reg, base in (("$dd0d", 0x4000), ("$dd04", 0x4100), ("$dd05", 0x4200)):
        for d in [0] + list(range(2, 25)):
            lines += ["        lda $dd0d", "        lda #0", "        sta $dd0e", "        lda #10", "        sta $dd04",
                      "        lda #0", "        sta $dd05", "        lda #$19", "        sta $dd0e"]
            lines += ["        bit $ea"] * (d % 2) + ["        nop"] * ((d - 3 * (d % 2)) // 2)
            lines += [f"        lda {reg}", f"        sta ${base + d:04x}"]
    lines += ["done    nop", "        jmp frame"]
    return "\n".join(lines) + "\n"


@needs_roms
@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
@pytest.mark.parametrize("program", ["samples", "timing"])
def test_the_cias_as_in_vice(program, tmp_path):
    source = CIA_SAMPLES if program == "samples" else _cia_timing_program()
    vice_took, sim_took, vice_memory, sim_memory = _from_vice(tmp_path, source, (0x4000, 0x47FF))
    differ = [(hex(0x4000 + i), v, s) for i, (v, s) in enumerate(zip(vice_memory, sim_memory)) if v != s]
    assert not differ, f"{len(differ)} bytes differ (address, VICE's, the simulator's): {differ[:10]}"
    assert sim_took == vice_took


def test_the_vic_iis_missing_bits_read_as_1_and_its_registers_repeat():
    m = ram_only(bytes([0xEA]))
    mem = m.memory
    mem.poke(1, 0x35)
    for r, v in ((0xD01A, 0x01), (0xD016, 0x08), (0xD018, 0x14), (0xD020, 0x02)):
        mem.poke(r, v)
    assert [mem.peek(r) for r in (0xD01A, 0xD016, 0xD018, 0xD020)] == [0xF1, 0xC8, 0x15, 0xF2]   # as VICE's
    assert mem.peek(0xD030) == 0xFF and mem.peek(0xD060) == 0xF2   # nothing at $D02F-$D03F; $D040 is $D000
