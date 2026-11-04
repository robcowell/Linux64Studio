"""The sprite scratch pad."""
from l64s.gfx.scratchpad import Placement, ScratchPad
from l64s.gfx.sprite import Sprite


def hires(points, colour=1):
    s = Sprite(colour=colour)
    for x, y in points:
        s.set(x, y, 1)
    return s


def test_side_by_side_and_layers():
    a, b = hires([(0, 0), (23, 20)], colour=2), hires([(0, 0), (5, 5)], colour=7)
    pad = ScratchPad(2, 1)
    pad.place(0, 0, 0)
    pad.place(1, 0, 1)
    img = pad.render([a, b], background=6, mc1=0, mc2=0)
    assert len(img) == 21 and len(img[0]) == 48
    assert img[0][0] == 2 and img[20][23] == 2 and img[0][24] == 7 and img[5][29] == 7 and img[1][1] == 6
    pad.place(0, 0, 1)                                   # on top of a in the first cell
    img = pad.render([a, b], 6, 0, 0)
    assert img[0][0] == 7 and img[5][5] == 7 and img[20][23] == 2      # b drawn over a; a still shows
    pad.raise_(0, 0, 1, -1)                              # b under a now
    assert pad.render([a, b], 6, 0, 0)[0][0] == 2


def test_offsets_flips_and_invert():
    s = hires([(0, 0)], colour=1)
    pad = ScratchPad(2, 2)
    p = pad.place(0, 0, 0)
    p.dx, p.dy = 3, 2
    assert pad.render([s], 0, 0, 0)[2][3] == 1
    p.dx, p.dy = 26, 0                                   # past the edge: into the next cell
    assert pad.render([s], 0, 0, 0)[0][26] == 1
    p.dx = p.dy = 0
    p.flip_x = True
    assert pad.render([s], 0, 0, 0)[0][23] == 1
    p.flip_y = True
    assert pad.render([s], 0, 0, 0)[20][23] == 1
    q = pad.place(1, 1, 0)
    q.invert = True
    img = pad.render([s], 0, 0, 0)
    assert img[21][24] == 0 and img[21][25] == 1 and img[41][47] == 1
    assert s.rows[0] == 0x800000                         # the sprite itself is unchanged


def test_multicolour():
    s = Sprite(multi=True, colour=5)
    s.set(0, 0, 1)
    s.set(1, 0, 2)
    s.set(11, 0, 3)
    pad = ScratchPad(1, 1)
    p = pad.place(0, 0, 0)
    row = pad.render([s], 6, 10, 12)[0]
    assert row[:4] == [10, 10, 5, 5] and row[22:] == [12, 12] and row[4] == 6
    p.flip_x = True
    row = pad.render([s], 6, 10, 12)[0]
    assert row[:2] == [12, 12] and row[20:] == [5, 5, 10, 10]
    p.flip_x, p.invert = False, True
    row = pad.render([s], 6, 10, 12)[0]
    assert row[:4] == [5, 5, 10, 10] and row[4] == 12 and row[22:] == [6, 6]


def test_sprites_moving_in_the_set():
    pad = ScratchPad()
    pad.place(0, 0, 0)
    pad.place(1, 0, 2)
    pad.place(1, 0, 3)
    pad.sprites_inserted(1)                              # a sprite added before 2 and 3
    assert [p.sprite for p in pad.stack(1, 0)] == [3, 4]
    pad.sprite_removed(3)
    assert [p.sprite for p in pad.stack(1, 0)] == [3]
    pad.sprite_removed(0)
    assert pad.stack(0, 0) == [] and (0, 0) not in pad.cells
    assert pad.render([Sprite()], 0, 0, 0)               # indices out of range are skipped


def test_save_and_resize():
    pad = ScratchPad(4, 3)
    pad.place(3, 2, 1).invert = True
    pad.place(0, 0, 0)
    back = ScratchPad.from_dict(pad.to_dict())
    assert back == pad and back.stack(3, 2) == [Placement(1, invert=True)]
    pad.resize(2, 2)
    assert list(pad.cells) == [(0, 0)]
    assert Placement(4, -3, 2, True).describe() == "Sprite 4, moved -3, +2, flipped across"
