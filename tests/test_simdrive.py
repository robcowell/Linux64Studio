"""The simulated C64's disk drive (emu.simdrive): its DOS on its own, then with the real KERNAL on
the simulator, and (opt-in) the same BASIC program's disk work in VICE, with its emulated 1541."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from l64s.disk.image import DiskImage
from l64s.emu.sim import Machine, find_roms
from l64s.emu.simdrive import ACPTR, CIOUT, LISTEN, SECOND, TALK, TKSA, UNLSN, UNTLK, Bus, Drive, matches, parse_name

needs_roms = pytest.mark.skipif(len(find_roms()) < 3, reason="VICE's C64 ROMs aren't installed")


def disk() -> DiskImage:
    d = DiskImage.blank("d64", "test disk", "ab")
    d.add_file("game", bytes([0x00, 0xC0, 1, 2, 3]))
    d.add_file("notes", b"HELLO\rWORLD\r", "seq")
    return d


def opened(drive: Drive, channel: int, name: bytes) -> None:
    drive.listen()
    drive.second(0xF0 | channel)
    for b in name:
        drive.send(b)
    drive.unlisten()


def read_all(drive: Drive, channel: int) -> tuple[bytes, int]:
    """Everything on a channel, up to EOI, and the last byte's ST bits."""
    drive.talk()
    drive.second(0x60 | channel)
    out = bytearray()
    while True:
        b, st = drive.receive()
        if st & 0x02:
            drive.untalk()
            return bytes(out), st
        out.append(b)
        if st & 0x40:
            drive.untalk()
            return bytes(out), st


def written(drive: Drive, channel: int, data: bytes) -> None:
    drive.listen()
    drive.second(0x60 | channel)
    for b in data:
        drive.send(b)
    drive.unlisten()


def closed(drive: Drive, channel: int) -> None:
    drive.listen()
    drive.second(0xE0 | channel)
    drive.unlisten()


def command(drive: Drive, text: bytes) -> str:
    written(drive, 15, text + b"\r")
    return read_all(drive, 15)[0].decode().rstrip("\r")


# ---------------------------------------------------------------------- the DOS


def test_patterns_match_as_the_dos_matches_them():
    assert matches(b"GAME", b"GAME") and not matches(b"GAM", b"GAME") and not matches(b"GAMES", b"GAME")
    assert matches(b"G*", b"GAME") and matches(b"*", b"ANY") and matches(b"G?ME", b"GAME")
    assert not matches(b"G?ME", b"GAMES")


def test_file_names_with_their_drive_replace_type_and_mode():
    o = parse_name(b"@0:SCORES,S,W")
    assert (o.name, o.replace, o.file_type, o.mode) == (b"SCORES", True, "seq", ord("W"))
    assert parse_name(b"$0:G*").directory and parse_name(b"$0:G*").name == b"0:G*"
    assert parse_name(b"GAME").file_type is None


def test_the_error_channel_starts_with_the_dos_version_then_says_ok():
    d = Drive(disk())
    assert read_all(d, 15)[0] == b"73,CBM DOS V2.6 1541,00,00\r"
    assert read_all(d, 15)[0] == b"00, OK,00,00\r"


def test_reading_a_file_ends_with_eoi_on_its_last_byte():
    d = Drive(disk())
    opened(d, 0, b"GAME")
    data, st = read_all(d, 0)
    assert data == bytes([0x00, 0xC0, 1, 2, 3]) and st == 0x40


def test_a_file_that_isnt_there_times_out_and_says_so():
    d = Drive(disk())
    opened(d, 0, b"MISSING")
    assert read_all(d, 0) == (b"", 0x42)
    assert d.status == "62,FILE NOT FOUND,00,00"


def test_a_type_that_doesnt_match():
    d = Drive(disk())
    opened(d, 2, b"NOTES,P,R")
    assert d.status.startswith("64,FILE TYPE MISMATCH")


def test_writing_a_file_puts_it_on_the_disk_when_its_closed():
    d = Drive(disk())
    opened(d, 2, b"SCORES,S,W")
    written(d, 2, b"100\r")
    assert d.image.find("scores") is None              # (not until it's closed)
    closed(d, 2)
    e = d.image.find("scores")
    assert e.file_type == "seq" and d.image.read_file(e) == b"100\r" and d.changed
    opened(d, 2, b"SCORES,S,W")                         # there already
    assert d.status.startswith("63,FILE EXISTS")
    opened(d, 2, b"@0:SCORES,S,W")                      # replaced
    written(d, 2, b"200\r")
    closed(d, 2)
    opened(d, 3, b"SCORES,A")                           # appended to
    written(d, 3, b"300\r")
    closed(d, 3)
    assert d.image.read_file("scores") == b"200\r300\r"


