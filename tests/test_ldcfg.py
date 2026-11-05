import shutil
import subprocess
from pathlib import Path

import pytest

from l64s.project.ldcfg import Area, LayoutError, generate, layout, parse_address

HAVE_CC65 = shutil.which("cl65") is not None
STARFALL = Path(__file__).parent.parent / "examples" / "starfall"


def test_layout_puts_the_program_in_the_biggest_gap():
    main, regions = layout([Area("MUSIC", 0x1000, 0x800)])
    assert main == (0x1800, 0xD000)
    assert [r[0] for r in regions] == ["BOOT", "MUSIC", "MAIN"]
    main, regions = layout([Area("GFX", 0xC000, 0x800)])
    assert main == (0x080D, 0xC000) and [r[0] for r in regions] == ["MAIN", "GFX"]
    main, regions = layout([Area("MUSIC", 0x1000, 0x800), Area("CHARSET", 0x3800, 0x800)])
    assert main == (0x4000, 0xD000) and [r[0] for r in regions] == ["BOOT", "MUSIC", "FILL1", "CHARSET", "MAIN"]


def test_bad_layouts():
    for areas, says in (([Area("MUSIC", 0x0810, 0x100)], "start-up"),
                        ([Area("A", 0x1000, 0x800), Area("B", 0x1400, 0x100)], "overlap"),
                        ([Area("CODE", 0x2000, 0x100)], "cc65's own"),
                        ([Area("my area", 0x2000, 0x100)], "area name"),
                        ([Area("BIG", 0x0900, 0xC6F0)], "too small")):
        with pytest.raises(LayoutError, match=says):
            layout(areas)


def test_config_text():
    cfg = generate([Area("MUSIC", 0x1000, 0x800)])
    assert "    MUSIC:    file = %O, define = yes, start = $1000, size = $0800, fill = yes;" in cfg
    assert "    STARTUP:  load = BOOT,     type = ro;" in cfg and "MUSIC:    load = MUSIC" in cfg
    assert "__HIMEM__:     type = weak, value = $D000;" in cfg
    assert "__HIMEM__:     type = weak, value = $C000;" in generate([Area("GFX", 0xC000, 0x800)])
    assert parse_address("$1000") == parse_address("1000") == parse_address("#4096") == 0x1000


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_the_standard_config_is_cc65_s(tmp_path):
    (tmp_path / "std.cfg").write_text(generate([]))
    srcs = [str(STARFALL / f) for f in ("main.c", "sound.c", "sprites.s")]
    for name, cfg in (("ours", ["-C", str(tmp_path / "std.cfg")]), ("cc65", [])):
        subprocess.run(["cl65", "-t", "c64", *cfg, "-o", str(tmp_path / f"{name}.prg"), "--obj-path", str(tmp_path),
                        *srcs], check=True, cwd=STARFALL, capture_output=True)
    assert (tmp_path / "ours.prg").read_bytes() == (tmp_path / "cc65.prg").read_bytes()


def _starfall(tmp_path):
    from l64s.project.model import load_project
    shutil.copytree(STARFALL, tmp_path / "sf", ignore=shutil.ignore_patterns("build"))
    return load_project(tmp_path / "sf" / "starfall.l64proj")


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_fixed_areas_in_a_build(tmp_path):
    from l64s.project.build import build_project
    p = _starfall(tmp_path)
    (p.directory / "tune.s").write_text('        .segment "MUSIC"\n        .byte $60, $60, $60\n')
    p.build_list.append("tune.s")
    p.c_areas = [{"name": "MUSIC", "start": 0x1000, "size": 0x800}]
    res = build_project(p)
    assert res.ok, res.log
    prg = res.prg.read_bytes()
    assert prg[2 + 0x1000 - 0x0801:][:3] == b"\x60\x60\x60"           # at $1000 in the .prg
    assert res.c_addresses["main"] >= 0x1800
    assert res.prg.with_suffix(".cfg").is_file() and " -C " in res.log
    p.c_areas = [{"name": "MUSIC", "start": 0x0850, "size": 0x800}]
    res = build_project(p)
    assert not res.ok and "Fixed areas" in res.diagnostics[0].message


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_errors_in_the_project_s_own_config(tmp_path):
    from l64s.project.build import build_project
    p = _starfall(tmp_path)
    (p.directory / "game.cfg").write_text(generate([]).replace("CODE:     load = MAIN,", "CODE:     load = MAINX,"))
    p.linker_config = "game.cfg"
    res = build_project(p)
    err = next(d for d in res.diagnostics if d.severity == "error")
    assert not res.ok and err.loc.file.endswith("game.cfg") and "MAINX" in err.message
    line = (p.directory / "game.cfg").read_text().splitlines()[err.loc.line - 1]
    assert "MAINX" in line
    # a config without the runtime's names
    (p.directory / "game.cfg").write_text(generate([]).replace("BSS:      load = BSS,      type = bss, define   = yes;",
                                                               "BSS:      load = BSS,      type = bss;"))
    res = build_project(p)
    assert any("__BSS_RUN__ comes from the linker config" in d.message for d in res.diagnostics)
    p.linker_config = "missing.cfg"
    assert "doesn't exist" in build_project(p).diagnostics[-1].message


