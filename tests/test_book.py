"""Retro Game Dev C64 Edition, Vol 1: every chapter must assemble byte-for-byte to the shipped .prg,
and so must its Kick Assembler versions; Vol 2's chapters must build with Kick Assembler.

Point L64S_BOOK at the unzipped c64edition-main folder (L64S_BOOK2 at c64editionvol2-main), or unzip
them into tests/book/.
"""
import os
import shutil
from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler
from l64s.project.build import build_project, default_kickass_jar
from l64s.project.model import load_project

BOOK = Path(os.environ.get("L64S_BOOK", Path(__file__).parent / "book" / "c64edition-main"))
BOOK2 = Path(os.environ.get("L64S_BOOK2", Path(__file__).parent / "book" / "c64editionvol2-main"))

needs_book = pytest.mark.skipif(not (BOOK / "Chapters").is_dir(), reason=f"book sources not found at {BOOK}")
needs_book2 = pytest.mark.skipif(not (BOOK2 / "Chapters").is_dir(), reason=f"Vol 2's sources not found at {BOOK2}")
needs_kick = pytest.mark.skipif(not (default_kickass_jar() and shutil.which("java")),
                                reason="Kick Assembler (or Java) isn't installed")


@needs_book
@pytest.mark.parametrize("chapter", range(6, 18))
def test_chapter_matches_shipped_prg(chapter):
    proj = load_project(BOOK / "Chapters" / f"chapter{chapter}" / f"chapter{chapter}.cbmprj")
    result = Assembler().assemble_files(proj.build_paths())
    assert result.ok, "\n".join(map(str, result.errors[:10]))
    gold = (BOOK / "prgs" / f"chapter{chapter}.prg").read_bytes()
    assert result.prg() == gold


def _kick_build(folder: Path, tmp_path: Path):
    """Build a copy of a book's Kick Assembler chapters folder's chapter (its sources import
    ../../Library and ../../Content by Windows paths: project.kickpaths)."""
    shutil.copytree(folder.parent, tmp_path / "book")
    workspace = next((tmp_path / "book" / folder.name).glob("*.code-workspace"))
    res = build_project(load_project(workspace), kickass_jar=default_kickass_jar())
    assert res.ok, res.log
    return res.prg.read_bytes()


@needs_book
@needs_kick
@pytest.mark.parametrize("chapter", range(6, 18))
def test_kick_assembler_chapter_matches_shipped_prg(chapter, tmp_path):
    folder = BOOK / "ChaptersKickAss" / f"chapter{chapter}"
    assert _kick_build(folder, tmp_path) == (BOOK / "ChaptersKickAss" / "prgs" / f"chapter{chapter}.prg").read_bytes()


@needs_book2
@needs_kick
@pytest.mark.parametrize("chapter", [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13])
def test_vol2_chapter_builds(chapter, tmp_path):
    """Chapters 1-3 match the shipped .prgs. The others were shipped built from an older Library (its
    LIBMATH_MAX16BIT_AV, for one, made different code), so they're only built."""
    prg = _kick_build(BOOK2 / "Chapters" / f"Chapter{chapter}", tmp_path)
    if chapter <= 3:
        assert prg == (BOOK2 / "prgs" / f"chapter{chapter}.prg").read_bytes()