def test_save_on_channel_1_writes_a_program():
    d = Drive(disk())
    opened(d, 1, b"NEW")
    written(d, 1, bytes([0x01, 0x08, 0xAA]))
    closed(d, 1)
    assert d.image.find("new").file_type == "prg"


def test_the_directory_is_a_basic_program_as_a_1541_sends_it():
    d = Drive(disk())
    opened(d, 0, b"$")
    data, _st = read_all(d, 0)
    assert data[:2] == bytes([0x01, 0x04])
    lines, at = [], 2                                   # (link, line number, text, 0) each
    while data[at:at + 2] != b"\0\0":
        end = data.index(0, at + 4)
        lines.append((data[at + 2] | data[at + 3] << 8, data[at + 4:end]))
        at = end + 1
    assert lines[0] == (0, b'\x12"TEST DISK       " AB 2A')
    assert lines[1][0] == 1 and lines[1][1].startswith(b'   "GAME"             PRG ')
    assert len(lines[1][1]) + 5 == 32                   # each entry 32 bytes, as a 1541's
    assert lines[-1] == (d.image.blocks_free, b"BLOCKS FREE.".ljust(25))
    assert b"BLOCKS FREE." in data and data.endswith(b"\0\0\0")
    opened(d, 0, b"$:N*")
    assert b"NOTES" in read_all(d, 0)[0] and b"GAME" not in read_all(d, 0)[0]
    opened(d, 0, b"$:*=P")
    listing = read_all(d, 0)[0]
    assert b"GAME" in listing and b"NOTES" not in listing


def test_scratch_rename_copy_and_validate():
    d = Drive(disk())
    assert command(d, b"C:BOTH=GAME,NOTES") == "00, OK,00,00"
    assert d.image.read_file("both") == bytes([0x00, 0xC0, 1, 2, 3]) + b"HELLO\rWORLD\r"
    assert command(d, b"R0:RENAMED=BOTH") == "00, OK,00,00" and d.image.find("renamed")
    assert command(d, b"R:GAME=NOTES") == "63,FILE EXISTS,00,00"
    assert command(d, b"S0:RE*,NOTES") == "01, FILES SCRATCHED,02,00"
    assert [e.name for e in d.image.entries()] == ["GAME"]
    assert command(d, b"V") == "00, OK,00,00"
    assert command(d, b"X") == "31,SYNTAX ERROR,00,00"


def test_new_formats_the_disk():
    d = Drive(disk())
    assert command(d, b"N:FRESH,XY") == "00, OK,00,00"
    assert d.image.entries() == [] and d.image.disk_name == "FRESH" and d.image.disk_id == "XY"


def test_buffers_and_the_block_commands():
    d = Drive(disk())
    opened(d, 5, b"#")
    assert command(d, b"U1:5 0 18 0") == "00, OK,00,00"
    command(d, b"B-P 5 144")
    d.talk()
    d.second(0x65)
    assert bytes(d.receive()[0] for _ in range(9)) == b"TEST DISK"
    d.untalk()
    assert command(d, b"B-A 0 1 0") == "00, OK,00,00" and not d.image.is_free(1, 0)
    assert command(d, b"B-A 0 1 0").startswith("65,NO BLOCK,")
    assert command(d, b"B-F 0 1 0") == "00, OK,00,00" and d.image.is_free(1, 0)
    assert command(d, b"U1:9 0 18 0") == "70,NO CHANNEL,00,00"
    assert command(d, b"U1:5 0 99 0") == "66,ILLEGAL TRACK OR SECTOR,99,00"


def test_no_disk_in_the_drive():
    d = Drive(None)
    opened(d, 0, b"GAME")
    assert d.status == "74,DRIVE NOT READY,00,00"


# ---------------------------------------------------------------------- the bus, as the KERNAL calls it


class _Cpu:
    a = x = y = 0
    p = 0x24


def test_the_bus_routines_leave_st_as_the_kernal_does():
    bus, cpu, ram = Bus({8: Drive(disk())}), _Cpu(), bytearray(0x10000)

    def call(pc, a=0):
        cpu.a = a
        bus.routine(pc, cpu, ram)
        return cpu.a
    call(LISTEN, 9)                                      # nothing there
    assert ram[0x90] == 0x80
    ram[0x90] = 0
    call(LISTEN, 8)
    call(SECOND, 0xF0)
    for b in b"GAME":
        call(CIOUT, b)
    call(UNLSN)
    call(TALK, 8)
    call(TKSA, 0x60)
    got = [call(ACPTR) for _ in range(5)]
    call(UNTLK)
    assert got == [0x00, 0xC0, 1, 2, 3] and ram[0x90] == 0x40 and not cpu.p & 0x05


