import os
from pathlib import Path

import pytest

from l64s import memmap
from l64s.asm.assembler import Assembler

BOOK = Path(os.environ.get("L64S_BOOK", Path(__file__).parent / "book" / "c64edition-main"))
CH17 = BOOK / "Chapters" / "chapter17"


def build(tmp_path, files: dict[str, str | bytes]):
    for name, content in files.items():
        p = tmp_path / name
        p.write_bytes(content) if isinstance(content, bytes) else p.write_text(content)
    r = Assembler().assemble_files([tmp_path / n for n in files if n.endswith(".asm")])
    assert r.ok, r.errors
    return memmap.from_build(r)


@pytest.mark.skipif(not CH17.is_dir(), reason="book sources not present")
def test_chapter17_layout():
    from l64s.project.model import load_project
    r = Assembler().assemble_files(load_project(CH17 / "chapter17.cbmprj").build_paths())
    m = memmap.from_build(r)
    first = m.segments[0]
    assert (first.start, first.end, first.owner, first.kind) == (0x0801, 0x080F, "gameMain.asm", "data")
    binaries = [(s.start, s.end) for s in m.segments if s.kind == "binary"]
    assert binaries == [(0x1F20, 0x2E1F), (0x3000, 0x36FF), (0x3800, 0x3B1F)]
    assert m.total == sum(s.size for s in m.segments) == sum(r.used)
    # macro code belongs to the file that used the macro, not the library that defines it
    assert m.owner_of(0x0888).owner == "gameMain.asm"
    assert (0x2E20, 0x2FFF) in m.free_ranges()
    assert m.owner_of(0x3000).lines[0][0].endswith("gameMemory.asm")


def test_segments_by_file_and_kind(tmp_path):
    m = build(tmp_path, {"a.asm": "*=$c000\n lda #1\n rts\ntable byte 1,2,3\n text 'hi'\n incbin pic.bin\n",
                         "pic.bin": bytes(10)})
    assert [(s.start, s.end, s.kind) for s in m.segments] == [(0xC000, 0xC002, "code"), (0xC003, 0xC007, "data"),
                                                            (0xC008, 0xC011, "binary")]


@pytest.mark.parametrize("src,needle", [
    ("*=$00fb\n byte 1", "zero page"),
    ("*=$0340\n rts", "work area"),
    ("*=$0400\n byte 1", "screen memory"),
    ("*=$d000\n byte 1", "I/O"),
    ("*=$a000\n rts", "BASIC ROM"),
    ("*=$e000\n rts", "KERNAL ROM"),
    ("*=$1800\n incbin g.bin", "character ROM"),
    ("*=$9000\n incbin g.bin", "character ROM"),
])
def test_warnings(tmp_path, src, needle):
    m = build(tmp_path, {"m.asm": src, "g.bin": bytes(64)})
    assert any(needle in w.message for w in memmap.warnings(m)), [w.message for w in memmap.warnings(m)]


def test_no_warnings_for_a_tidy_program(tmp_path):
    m = build(tmp_path, {"m.asm": "*=$0801\n byte 0,0\n*=$1000\n rts\n*=$a000\n byte 1\n*=$3000\n incbin g.bin",
                         "g.bin": bytes(64)})
    assert memmap.warnings(m) == []      # data under the BASIC ROM is fine (the VIC-II sees RAM there)


def test_no_graphics_warning_for_the_project_s_music(tmp_path):
    m = build(tmp_path, {"m.asm": "*=$1000\n incbin music.bin\n*=$1800\n incbin g.bin",
                         "music.bin": bytes(64), "g.bin": bytes(64)})
    memmap.mark_music(m, ["Music.bin"])
    assert [s.music for s in m.segments] == [True, False]
    msgs = [w.message for w in memmap.warnings(m)]
    assert len(msgs) == 1 and "g.bin" not in msgs[0] and "$1800" in msgs[0]     # only the graphics


def test_two_files_writing_the_same_bytes(tmp_path):
    (tmp_path / "a.asm").write_text("*=$c000\n byte 1,2,3\n")
    (tmp_path / "b.asm").write_text("*=$c001\n byte 9\n")
    r = Assembler().assemble_files([tmp_path / "a.asm", tmp_path / "b.asm"])
    m = memmap.from_build(r)
    assert any("both a.asm and b.asm" in w.message for w in memmap.warnings(m))


def test_from_prg_and_free_ranges():
    m = memmap.from_prg(b"\x00\xc0" + bytes(100), "game.prg")
    assert [(s.start, s.end, s.owner) for s in m.segments] == [(0xC000, 0xC063, "game.prg")]
    free = m.free_ranges()
    assert free[0] == (0x0801, 0xBFFF) and free[1] == (0xC064, 0xFFFF)
    assert memmap.system_region(0xD020).startswith("I/O")
    assert memmap.from_memory(bytes(0x10000)).segments == []
