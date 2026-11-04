"""Retro Game Dev C64 Edition, Vol 1: every chapter must assemble byte-for-byte to the shipped .prg.

Point L64S_BOOK at the unzipped c64edition-main folder, or unzip it into tests/book/.
"""
import os
from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler
from l64s.project.model import load_project

BOOK = Path(os.environ.get("L64S_BOOK", Path(__file__).parent / "book" / "c64edition-main"))

pytestmark = pytest.mark.skipif(not (BOOK / "Chapters").is_dir(), reason=f"book sources not found at {BOOK}")


@pytest.mark.parametrize("chapter", range(6, 18))
def test_chapter_matches_shipped_prg(chapter):
    proj = load_project(BOOK / "Chapters" / f"chapter{chapter}" / f"chapter{chapter}.cbmprj")
    result = Assembler().assemble_files(proj.build_paths())
    assert result.ok, "\n".join(map(str, result.errors[:10]))
    gold = (BOOK / "prgs" / f"chapter{chapter}.prg").read_bytes()
    assert result.prg() == gold
