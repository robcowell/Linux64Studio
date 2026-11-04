"""SID files, and GoatTracker songs and sound effects packed with the GoatTracker GTK edition's tools."""
import os
import struct
from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler
from l64s.sid.goattracker import (MusicError, PackOptions, convert_sfx, find_tool, pack_song, player_code,
                                  read_instrument_name, read_song_info)
from l64s.sid.sidfile import SidError, parse_sid, usage_code

BOOK2 = Path(os.environ.get("L64S_BOOK2", Path(__file__).parent / "book" / "c64editionvol2-main"))
CONTENT = BOOK2 / "Chapters" / "Content"
GT_EXAMPLES = BOOK2 / "Tools" / "goattrk2" / "examples"
needs_book2 = pytest.mark.skipif(not CONTENT.is_dir(), reason="Vol 2 sources not present")
needs_gt = pytest.mark.skipif(not (find_tool("gt2reloc") and find_tool("ins2snd2") and GT_EXAMPLES.is_dir()),
                              reason="GoatTracker tools or example songs not available")


def make_sid(load=0x1000, in_data=True, version=2, body=b"\x4c\x00\x10\x4c\x00\x10", songs=3) -> bytes:
    hdr = b"PSID" + struct.pack(">HHHHHHHI", version, 0x7C if version > 1 else 0x76, 0 if in_data else load,
                                load, (load + 3) & 0xFFFF, songs, 2, 0b10)
    hdr += b"Song".ljust(32, b"\0") + b"Me".ljust(32, b"\0") + b"2026".ljust(32, b"\0")
    if version > 1:
        hdr += struct.pack(">HBBBB", 0b010100, 0, 0, 0, 0)
    return hdr + (bytes([load & 0xFF, load >> 8]) if in_data else b"") + body


def test_parse_sid():
    s = parse_sid(make_sid())
    assert (s.load, s.init, s.play, s.songs, s.start_song) == (0x1000, 0x1000, 0x1003, 3, 2)
    assert (s.name, s.author, s.released) == ("Song", "Me", "2026")
    assert s.data == b"\x4c\x00\x10\x4c\x00\x10" and s.skip == 0x7E and s.end == 0x1006
    assert (s.clock, s.model) == ("PAL", "6581")
    assert s.speed_of(1) == "VBI" and s.speed_of(2) == "CIA"
    s2 = parse_sid(make_sid(in_data=False, version=1))
    assert s2.load == 0x1000 and s2.skip == 0x76 and s2.data[:1] == b"\x4c"


def test_bad_sids():
    with pytest.raises(SidError):
        parse_sid(b"MThd" + bytes(200))
    with pytest.raises(SidError, match="past"):
        parse_sid(make_sid(load=0xFFFE))


def test_usage_code_assembles_and_lands_at_the_load_address(tmp_path):
    s = parse_sid(make_sid())
    (tmp_path / "tune.bin").write_bytes(s.data)
    src = tmp_path / "main.asm"
    src.write_text(usage_code(s, "tune.bin"))
    r = Assembler().assemble_files([src])
    assert r.ok, r.errors
    assert bytes(r.memory[0x1000:0x1006]) == s.data


@needs_book2
@pytest.mark.parametrize("name,songs,author", [("Bahama_Beach.sid", 1, "Kamil Degorski (Djinn)"),
                                                ("Calypso_Bar.sid", 2, "Richard Bayliss")])
def test_book_sids(name, songs, author):
    raw = (CONTENT / name).read_bytes()
    s = parse_sid(raw)
    assert (s.load, s.init, s.play, s.songs, s.author) == (0x1000, 0x1000, 0x1003, songs, author)
    # The book imports them with ".import binary ..., $7E": header plus load address.
    assert s.skip == 0x7E and raw[0x7E:] == s.data
    assert "$7E" in usage_code(s, name, kickass=True)


@needs_book2
def test_l64sid_extract(tmp_path, capsys):
    from l64s.sid.cli import main
    assert main(["extract", str(CONTENT / "Calypso_Bar.sid"), "-o", str(tmp_path / "m.prg")]) == 0
    assert (tmp_path / "m.prg").read_bytes()[:2] == b"\x00\x10"
    assert main(["info", str(CONTENT / "Calypso_Bar.sid")]) == 0
    assert "Richard Bayliss" in capsys.readouterr().out


def test_pack_options():
    o = PackOptions(address=0x2000, zeropage=0xFB, sfx=True, volume=True)
    assert o.args()[:6] == ["-W20", "-ZFB", "-D1", "-E1", "-H1", "-P"]
    assert o.entry_points() == {"init": 0x2000, "play": 0x2003, "sfx": 0x2006, "volume": 0x2009}
    assert PackOptions(volume=True).entry_points()["volume"] == 0x1006
    with pytest.raises(MusicError, match="page"):
        PackOptions(address=0x1080).args()
    assert PackOptions.from_dict(o.to_dict()) == o


