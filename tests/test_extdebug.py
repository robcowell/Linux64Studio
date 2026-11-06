from pathlib import Path

from l64s.emu import extdebug
from l64s.emu.cycles import NTSC, PAL, raster_cycles


def test_the_command_line(tmp_path):
    prg = tmp_path / "game.prg"
    dbg = tmp_path / "game.dbg"
    vs = tmp_path / "game.vs"
    for f in (prg, dbg, vs):
        f.write_text("")
    assert extdebug.command("rd", prg, dbg, vs, ["-layout", "9"]) == [
        "rd", "-wait", "2000", "-debuginfo", str(dbg), "-symbols", str(vs), "-prg", str(prg), "-autojmp",
        "-layout", "9"]
    d64 = tmp_path / "game.d64"
    assert extdebug.command("rd", d64)[-3:] == ["-d64", str(d64), "-autorundisk"]
    assert extdebug.command("rd", tmp_path / "cart.crt")[-2:] == ["-crt", str(tmp_path / "cart.crt")]
    # a debug dump that isn't there isn't passed
    assert "-debuginfo" not in extdebug.command("rd", prg, tmp_path / "none.dbg")


def test_finding_it(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(extdebug, "INSTALL_DIR", tmp_path / "rd")
    assert extdebug.find() is None
    exe = tmp_path / "rd" / "RetroDebugger-v1" / "RetroDebugger"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert extdebug.find() == str(exe)
    other = tmp_path / "mine"
    other.write_text("#!/bin/sh\n")
    other.chmod(0o755)
    assert extdebug.find(str(other)) == str(other)            # the one in Preferences


def test_raster_cycles():
    assert raster_cycles((10, 5), (10, 9)) == 4
    assert raster_cycles((311, 60), (0, 2), PAL) == 5                       # round the end of the frame
    assert raster_cycles((0, 0), (1, 0), NTSC) == 65
