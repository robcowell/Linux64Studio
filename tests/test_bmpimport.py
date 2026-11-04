"""Importing sprites from an image (CBM prg Studio's Import From Bitmap)."""
import random
import struct

import gi
import pytest

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

from l64s.gfx.bmpimport import (PALETTE, Image, ImageError, Options, cells, guess_colours,  # noqa: E402
                                import_sprites, load_image, nearest_c64)
from l64s.gfx.sprite import Sprite  # noqa: E402

INK, PAPER = (20, 20, 20), (240, 240, 230)
MC = [(0, 0, 0), (200, 80, 60), (90, 180, 70), (70, 60, 180)]     # background, MC1, sprite colour, MC2


def random_sprite(rng, multi=False):
    s = Sprite(multi=multi)
    for y in range(21):
        for x in range(s.pixel_width):
            s.set(x, y, rng.randrange(4 if multi else 2))
    return s


def sheet(sprites, per_row, scale=1, gap=0, x0=0, y0=0, multi=False, fill=PAPER):
    """Draw sprites into an image the way an artist's sprite sheet looks."""
    cw, ch = 24 * scale, 21 * scale
    rows_n = (len(sprites) + per_row - 1) // per_row
    w, h = x0 + per_row * (cw + gap), y0 + rows_n * (ch + gap)
    img = [[fill] * w for _ in range(h)]
    for n, s in enumerate(sprites):
        ox, oy = x0 + (n % per_row) * (cw + gap), y0 + (n // per_row) * (ch + gap)
        for y in range(21):
            for x in range(24):
                v = s.get(x // 2, y) if multi else s.get(x, y)
                c = MC[v] if multi else (INK if v else PAPER)
                for dy in range(scale):
                    for dx in range(scale):
                        img[oy + y * scale + dy][ox + x * scale + dx] = c
    return Image.from_rows(img)


def test_hires_round_trip():
    rng = random.Random(1)
    sprites = [random_sprite(rng) for _ in range(5)]
    img = sheet(sprites, 3, scale=2, gap=3, x0=4, y0=1)
    r = import_sprites(img, Options(x=4, y=1, gap_x=3, gap_y=3, scale=2))
    assert [s.rows for s in r.sprites] == [s.rows for s in sprites] + [[0] * 21]   # the empty sixth cell
    assert r.cells[1] == (4 + 51, 1)
    r = import_sprites(img, Options(x=4, y=1, gap_x=3, gap_y=3, scale=2, skip_empty=True))
    assert len(r.sprites) == 5 and r.colour == nearest_c64(INK) == 0
    assert len(import_sprites(img, Options(x=4, y=1, gap_x=3, gap_y=3, scale=2, count=2)).sprites) == 2
    col = import_sprites(img, Options(x=4, y=1, gap_x=3, gap_y=3, scale=2, column_first=True)).sprites
    assert col[1].rows == sprites[3].rows                       # down the first column first


def test_light_on_dark():
    rng = random.Random(2)
    s = random_sprite(rng)
    img = sheet([s], 1, fill=INK)
    # drawn light on dark: swap ink and paper
    data = bytearray(img.pixels)
    for i in range(0, len(data), 4):
        data[i:i + 3] = bytes(PAPER) if tuple(data[i:i + 3]) == INK else bytes(INK)
    img = Image(img.width, img.height, bytes(data))
    assert import_sprites(img, Options(light_on=True)).sprites[0].rows == s.rows
    assert import_sprites(img, Options()).sprites[0].rows != s.rows


def test_multicolour_round_trip():
    rng = random.Random(3)
    sprites = [random_sprite(rng, multi=True) for _ in range(3)]
    img = sheet(sprites, 3, scale=1, multi=True, fill=MC[0])
    guess = guess_colours(img, Options(multi=True))
    assert guess[0] == MC[0] and set(guess[1:]) == set(MC[1:])
    r = import_sprites(img, Options(multi=True, colours=list(MC)))
    assert [s.rows for s in r.sprites] == [s.rows for s in sprites] and r.sprites[0].multi
    assert (r.colour, r.mcolour1, r.mcolour2) == tuple(nearest_c64(MC[i]) for i in (2, 1, 3))
    # slightly off colours (a JPEG, a screenshot) still match within the tolerance
    noisy = bytearray(img.pixels)
    for i in range(0, len(noisy), 4):
        noisy[i] = max(0, min(255, noisy[i] + rng.randint(-12, 12)))
    assert import_sprites(Image(img.width, img.height, bytes(noisy)),
                          Options(multi=True, colours=list(MC))).sprites[0].rows == sprites[0].rows


def test_transparent_is_background():
    img = Image.from_rows([[None] * 24 for _ in range(21)])
    assert import_sprites(img, Options()).sprites[0].rows == [0] * 21
    assert guess_colours(img, Options(multi=True))[0] is None


def test_cells():
    img = Image.from_rows([[PAPER] * 50 for _ in range(43)])
    assert cells(img, Options()) == [(0, 0), (24, 0), (0, 21), (24, 21)]
    assert cells(img, Options(x=3)) == [(3, 0), (3, 21)]
    assert cells(img, Options(scale=3)) == []


def test_files(tmp_path):
    """A real .bmp and .png, through GdkPixbuf."""
    rng = random.Random(4)
    sprites = [random_sprite(rng) for _ in range(2)]
    img = sheet(sprites, 2)
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(img.pixels), GdkPixbuf.Colorspace.RGB, True, 8,
                                         img.width, img.height, img.width * 4)
    for kind in ("bmp", "png"):
        pb.savev(str(tmp_path / f"s.{kind}"), kind, [], [])
        got = load_image(tmp_path / f"s.{kind}")
        assert got.kind.startswith(kind.upper()) and (got.width, got.height) == (48, 21)
        assert [s.rows for s in import_sprites(got, Options()).sprites] == [s.rows for s in sprites]
    (tmp_path / "bad.bmp").write_bytes(b"not an image")
    with pytest.raises(ImageError):
        load_image(tmp_path / "bad.bmp")


def test_one_bit_bmp(tmp_path):
    """A 1 bit per pixel .bmp, the kind CBM prg Studio's help mentions, written by hand."""
    rng = random.Random(5)
    s = random_sprite(rng)
    w, h = 24, 21
    stride = 4                                          # 24 bits, padded to 32
    rows = b"".join((s.rows[y] ^ 0xFFFFFF).to_bytes(3, "big") + b"\0" for y in reversed(range(h)))
    header = struct.pack("<2sIHHI", b"BM", 62 + len(rows), 0, 0, 62)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 1, 0, len(rows), 2835, 2835, 2, 2)
    palette = bytes([0, 0, 0, 0, 255, 255, 255, 0])     # 0 black, 1 white: set bits are white
    (tmp_path / "one.bmp").write_bytes(header + info + palette + rows)
    assert stride * h == len(rows)
    got = load_image(tmp_path / "one.bmp")
    assert import_sprites(got, Options()).sprites[0].rows == s.rows


def test_guess_uses_the_sprite_sets_colours():
    """Which colour is which bit pair can't be told from the image: the set's colours decide."""
    global MC
    saved = MC
    MC = [PALETTE[6], PALETTE[2], PALETTE[5], PALETTE[7]]       # blue background; red, green, yellow
    try:
        rng = random.Random(6)
        img = sheet([random_sprite(rng, multi=True) for _ in range(2)], 2, multi=True, fill=MC[0])
        assert guess_colours(img, Options(multi=True), hints=(5, 2, 7)) == MC
        assert guess_colours(img, Options(multi=True), hints=(7, 5, 2)) == [MC[0], MC[2], MC[3], MC[1]]
    finally:
        MC = saved
