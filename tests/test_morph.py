import pytest

from l64s.gfx.morph import EASINGS, ORDERS, morph
from l64s.gfx.sprite import HEIGHT, Sprite


def solid(value=0xFFFFFF, **kw):
    return Sprite(rows=[value] * HEIGHT, **kw)


def ones(s: Sprite) -> int:
    return sum(bin(r).count("1") for r in s.rows)


def test_first_and_last_are_the_sprites():
    a, b = solid(0), solid()
    frames = morph(a, b, 5)
    assert len(frames) == 5
    assert frames[0].rows == a.rows and frames[-1].rows == b.rows


def test_linear_switches_evenly():
    frames = morph(solid(0), solid(), 5)
    assert [ones(f) for f in frames] == [0, 126, 252, 378, 504]


@pytest.mark.parametrize("easing", list(EASINGS))
def test_easings_are_monotonic(easing):
    counts = [ones(f) for f in morph(solid(0), solid(), 9, easing)]
    assert counts == sorted(counts) and counts[0] == 0 and counts[-1] == 504
    if easing in ("quadratic", "cubic"):
        assert counts[4] < 252                  # slow at the start
    if easing == "sine":
        assert counts[4] == 252                 # symmetrical


def test_only_differing_pixels_change():
    a = solid(0xF0F0F0)
    b = solid(0x0F0F0F)
    for f in morph(a, b, 6):
        for ra, rb, rf in zip(a.rows, b.rows, f.rows):
            # each bit is either the start's or the end's
            assert rf & ~(ra | rb) == 0 and ~rf & (ra & rb) == 0


def test_dissolve_is_repeatable_and_seeded():
    a, b = solid(0), solid()
    assert morph(a, b, 4)[1].rows == morph(a, b, 4)[1].rows
    assert morph(a, b, 4, seed=1)[1].rows != morph(a, b, 4, seed=2)[1].rows


@pytest.mark.parametrize("order", ORDERS)
def test_orders(order):
    frames = morph(solid(0), solid(), 3, order=order)
    assert ones(frames[1]) == 252
    if order == "top to bottom":
        assert frames[1].rows[:10] == [0xFFFFFF] * 10 and frames[1].rows[11:] == [0] * 10
    if order == "left to right":
        assert all(r == 0xFFF000 for r in frames[1].rows)


def test_multicolour_uses_the_start_sprites_mode():
    a = Sprite(multi=True, colour=5)
    b = Sprite(rows=[0b01] * HEIGHT, multi=False)        # read as multicolour: the last pixel pair is 01
    frames = morph(a, b, 2)
    assert all(f.multi and f.colour == 5 for f in frames)
    assert frames[-1].get(11, 0) == 1


def test_bad_frames():
    with pytest.raises(ValueError):
        morph(solid(), solid(0), 1)
