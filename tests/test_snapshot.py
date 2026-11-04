import os
import shutil
import struct
import time
from pathlib import Path

import pytest

from l64s.snapshot import (Info, SnapshotError, compare, delete_snapshot, list_snapshots, program_stamp, read_vsf,
                           rename_snapshot, safe_name, unique_path)


def make_vsf(path: Path, regs=(0xEB, 0x13, 0x1E, 0xF6), pc=0x088D, fl=0xA5, clock=1000, ram=None, cpu_major=1):
    """A minimal VICE 3.x-style snapshot: header, version block, MAINCPU and C64MEM modules."""
    ram = ram or bytes(0x10000)

    def module(name: str, major: int, minor: int, body: bytes) -> bytes:
        return name.encode().ljust(16, b"\0") + bytes([major, minor]) + struct.pack("<I", 22 + len(body)) + body
    cpu = struct.pack("<Q", clock) + bytes(regs) + struct.pack("<H", pc) + bytes([fl]) + bytes(20)
    data = (b"VICE Snapshot File\x1a" + b"\x02\x00" + b"C64SC".ljust(16, b"\0") + b"VICE Version\x1a"
            + bytes([3, 7, 1, 0, 0, 0, 0, 0]) + module("MAINCPU", cpu_major, 2, cpu)
            + module("C64MEM", 0, 1, bytes([0x37, 0x2F, 1, 1]) + ram) + module("SID", 1, 0, bytes(30)))
    path.write_bytes(data)
    return path


def test_read_vsf(tmp_path):
    ram = bytearray(0x10000)
    ram[0x0888:0x088B] = b"\xa9\xeb\xcd"
    s = read_vsf(make_vsf(tmp_path / "a.vsf", ram=bytes(ram)))
    assert s.registers == {"A": 0xEB, "X": 0x13, "Y": 0x1E, "SP": 0xF6, "PC": 0x088D, "FL": 0xA5}
    assert (s.machine, s.vice_version, s.clock) == ("C64SC", "3.7.1", 1000)
    assert s.ram[0x0888:0x088B] == b"\xa9\xeb\xcd" and len(s.ram) == 0x10000
    assert s.modules == ["MAINCPU", "C64MEM", "SID"]


def test_bad_files(tmp_path):
    (tmp_path / "x.vsf").write_bytes(b"not a snapshot")
    with pytest.raises(SnapshotError, match="isn't a VICE snapshot"):
        read_vsf(tmp_path / "x.vsf")
    with pytest.raises(SnapshotError, match="MAINCPU version 2"):
        read_vsf(make_vsf(tmp_path / "y.vsf", cpu_major=2))
    good = (make_vsf(tmp_path / "z.vsf")).read_bytes()
    (tmp_path / "t.vsf").write_bytes(good[:-10])
    with pytest.raises(SnapshotError, match="damaged"):
        read_vsf(tmp_path / "t.vsf")


def test_compare(tmp_path):
    ram_a, ram_b = bytearray(0x10000), bytearray(0x10000)
    ram_b[0xC000:0xC003] = b"\x11\x22\x33"
    ram_b[0xC005] = 0x44          # within 4 bytes: same range
    ram_b[0xD800] = 0x01
    a = read_vsf(make_vsf(tmp_path / "a.vsf", ram=bytes(ram_a)))
    b = read_vsf(make_vsf(tmp_path / "b.vsf", regs=(0xEB, 0x42, 0x1E, 0xF6), ram=bytes(ram_b), clock=985248 + 1000))
    d = compare(a, b)
    assert d.registers == {"X": (0x13, 0x42)}
    assert d.ranges == [(0xC000, 0xC005), (0xD800, 0xD800)] and d.changed_bytes == 5
    assert d.clock_delta == 985248


def test_notes_list_rename_delete(tmp_path):
    a = make_vsf(unique_path(tmp_path, "before boss"))
    Info(name="before boss", note="lives: 3", created=100, pc=0x888).save(a)
    b = make_vsf(unique_path(tmp_path, "before boss"))
    assert b.name == "before boss (2).vsf"
    Info(name="later", created=200).save(b)
    assert [i.name for _p, i in list_snapshots(tmp_path)] == ["later", "before boss"]   # newest first
    moved = rename_snapshot(a, "level 2")
    assert moved.name == "level 2.vsf" and Info.load(moved).note == "lives: 3" and not a.exists()
    delete_snapshot(moved)
    assert not moved.exists() and not moved.with_suffix(".json").exists()
    assert safe_name("a/b:c?") == "a_b_c_" and safe_name("   ") == "snapshot"
    assert Info.load(tmp_path / "missing.vsf").name == "missing"


def test_program_stamp(tmp_path):
    p = tmp_path / "g.prg"
    p.write_bytes(b"\x01\x08")
    assert program_stamp(p).startswith("2:") and program_stamp(None) == ""


@pytest.mark.skipif(not (os.environ.get("L64S_VICE_TESTS") and shutil.which("x64sc")),
                    reason="set L64S_VICE_TESTS=1 to run against VICE (opens emulator windows)")
def test_save_and_restore_with_vice(tmp_path):
    from l64s.emu import vice
    from l64s.emu.binmon import BinaryMonitor
    prg = tmp_path / "loop.prg"
    prg.write_bytes(bytes([0x01, 0x08, 0x0B, 0x08, 0x0A, 0x00, 0x9E, 0x32, 0x30, 0x36, 0x31, 0, 0, 0,
                           0xEE, 0x20, 0xD0, 0x4C, 0x0D, 0x08]))   # 10 SYS 2061: inc $d020 / jmp $080d
    port = vice.free_port()
    p = vice.launch(prg, monitor_port=port, extra_args=["+sound", "-warp"])
    try:
        assert vice.wait_for_port(port)
        m = BinaryMonitor()
        m.connect(port=port)
        m.resume()
        time.sleep(3)
        m.ping()
        m.write_memory(0xC000, b"before")
        m.dump(str(tmp_path / "s.vsf"))
        m.write_memory(0xC000, b"after!")
        pc = m.undump(str(tmp_path / "s.vsf"))
        assert m.read_memory(0xC000, 0xC005) == b"before"
        m.quit()
        m.close()
    finally:
        p.terminate()
    s = read_vsf(tmp_path / "s.vsf")
    assert s.ram[0xC000:0xC006] == b"before" and s.registers["PC"] == pc and 0x080D <= pc <= 0x0812