# ------------------------------------------------------------------ music in C projects
def test_music_glue_assembles():
    from l64s.sid.cmusic import Tune, glue
    if not shutil.which("ca65"):
        pytest.skip("cc65 isn't installed")
    import tempfile
    for t in (Tune("t", "m.bin", 0x1000, 100, 0x1000, 0x1003, sfx=0x1006, volume=0x1009),
              Tune("t", "m.bin", 0x1000, 100, 0x1000, 0x1003),
              Tune("rsid", "m.bin", 0x1000, 100, 0x1000)):
        with tempfile.TemporaryDirectory() as d:
            files = glue(t)
            (Path(d) / "m.bin").write_bytes(bytes(100))
            (Path(d) / "music.s").write_text(files["music.s"])
            r = subprocess.run(["ca65", "-t", "c64", "music.s"], cwd=d, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr + files["music.s"]
            assert ("music_sfx" in files["music.h"]) == bool(t.sfx)
            assert ("music_start" in files["music.h"]) == bool(t.play)


def test_install_into_a_c_project(tmp_path):
    from l64s.project.model import TOOLCHAIN_CC65, Project
    from l64s.sid.cmusic import InstallError, Tune, install
    p = Project(path=tmp_path / "g.l64proj", name="g", toolchain=TOOLCHAIN_CC65, build_list=["main.c"])
    t = Tune("song", "song.bin", 0x1000, 4450, 0x1000, 0x1003)
    done = install(p, t)
    assert p.c_areas == [{"name": "MUSIC", "start": 0x1000, "size": 0x1200}] and p.build_list == ["main.c", "music.s"]
    assert (tmp_path / "music.s").is_file() and (tmp_path / "music.h").is_file() and len(done) == 4
    install(p, Tune("song", "song.bin", 0x1000, 100, 0x1000, 0x1003))           # again: replaced, not added
    assert p.c_areas == [{"name": "MUSIC", "start": 0x1000, "size": 0x100}] and p.build_list.count("music.s") == 1
    with pytest.raises(InstallError, match="can't go"):
        install(p, Tune("low", "x.bin", 0x0810, 100, 0x0810, 0x0813))
    (tmp_path / "music.h").write_text("/* mine */\n")
    with pytest.raises(InstallError, match="didn't write it"):
        install(p, t)
    p.linker_config = "own.cfg"
    (tmp_path / "music.h").unlink()
    assert "needs an area" in install(p, t)[0]


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_sound_effects_for_c(tmp_path):
    from l64s.sid.goattracker import convert_sfx, find_tool
    if not find_tool("ins2snd2"):
        pytest.skip("GoatTracker's ins2snd2 isn't installed")
    ins = next(iter(sorted(Path.home().glob("gt_songs/*.ins"))), None) or \
        next(iter(sorted((Path(__file__).parent / "fixtures").rglob("*.ins"))), None)
    if ins is None:
        pytest.skip("no GoatTracker instrument to convert")
    data = convert_sfx(ins, tmp_path / "gun.c", "gun", c_project=True)
    assert f"const unsigned char gun[{len(data)}] = {{" in (tmp_path / "gun.c").read_text()
    convert_sfx(ins, tmp_path / "gunsfx.s", "gun", c_project=True)
    assert "        .export _gun" in (tmp_path / "gunsfx.s").read_text()
    (tmp_path / "main.c").write_text("extern const unsigned char gun[];\nint main(void) { return gun[0]; }\n")
    for src in ("gun.c", "gunsfx.s"):
        r = subprocess.run(["cl65", "-t", "c64", "-o", "t.prg", "main.c", src], cwd=tmp_path, capture_output=True,
                           text=True)
        assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_a_song_added_to_a_c_project_follows_its_settings(tmp_path):
    from l64s.project.build import build_project
    from l64s.sid.goattracker import find_tool
    song = Path.home() / "gt_songs" / "hyperspace.sng"
    if not find_tool("gt2reloc") or not song.exists():
        pytest.skip("needs GoatTracker's gt2reloc and a song")
    p = _starfall(tmp_path)
    shutil.copy(song, p.directory)
    p.music = [{"source": "hyperspace.sng", "output": "hyperspace.bin", "address": 0x1000, "sfx": False,
                "c_glue": "music"}]
    res = build_project(p)
    assert res.ok, res.log
    assert "music_sfx" not in (p.directory / "music.h").read_text() and "music.s" in p.build_list
    assert p.c_areas[0]["name"] == "MUSIC" and res.c_addresses["music_start"]
    p.music[0]["sfx"] = True                               # sound effects switched on afterwards
    res = build_project(p)
    assert res.ok and "music_sfx" in (p.directory / "music.h").read_text() and res.c_addresses["music_sfx"]
