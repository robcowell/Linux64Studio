"""Sprite morphing, as CBM prg Studio's tool does it: a series of frames that turn one sprite into
another, by switching the pixels that differ from the first sprite's value to the second's, a
few more on each frame ("more like dissolve", as its help says).

The easing function sets how many of the differing pixels have switched by each frame:
  linear t, quadratic t^2, cubic t^3, sine (1 - cos(pi t)) / 2
where t runs from 0 (the first frame, the start sprite) to 1 (the last, the end sprite). The order
the pixels switch in is a shuffle (a dissolve, the same every time for the same seed), or a wipe.

The frames use the start sprite's mode (single colour or multicolour), colour and expansion, and
the end sprite's data is read in that mode, as CBM prg Studio does. In multicolour mode a pixel is
a pair of bits.
"""
from __future__ import annotations

import math
import random

from .sprite import HEIGHT, Sprite

EASINGS = {
    "linear": lambda t: t,
    "quadratic": lambda t: t * t,
    "cubic": lambda t: t * t * t,
    "sine": lambda t: (1 - math.cos(math.pi * t)) / 2,
}
ORDERS = ("dissolve", "top to bottom", "left to right", "from the centre")


def _order(points: list[tuple[int, int]], how: str, width: int, seed: int) -> list[tuple[int, int]]:
    if how == "dissolve":
        out = list(points)
        random.Random(seed).shuffle(out)
        return out
    if how == "top to bottom":
        return sorted(points, key=lambda p: (p[1], p[0]))
    if how == "left to right":
        return sorted(points, key=lambda p: (p[0], p[1]))
    if how == "from the centre":
        # in screen proportions: a multicolour pixel is two wide
        sx = 24 / width
        cx, cy = (width - 1) / 2, (HEIGHT - 1) / 2
        rng = random.Random(seed)
        jitter = {p: rng.random() for p in points}       # so rings don't switch all at once
        return sorted(points, key=lambda p: ((p[0] - cx) * sx) ** 2 + (p[1] - cy) ** 2 + jitter[p])
    raise ValueError(f"Unknown order {how!r}")


def morph(start: Sprite, end: Sprite, frames: int, easing: str = "linear", order: str = "dissolve",
          seed: int = 64) -> list[Sprite]:
    """`frames` sprites from start (the first) to end (the last)."""
    if frames < 2:
        raise ValueError("Morphing needs at least 2 frames (the start and end sprites)")
    if frames > 256:
        raise ValueError("That's too many frames (256 at most)")
    ease = EASINGS[easing]
    target = end.copy()
    target.multi = start.multi                      # read the end sprite in the start sprite's mode
    width = start.pixel_width
    diff = [(x, y) for y in range(HEIGHT) for x in range(width) if start.get(x, y) != target.get(x, y)]
    seq = _order(diff, order, width, seed)
    out = []
    for i in range(frames):
        t = i / (frames - 1)
        count = round(ease(t) * len(seq))
        f = start.copy()
        f.description = ""
        for x, y in seq[:count]:
            f.set(x, y, target.get(x, y))
        out.append(f)
    return out
