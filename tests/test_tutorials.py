import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from l64s import mdview
from l64s.transcript import parse as parse_transcript

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples" / "tutorials"
HAVE_CC65 = shutil.which("cl65") is not None


def test_reading_markdown():
    blocks = mdview.parse("# Title\n\nSome **bold**, `code` and [a link](2-x.md), *italic*.\n\n"
                          "1. First\n   carried on\n2. Second\n\n* a bullet\n\n```\nlda #0\n\nrts\n```\n\n"
                          "![A picture](img/p.png)\n<!-- example: 2-assembler -->\n")
    assert [b.kind for b in blocks] == ["heading", "para", "number", "number", "bullet", "code", "image"]
    assert [(r.text, r.style) for r in blocks[1].runs] == [
        ("Some ", ""), ("bold", "bold"), (", ", ""), ("code", "code"), (" and ", ""), ("a link", "link"),
        (", ", ""), ("italic", "italic"), (".", "")]
    assert blocks[1].runs[5].url == "2-x.md"
    assert blocks[2].level == 1 and blocks[2].runs[0].text == "First carried on"
    assert blocks[5].text == "lda #0\n\nrts"
    assert (blocks[6].text, blocks[6].url) == ("A picture", "img/p.png")
    assert mdview.example_of("<!-- example: 2-assembler -->") == "2-assembler"


def test_the_tutorials_hang_together():
    files = mdview.tutorials()
    assert files[0].name == "README.md" and len(files) == 6
    for f in files:
        text = f.read_text()
        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):        # every picture is there
            assert (f.parent / m.group(1)).is_file(), (f.name, m.group(1))
        for m in re.finditer(r"(?<!!)\[[^\]]*\]\(([^)#]+)(#[^)]*)?\)", text):   # every link to a file
            if not m.group(1).startswith("http"):
                assert (f.parent / m.group(1)).is_file(), (f.name, m.group(1))
        example = mdview.example_of(text)
        if f.name != "README.md":
            assert example and (EXAMPLES / example).is_dir(), f.name


def _projects():
    return sorted(EXAMPLES.glob("*/*.l64proj"))


@pytest.mark.parametrize("project", _projects(), ids=lambda p: p.parent.name)
def test_each_example_builds(project, tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import load_project
    if project.parent.name == "5-c" and not HAVE_CC65:
        pytest.skip("cc65 isn't installed")
    shutil.copytree(project.parent, tmp_path / "p")
    res = build_project(load_project(tmp_path / "p" / project.name))
    assert res.ok, res.log
    assert parse_transcript((project.parent / "tests.transcript").read_text())


def _vice_ok():
    return os.environ.get("L64S_VICE_TESTS") == "1" and shutil.which("x64sc")


@pytest.mark.skipif(not _vice_ok(), reason="set L64S_VICE_TESTS=1 (with VICE) to run VICE")
@pytest.mark.parametrize("project", _projects(), ids=lambda p: p.parent.name)
def test_each_examples_transcript_passes(project, tmp_path):
    """What the tutorials say each program does, checked in VICE."""
    if project.parent.name == "5-c" and not HAVE_CC65:
        pytest.skip("cc65 isn't installed")
    shutil.copytree(project.parent, tmp_path / "p")
    out = subprocess.run([sys.executable, "-m", "l64s.transcript", str(tmp_path / "p" / project.name),
                          str(tmp_path / "p" / "tests.transcript"), "--vice-args=-sounddev dummy"],
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0 and " 0 failed" in out.stdout, out.stdout
