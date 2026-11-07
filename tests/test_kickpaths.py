"""Kick Assembler sources with Windows paths (project.kickpaths), as the Retro Game Dev books write them."""
import shutil
from pathlib import Path

import pytest

from l64s.project.build import build_project, default_kickass_jar
from l64s.project.kickpaths import find, needs_shadow, shadow
from l64s.project.model import TOOLCHAIN_KICKASS, Project


def _book_layout(tmp: Path) -> Path:
    """Vol 1's Kick layout: chapter/code/gameMain.asm importing ../../Library (the folder is library),
    which imports data by a Windows path."""
    (tmp / "library").mkdir()
    (tmp / "Content").mkdir()
    (tmp / "Content" / "Sprites.bin").write_bytes(bytes([1, 2, 3]))
    (tmp / "library" / "libData.asm").write_text('#importonce\nsprites:\n.import binary "..\\Content\\Sprites.bin"\n')
    code = tmp / "chapter" / "code"
    code.mkdir(parents=True)
    main = code / "gameMain.asm"
    main.write_text('*= $c000\n#import "../../Library/libData.asm"\n    lda sprites\n    rts\nbroken:\n')
    return main


def test_a_path_is_found_as_windows_finds_it(tmp_path):
    main = _book_layout(tmp_path)
    lib = (tmp_path / "library" / "libData.asm").resolve()
    assert find("../../Library/libData.asm", [main.parent]) == lib
    assert find("..\\..\\LIBRARY\\libdata.ASM", [main.parent]) == lib
    assert find("..\\Content\\Sprites.bin", [lib.parent]) == (tmp_path / "Content" / "Sprites.bin").resolve()
    assert find("../../Library/nothing.asm", [main.parent]) is None
    assert find("libData.asm", [main.parent, tmp_path / "library"]) == lib       # (a -libdir)


def test_only_sources_that_need_it_are_copied(tmp_path):
    main = _book_layout(tmp_path)
    assert needs_shadow(main, [])
    (tmp_path / "plain.asm").write_text('#import "library/libData.asm"\n')         # (its data still Windows)
    assert needs_shadow(tmp_path / "plain.asm", [])
    (tmp_path / "library" / "libData.asm").write_text('sprites:\n.import binary "../Content/Sprites.bin"\n')
    assert not needs_shadow(tmp_path / "plain.asm", [])
    assert shadow(tmp_path / "plain.asm", [], tmp_path / "copy") is None and not (tmp_path / "copy").exists()


def test_the_copy_has_the_paths_fixed_and_the_lines_where_they_were(tmp_path):
    main = _book_layout(tmp_path)
    s = shadow(main, [], tmp_path / "out" / ".kick-src")
    lib_copy = tmp_path / "out" / ".kick-src" / "library" / "libData.asm"
    assert s.main == (tmp_path / "out" / ".kick-src" / "chapter" / "code" / "gameMain.asm").resolve()
    assert s.main.read_text().splitlines()[1] == '#import "../../library/libData.asm"'
    assert lib_copy.read_text().splitlines()[2] == '.import binary "../Content/Sprites.bin"'
    assert (tmp_path / "out" / ".kick-src" / "Content" / "Sprites.bin").read_bytes() == bytes([1, 2, 3])
    assert s.map(str(lib_copy.resolve())) == str((tmp_path / "library" / "libData.asm").resolve())
    assert s.map(str(s.main)) == str(main.resolve())
    assert main.read_text().splitlines()[1] == '#import "../../Library/libData.asm"'     # (untouched)


@pytest.mark.skipif(not (default_kickass_jar() and shutil.which("java")), reason="Kick Assembler (or Java) isn't installed")
def test_kick_assembler_builds_them_and_its_lines_and_errors_are_the_originals(tmp_path):
    main = _book_layout(tmp_path)
    p = Project(path=tmp_path / "chapter" / "t.l64proj", name="t", toolchain=TOOLCHAIN_KICKASS,
                main_file="code/gameMain.asm")
    res = build_project(p, kickass_jar=default_kickass_jar())
    assert res.ok, res.log
    assert res.prg.read_bytes() == bytes([0x00, 0xC0, 1, 2, 3, 0xAD, 0x00, 0xC0, 0x60])   # (the data, then the code)
    assert res.srcmap[0xC003] == (str(main.resolve()), 3)
    main.write_text(main.read_text().replace("    rts", "    rts\n    jmp nowhere"))
    res = build_project(p, kickass_jar=default_kickass_jar())
    assert not res.ok and res.diagnostics[0].loc.file == str(main.resolve()) and res.diagnostics[0].loc.line == 5
