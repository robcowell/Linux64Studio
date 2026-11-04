"""Screen designer paths."""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from l64s.basic.tokenizer import tokenize
from l64s.gfx.paths import (GenOptions, PathError, ScreenPath, function_points, generate, interpolate, parse_point,
                            to_cells, transform)
from l64s.gfx.screen import ScreenSet

BOOK = Path(__file__).resolve().parent / "book" / "c64edition-main"


def test_editing():
    p = ScreenPath([(0, 0), (10, 0)])
    assert p.insert_after(0) == 1 and p.points == [(0, 0), (5, 0), (10, 0)]
    p.move(1, (5, 6))
    p.subdivide()
    assert p.points == [(0, 0), (2, 3), (5, 6), (7, 3), (10, 0)]
    assert p.nearest((6, 5), 3) == 2 and p.nearest((50, 50), 3) is None
    p.delete(0)
    assert p.lines == 3


def test_interpolate():
    p = ScreenPath([(0, 0), (4, 0), (4, 8)])
    assert interpolate(p) == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (4, 1), (4, 2), (4, 3), (4, 4), (4, 5),
                              (4, 6), (4, 7), (4, 8)]
    assert interpolate(p, step=4) == [(0, 0), (4, 0), (4, 4), (4, 8)]
    assert interpolate(p, step=2, first=2) == [(4, 0), (4, 2), (4, 4), (4, 6), (4, 8)]
    assert interpolate(p, first=1, last=1) == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
    assert interpolate(p, only_points=True) == p.points
    assert interpolate(ScreenPath([(0, 0), (3, 6)]), 3) == [(0, 0), (2, 3), (3, 6)]   # diagonal: the longer axis
    with pytest.raises(PathError):
        interpolate(p, first=3, last=2)


def test_transform():
    pts = [(0, 0), (10, 20)]
    assert transform(pts, "x+24", "y+50") == [(24, 50), (34, 70)]                 # screen to sprite pixels
    assert transform(pts, "x*2", "(y+5)/2") == [(0, 3), (20, 13)]
    assert transform(pts, "5", "y") == [(5, 0), (5, 20)]                        # CBM's "straight line"
    with pytest.raises(PathError):
        transform(pts, "x+5*y")                                                   # x only uses x


def test_function_and_cells():
    pts = function_points("-sin(x/20)*50+100", 0, 40, 10)
    assert pts == [(0, 100), (10, 76), (20, 58), (30, 50), (40, 55)]
    with pytest.raises(PathError):
        function_points("5", 0, 10)
    assert to_cells(ScreenPath([(0, 0), (20, 0), (20, 9)]), 40, 25) == [(0, 0), (1, 0), (2, 0), (2, 1)]


def test_generate_assembler():
    p = ScreenPath([(0, 0), (16, 0), (16, 8)])
    text, warn = generate(p, GenOptions(step=8))
    assert text.splitlines() == ["; path: 4 points, every 8 pixels (x, y pairs)", "path",
                                 "        byte $00, $00, $08, $00, $10, $00, $10, $08", "; 4 points, 8 bytes"]
    assert not warn
    text, _ = generate(p, GenOptions(step=8, separate=True, kickass=True, comments=False, fx="x+24"))
    assert text.splitlines() == ["path_x:", "    .byte $18, $20, $28, $28", "path_y:", "    .byte $00, $00, $00, $08"]
    _, warn = generate(p, GenOptions(fx="x+250"))
    assert warn and "outside a byte" in warn[0]
    text, warn = generate(p, GenOptions(output="words", only_points=True, fx="x+250", comments=False))
    assert "word $00FA, $0000, $010A" in text and not warn
    with pytest.raises(PathError):
        generate(ScreenPath(), GenOptions())


def test_generate_basic():
    p = ScreenPath([(0, 0), (16, 0), (16, 8)])
    text, _ = generate(p, GenOptions(output="basic", step=4, per_line=3, basic_start=500, basic_step=5))
    lines = text.splitlines()
    assert lines[0] == "500 rem path: 7 points, every 4 pixels (x, y pairs)"
    assert lines[1] == "505 data 0,0,4,0,8,0" and lines[-1] == "515 data 16,8"
    tokenize(text)


def test_sdd_round_trip(tmp_path):
    ss = ScreenSet()
    ss.screens[0].path.points = [(10, 20), (100, 20), (100, 150)]
    ss.save_sdd(tmp_path / "s.sdd")
    back = ScreenSet.load_sdd(tmp_path / "s.sdd")
    assert back.screens[0].path.points == [(10, 20), (100, 20), (100, 150)]
    for xml in ("<Point>3,4</Point>", "<Point>{X=3,Y=4}</Point>", "<Point><X>3</X><Y>4</Y></Point>",
                '<Point X="3" Y="4"/>'):
        assert parse_point(ET.fromstring(xml)) == (3, 4)


@pytest.mark.skipif(not BOOK.exists(), reason="book downloads not in tests/book")
def test_book_screens_keep_their_empty_paths(tmp_path):
    f = BOOK / "Chapters" / "chapter17" / "screens.sdd"
    ss = ScreenSet.load_sdd(f)
    assert all(s.path.points == [] for s in ss.screens)
    ss.save_sdd(tmp_path / "s.sdd")
    for pel in ET.parse(tmp_path / "s.sdd").getroot().findall("./Screens/Screen/Path"):
        assert pel.findtext("Width") == "0" and pel.find("Points") is not None and not pel.findall("./Points/Point")