# ---------------------------------------------------------------------- with the KERNAL

PROGRAM = """10 print chr$(147);
20 open15,8,15:open2,8,2,"notes,s,r":input#2,a$:close2:input#15,e:print a$;e
30 open3,8,3,"out,s,w":print#3,"saved":close3
40 print#15,"r:new=out":input#15,e,e$:print e;e$
50 open4,8,4,"missing":input#15,e,e$:print e;e$:close4
60 print#15,"s:new":input#15,e,e$,t:print e;e$;t
70 close15
80 if peek(49152)<>42 then load"data",8,1
90 open5,8,0,"$":fori=0to63:get#5,a$:poke49408+i,asc(a$+chr$(0)):next:close5
"""
# 80 loads DATA into $C000. A LOAD in a program runs it again from the start, which does it all
# again (with the same results), and goes on to read the directory's first 64 bytes into $C100.
CHECKS = """run
wait {wait}
check $0400 = "hello 0"
check $0428 = " 0 ok"
check $0450 = " 62 file not found"
check $0478 = " 1 files scratched 1"
check $c000 = $2a
; the directory, as a 1541 sends it: the disk's name and ID, then a line for each file
check $c100 = $01 $04 $01 $01 $00 $00 $12 $22 'drive test      ' $22 $20 'dt' $20 '2a' $00
check $c120 = $01 $01 $02 $00 '   "d"' '                prg  ' $00
"""


def _project(tmp_path, wait):
    p = tmp_path / "p"
    p.mkdir()
    (p / "main.bas").write_text(PROGRAM)
    (p / "notes.seq").write_bytes(b"HELLO\r")
    (p / "data.prg").write_bytes(bytes([0x00, 0xC0, 0x2A]))
    (p / "d.l64proj").write_text(json.dumps({
        "name": "d", "toolchain": "cbm", "build_list": ["main.bas"], "main_file": "main.bas",
        "executable": "d.prg", "output_dir": ".", "disk_image": "d.d64", "disk_name": "drive test",
        "disk_id": "dt", "disk_extra_files": [{"file": "notes.seq", "name": "notes", "type": "seq"},
                                              {"file": "data.prg", "name": "data", "type": "prg"}]}))
    (p / "t.transcript").write_text(CHECKS.format(wait=wait))
    return p


def _transcript(p, *args):
    return subprocess.run([sys.executable, "-m", "l64s.transcript", str(p / "d.l64proj"), str(p / "t.transcript"),
                           *args], capture_output=True, text=True, timeout=180).stdout


@needs_roms
def test_basic_works_with_files_on_the_simulators_drive(tmp_path):
    out = _transcript(_project(tmp_path, 3), "--simulate")
    assert " 7 checks passed, 0 failed" in out, out


@needs_roms
@pytest.mark.skipif(not (os.environ.get("L64S_VICE_TESTS") == "1" and shutil.which("x64sc")),
                    reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
def test_and_the_same_in_vice_with_its_1541(tmp_path):
    out = _transcript(_project(tmp_path, 25), "--vice-args=-sounddev dummy -drive8truedrive")
    assert " 7 checks passed, 0 failed" in out, out


@needs_roms
def test_load_and_save_from_basic_on_the_simulator():
    m = Machine()
    m.attach_disk(disk())
    assert m.boot()

    def typed(text: str) -> None:
        for i in range(0, len(text), 10):
            m.type_keys(text[i:i + 10].encode())
            m.run(2_000_000, until=lambda: m.memory.peek(0xC6) == 0)
        m.run(20_000_000, until=lambda: m.cpu.pc in range(0xE5CD, 0xE5D7))
    typed('LOAD"GAME",8,1\r')
    assert bytes(m.memory.ram[0xC000:0xC003]) == bytes([1, 2, 3])
    typed('NEW\r10 PRINT"HI"\rSAVE"HI",8\r')
    assert m.drive.image.read_file("hi")[:2] == bytes([0x01, 0x08]) and m.drive.changed
    typed('LOAD"NOPE",8\r')
    text = bytes(m.memory.ram[0x400:0x7E8])
    assert bytes([0x06, 0x09, 0x0C, 0x05, 0x20, 0x0E, 0x0F, 0x14]) in text   # "file not" (FILE NOT FOUND)
    typed('LOAD"X",9\r')
    assert bytes([0x04, 0x05, 0x16, 0x09, 0x03, 0x05]) in bytes(m.memory.ram[0x400:0x7E8])   # "device"