@needs_gt
def test_song_and_instrument_headers():
    info = read_song_info(GT_EXAMPLES / "ghosttrackers.sng")
    assert info.format == "GTS5" and info.subtunes >= 1
    assert isinstance(read_instrument_name(GT_EXAMPLES / "sfx_gun.ins"), str)
    with pytest.raises(MusicError):
        read_song_info(GT_EXAMPLES / "sfx_gun.ins")


@needs_gt
@pytest.mark.parametrize("ext", [".bin", ".prg", ".sid"])
def test_pack_song(tmp_path, ext):
    song = tmp_path / "song.sng"
    song.write_bytes((GT_EXAMPLES / "consultant.sng").read_bytes())
    opts = PackOptions(address=0x2000, zeropage=0xFB, sfx=True)
    r = pack_song(song, tmp_path / f"music{ext}", opts)
    data = r.output.read_bytes()
    code = {".bin": data, ".prg": data[2:], ".sid": data[0x7E:]}[ext]
    # The player's jump table: init, play, sound effect
    assert code[0] == 0x4C and code[3] == 0x4C and code[6] == 0x4C
    assert all(0x20 <= code[i + 2] < 0x30 for i in (0, 3, 6))
    if ext == ".prg":
        assert data[:2] == b"\x00\x20"
    if ext == ".sid":
        s = parse_sid(data)
        assert (s.load, s.init, s.play) == (0x2000, 0x2000, 0x2003)
    assert r.start == 0x2000 and r.size > 1000
    assert not list(tmp_path.glob(".l64s-pack*"))          # no temporary files left behind


@needs_gt
def test_missing_song_is_an_error_not_an_empty_song(tmp_path):
    with pytest.raises(MusicError, match="not found"):
        pack_song(tmp_path / "nope.sng", tmp_path / "m.bin", PackOptions())


@needs_gt
def test_sound_effect_conversion(tmp_path):
    raw = convert_sfx(GT_EXAMPLES / "sfx_gun.ins", tmp_path / "gun.bin")
    assert (tmp_path / "gun.bin").read_bytes() == raw and len(raw) > 4
    convert_sfx(GT_EXAMPLES / "sfx_gun.ins", tmp_path / "gun.asm", "gunSound")
    r = Assembler().assemble_text("*=$c000\n" + (tmp_path / "gun.asm").read_text(), str(tmp_path / "t.asm"))
    assert r.ok and r.binary() == raw and r.symbols["gunsound"] == 0xC000
    convert_sfx(GT_EXAMPLES / "sfx_gun.ins", tmp_path / "gun.s", "gun", kickass=True)
    assert (tmp_path / "gun.s").read_text().splitlines()[1] == "gun:"


@needs_gt
def test_project_packs_music_before_assembling(tmp_path):
    """The program incbins music.bin, which only exists once the build has packed the song."""
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "tune.sng").write_bytes((GT_EXAMPLES / "consultant.sng").read_bytes())
    (tmp_path / "gun.ins").write_bytes((GT_EXAMPLES / "sfx_gun.ins").read_bytes())
    opts = PackOptions(address=0x1000, sfx=True)
    main = ("*=$0801\n byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00\n lda #0\n jsr $1000\n rts\n"
            + player_code("music.bin", opts, ".bin").split("; Once")[0].replace("*=$1000", "*=$1000") + "\n"
            + "*=$c000\n incasm \"gun.asm\"\n")
    (tmp_path / "main.asm").write_text(main)
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.asm"], executable="t.prg",
                   music=[{"source": "tune.sng", "output": "music.bin", **opts.to_dict()},
                          {"source": "gun.ins", "output": "gun.asm", "label": "gun"}])
    res = build_project(proj)
    assert res.ok, res.log
    assert "Packed tune.sng -> music.bin ($1000-" in res.log and "Sound effect gun.ins -> gun.asm" in res.log
    a = res.asm_result
    assert a.memory[0x1000] == 0x4C and a.memory[0x1006] == 0x4C and a.symbols["gun"] == 0xC000


@needs_gt
def test_project_music_errors_stop_the_build(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.asm").write_text("*=$0801\n rts\n")
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.asm"], executable="t.prg",
                   music=[{"source": "missing.sng", "output": "music.bin"}])
    res = build_project(proj)
    assert not res.ok and "missing.sng not found" in res.diagnostics[0].message
