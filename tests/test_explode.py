import random

import pytest

from l64s.basic.tokenizer import tokenize
from l64s.gfx.explode import TYPES, Params, basic_data, generate, levels, mutate, random_preset


def pixels(s):
    return sum(bin(r).count("1") for r in s.rows)


@pytest.mark.parametrize("kind", TYPES)
def test_each_type_grows_and_dies_away(kind):
    frames = generate(Params(type=kind, frames=8))
    counts = [pixels(f) for f in frames]
    assert len(frames) == 8 and all(not f.multi for f in frames)
    peak = max(counts)
    assert peak >= 40, counts                                # it's a real explosion
    assert counts[0] < peak and counts[-1] < peak * 0.5      # small at first, nearly gone at the end
    assert len({tuple(f.rows) for f in frames}) >= 6         # the frames differ


@pytest.mark.parametrize("kind", TYPES)
def test_multicolour_uses_three_colours(kind):
    frames = generate(Params(type=kind, frames=8), multi=True, colour=7)
    assert all(f.multi and f.colour == 7 for f in frames)
    used = {f.get(x, y) for f in frames for y in range(21) for x in range(12)}
    assert {1, 2}.issubset(used) and 0 in used


def test_levels():
    assert [levels(h) for h in (1.0, 0.5, 0.3, 0.1)] == [2, 1, 3, 0]


def test_repeatable_and_seeded():
    p = Params(type="debris", frames=6, seed=7)
    assert [f.rows for f in generate(p)] == [f.rows for f in generate(p)]
    assert [f.rows for f in generate(p)] != [f.rows for f in generate(p.copy(seed=8))]


def test_parameters_matter():
    small = sum(pixels(f) for f in generate(Params(radius=4)))
    big = sum(pixels(f) for f in generate(Params(radius=10)))
    assert big > small * 2
    few = sum(pixels(f) for f in generate(Params(type="debris", debris=5)))
    many = sum(pixels(f) for f in generate(Params(type="debris", debris=20)))
    assert many > few


def test_random_preset_and_mutate_stay_in_range():
    rng = random.Random(3)
    for _ in range(20):
        p = random_preset(rng)
        assert p.type in TYPES and 4 <= p.radius <= 10 and 6 <= p.spikes <= 16 and 5 <= p.debris <= 20
        m = mutate(p, rng)
        assert m.seed != p.seed and abs(m.radius - p.radius) <= 1
        generate(m)


def test_basic_data():
    frames = generate(Params(frames=2))
    text = basic_data(frames, 1000, 10)
    lines = text.splitlines()
    assert lines[0] == "1000 rem frame 0" and lines[5] == "1050 rem frame 1"
    assert not tokenize(text).warnings
    values = [int(v) for ln in lines if " data " in ln for v in ln.split(" data ")[1].split(",")]
    assert values == list(frames[0].to_bytes() + frames[1].to_bytes())


def test_bad_parameters():
    with pytest.raises(ValueError):
        generate(Params(type="nuke"))
    with pytest.raises(ValueError):
        generate(Params(frames=0))
