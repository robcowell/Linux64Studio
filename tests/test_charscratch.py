"""The character scratch pad."""
import pytest

from l64s.gfx import charscratch
from l64s.gfx.charscratch import CharScratchPad, ListError, parse_list


def test_parse_list():
    assert parse_list("1,2,3,4-10,11,12") == list(range(1, 13))          # CBM prg Studio's example: 12
    assert parse_list("$41-$43, %1, 5-3") == [0x41, 0x42, 0x43, 1, 5, 4, 3]
    for bad in ("", "1,x", "300", "1-256"):
        with pytest.raises(ListError):
            parse_list(bad)


def test_place_list_across_and_down():
    pad = CharScratchPad(4, 3)
    assert pad.place_list(list(range(1, 7)), 2, 0) == 0
    assert pad.cells[0] == [None, None, 1, 2] and pad.cells[1] == [3, 4, 5, 6]
    pad.clear()
    assert pad.place_list([7, 8, 9, 10], 2, 1, across=False) == 0          # down, then the next column
    assert (pad.get(2, 1), pad.get(2, 2), pad.get(3, 0), pad.get(3, 1)) == (7, 8, 9, 10)
    assert pad.place_list([1, 2, 3], 3, 2, across=False) == 2
    assert pad.place_list(list(range(20)), 0, 2) == 16                     # only 4 fit: 16 left over


def test_blocks_shift_and_bounds():
    pad = CharScratchPad(5, 4)
    pad.place_list([1, 2, 3, 4], 1, 1)
    assert pad.bounds() == (1, 1, 4, 1)
    block = pad.copy((1, 1, 2, 1))
    assert block == [[1, 2]]
    pad.paste(block, 0, 3)
    assert pad.cells[3][:2] == [1, 2]
    pad.erase((1, 1, 4, 1))
    assert pad.cells[1] == [None] * 5 and pad.used() == {1, 2}
    pad.shift(-1, 0)
    assert pad.cells[3] == [2, None, None, None, 1]
    pad.shift(0, 1)
    assert pad.cells[0] == [2, None, None, None, 1]
    assert CharScratchPad(2, 2).bounds() is None


def test_resize_and_save():
    pad = CharScratchPad(3, 2)
    pad.set(2, 1, 9)
    back = CharScratchPad.from_dict(pad.to_dict())
    assert back == pad
    pad.resize(5, 1)
    assert pad.cells == [[None] * 5]
    pad.resize(2, 3)
    assert len(pad.cells) == 3 and len(pad.cells[0]) == 2


def test_shared_pad_lives_in_the_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(charscratch, "_shared", None)
    monkeypatch.setattr(charscratch, "selection", None)
    pad = charscratch.shared()
    pad.place_list([65, 66, 67], 2, 2)
    charscratch.save_shared()
    assert (tmp_path / "linux64studio" / "char_scratchpad.json").exists()
    monkeypatch.setattr(charscratch, "_shared", None)
    assert charscratch.shared().get(3, 2) == 66
    assert charscratch.stamp_block() == [[65, 66, 67]]
    monkeypatch.setattr(charscratch, "selection", (3, 2, 1, 1))
    assert charscratch.stamp_block() == [[66]]
