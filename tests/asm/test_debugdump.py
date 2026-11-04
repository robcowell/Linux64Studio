"""The debug dump (.dbg) the built-in assembler writes, in Kick Assembler 5's format."""
import shutil
import subprocess
from pathlib import Path

import pytest

from l64s import kickdbg
from l64s.asm.assembler import Assembler, Options
from l64s.asm.output import debug_dump

BOOK = Path(__file__).resolve().parents[1] / "book" / "c64edition-main"

# the same program in both dialects: only the first line differs
PROGRAM = """start:  ldx #0
loop:   inx
        stx $0400
        jmp loop
"""


def _jar() -> Path | None:
    jar = Path.home() / ".local/share/linux64studio/KickAssembler/KickAss.jar"
    return jar if jar.exists() and shutil.which("java") else None


def _section(text: str, tag: str) -> list[str]:
    body = text.split(f"<{tag}", 1)[1].split(f"</{tag.split()[0]}>", 1)[0]
    return [ln.strip() for ln in body.splitlines()[1:] if ln.strip()]


@pytest.mark.skipif(_jar() is None, reason="needs Kick Assembler 5 (tools/install-kickassembler.sh) and java")
def test_same_as_kick_assemblers(tmp_path):
    kick = tmp_path / "kick" / "t.asm"
    kick.parent.mkdir()
    kick.write_text("*=$0810\n" + PROGRAM)
    subprocess.run(["java", "-jar", str(_jar()), kick.name, "-debugdump"], cwd=kick.parent, check=True,
                   capture_output=True)
    theirs = (kick.parent / "t.dbg").read_text()
    cbm = tmp_path / "cbm" / "t.asm"
    cbm.parent.mkdir()
    cbm.write_text("*=$0810\n" + PROGRAM)
    ours = debug_dump(Assembler(Options()).assemble_files([cbm]))
    # Kick Assembler numbers its autoinclude 0 and the source 1; ours has no autoinclude
    their_rows = [r for r in _section(theirs, "Block name=\"Unnamed\"")]
    our_rows = _section(ours, "Block")
    assert [r.split(",")[:2] + r.split(",")[3:] for r in our_rows] == \
        [r.split(",")[:2] + r.split(",")[3:] for r in their_rows]
    their_labels = [r for r in _section(theirs, "Labels") if ",1," in r]
    assert [r.replace(",0,", ",1,", 1) for r in _section(ours, "Labels")] == their_labels
    assert ours.splitlines()[0] == theirs.splitlines()[0]


def test_read_back(tmp_path):
    (tmp_path / "main.asm").write_text(
        "*=$c000\nstart   lda #1\n        mymac 2\n        jmp start\ntable   byte 1,2,3\n"
        "        breakpoint start A == 1\n        watch table\n")
    (tmp_path / "macros.asm").write_text("        defm mymac\n        ldx #/1\n        endm\n")
    r = Assembler(Options()).assemble_files([tmp_path / "main.asm", tmp_path / "macros.asm"])
    assert r.ok, [str(d) for d in r.diagnostics]
    dbg = tmp_path / "t.dbg"
    dbg.write_text(debug_dump(r))
    info = kickdbg.parse(dbg)
    main, macros = str((tmp_path / "main.asm").resolve()), str((tmp_path / "macros.asm").resolve())
    got = [(e.start, e.end, e.file, e.line) for e in info.entries]
    assert got == [(0xC000, 0xC001, main, 2), (0xC002, 0xC003, macros, 2),   # in a macro: the macro's line
                   (0xC004, 0xC006, main, 4), (0xC007, 0xC009, main, 5)]
    assert info.labels == [(0xC000, "start", main, 2), (0xC007, "table", main, 5)]
    text = dbg.read_text()
    assert _section(text, "Breakpoints") == ["Default,$c000,A == $1"]
    assert _section(text, "Watchpoints") == ["Default,$c007,,"]


def test_file_local_labels_keep_their_names(tmp_path):
    (tmp_path / "a.asm").write_text("*=$c000\nloop    jmp loop\n")
    (tmp_path / "b.asm").write_text("loop    jmp loop\n")
    r = Assembler(Options()).assemble_files([tmp_path / "a.asm", tmp_path / "b.asm"])
    dbg = tmp_path / "t.dbg"
    dbg.write_text(debug_dump(r))
    assert [(a, n, Path(f).name) for a, n, f, _l in kickdbg.parse(dbg).labels] == \
        [(0xC000, "loop", "a.asm"), (0xC003, "loop", "b.asm")]


@pytest.mark.skipif(not BOOK.exists(), reason="book downloads not in tests/book")
def test_book_chapter_maps_every_byte(tmp_path):
    from l64s.project.model import load_project
    proj = load_project(next(BOOK.rglob("*17*.cbmprj")))
    r = Assembler(Options()).assemble_files(proj.build_paths())
    dbg = tmp_path / "t.dbg"
    dbg.write_text(debug_dump(r))
    m = kickdbg.source_map(kickdbg.parse(dbg))
    for e in r.listing:
        for i in range(len(e.data)):
            assert m[e.address + i] == (str(Path(e.loc.file).resolve()), e.loc.line)


def test_cli_and_project(tmp_path):
    from l64s.asm.cli import main
    from l64s.project.build import build_project
    from l64s.project.model import Project
    src = tmp_path / "m.asm"
    src.write_text("*=$c000\nstart   rts\n")
    assert main([str(src), "--debugdump", "-q"]) == 0
    assert kickdbg.parse(tmp_path / "m.dbg").labels[0][:2] == (0xC000, "start")
    assert main([str(src), "--debugdump", str(tmp_path / "x.dbg"), "-q"]) == 0 and (tmp_path / "x.dbg").exists()
    p = Project(path=tmp_path / "t.l64proj", name="t", build_list=["m.asm"], executable="t.prg")
    build_project(p)
    assert not (tmp_path / "t.dbg").exists()
    p.debug_dump = True
    res = build_project(p)
    assert (tmp_path / "t.dbg").exists() and "t.dbg" in res.log
