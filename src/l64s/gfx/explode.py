"""Sprite explosion generator: a series of sprites that animate an explosion, as CBM prg Studio's
tool makes them. Six types, each drawn as a "heat" field over the sprite, frame by frame:

  fireball   a lumpy ball that swells, then cools from the middle and breaks up
  radial     spikes that shoot out from the centre and fly off
  ring       a shock wave: a ring that grows, thins and breaks up
  debris     pieces flung outwards that slow down and fade
  starburst  a star that flashes up and dies away
  plasma     a swirling cloud that grows and thins out

Parameters (CBM prg Studio's, with its recommended ranges):
  radius 4-10 (how big it gets, in pixels), spikes 6-16, debris 5-20, turbulence 1-3 (how
  much the shapes wobble from frame to frame, in pixels), thickness 1-2.

In single colour the hot parts are set pixels. In multicolour the heat is split into three
levels: the hottest uses one bit pair, the cooler ones the other two (see `levels`). The same
parameters and seed always give the same frames.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

from .sprite import HEIGHT, Sprite

TYPES = ("fireball", "radial", "ring", "debris", "starburst", "plasma")
RECOMMENDED = {"radius": (4, 10), "spikes": (6, 16), "debris": (5, 20), "turbulence": (1, 3), "thickness": (1, 2)}
CX, CY = 11.5, 10.0                     # the middle of the sprite, in single colour pixels


@dataclass
class Params:
    type: str = "fireball"
    frames: int = 8
    radius: float = 9
    spikes: int = 10
    debris: int = 12
    turbulence: float = 1.5
    thickness: float = 1.5
    seed: int = 1

    def copy(self, **kw) -> "Params":
        return Params(**{**asdict(self), **kw})


def random_preset(rng: random.Random | None = None, type: str | None = None) -> Params:
    """Parameters chosen at random within the recommended ranges (as CBM prg Studio's Random)."""
    r = rng or random.Random()
    lo_hi = RECOMMENDED
    return Params(type=type or r.choice(TYPES), frames=r.randint(6, 12),
                  radius=r.randint(*lo_hi["radius"]), spikes=r.randint(*lo_hi["spikes"]),
                  debris=r.randint(*lo_hi["debris"]), turbulence=round(r.uniform(*lo_hi["turbulence"]), 1),
                  thickness=round(r.uniform(*lo_hi["thickness"]), 1), seed=r.randrange(1, 1 << 30))


def mutate(p: Params, rng: random.Random | None = None) -> Params:
    """A variation: each parameter nudged a little, and a new seed."""
    r = rng or random.Random()

    def nudge(v, lo, hi, step):
        return min(hi, max(lo, v + r.choice((-step, 0, step))))
    return p.copy(radius=nudge(p.radius, 2, 12, 1), spikes=int(nudge(p.spikes, 2, 32, 2)),
                  debris=int(nudge(p.debris, 0, 40, 3)), turbulence=round(nudge(p.turbulence, 0, 5, 0.5), 1),
                  thickness=round(nudge(p.thickness, 1, 3, 0.5), 1), seed=r.randrange(1, 1 << 30))


# ---------------------------------------------------------------------- the heat fields

def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 2


def _angle_dist(a: float, b: float) -> float:
    d = (a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


class _Field:
    """Heat (0 = nothing, 1 = hottest) at a point for one frame of one explosion."""

    def __init__(self, p: Params):
        self.p = p
        rng = random.Random(p.seed)
        n = max(1, int(p.spikes))
        self.spike_angles = [2 * math.pi * i / n + rng.uniform(-0.25, 0.25) * 2 * math.pi / n for i in range(n)]
        self.spike_len = [rng.uniform(0.6, 1.0) for _ in range(n)]
        self.lobes = [(rng.uniform(0, 2 * math.pi), rng.randint(2, 5), rng.uniform(0.5, 1.0)) for _ in range(4)]
        self.debris = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.45, 1.0), rng.uniform(0.6, 1.4))
                       for _ in range(max(0, int(p.debris)))]
        self.phases = [rng.uniform(0, 2 * math.pi) for _ in range(6)]
        self.noise_seed = rng.randrange(1 << 30)

    def _wobble(self, angle: float, frame: int) -> float:
        """How far out the edge is pushed at an angle (in pixels), changing each frame."""
        t = self.p.turbulence
        return t * sum(w * math.sin(k * angle + ph + frame * 0.9) for ph, k, w in self.lobes) / 2.5

    def _grain(self, x: float, y: float, frame: int) -> float:
        """A repeatable 0-1 value per pixel and frame, for breaking shapes up."""
        h = hash((int(x * 2), int(y * 2), frame, self.noise_seed)) & 0xFFFF
        return h / 0xFFFF

    def heat(self, x: float, y: float, frame: int, frames: int) -> float:
        p = self.p
        t = frame / max(1, frames - 1)                      # 0 at the first frame, 1 at the last
        dx, dy = x - CX, y - CY
        dist = math.hypot(dx, dy)
        ang = math.atan2(dy, dx)
        R = p.radius
        grain = self._grain(x, y, frame)
        kind = p.type
        if kind == "fireball":
            # swells fast, then cools (dimmer, smaller hot core) and breaks into smoke
            r = max(1.2, R * (0.3 + 0.7 * _ease_out(min(1.0, t * 1.4)))) + self._wobble(ang, frame)
            if dist > r:
                return 0.0
            edge = dist / r
            h = (1 - edge ** 1.6) * (1.25 - 0.85 * t) + 0.2 * (grain - 0.5) * p.turbulence / 2
            if grain < t ** 1.5 * 0.75:                     # holes as it breaks up
                h *= 0.35
            return max(0.0, min(1.0, h))
        if kind == "radial":
            # spikes shoot out from a flash in the middle, and their inner ends follow them out
            reach = R * 1.2 * _ease_out(min(1.0, t * 1.3)) + 1.0
            inner = R * 1.2 * max(0.0, t - 0.35) * 1.4
            best = 0.0
            for a, length in zip(self.spike_angles, self.spike_len):
                if not inner <= dist <= reach * length:
                    continue
                da = _angle_dist(ang, a)
                if da < math.pi / 2 and dist * math.sin(da) <= p.thickness * 0.55 + 0.3:
                    best = max(best, 1.0 - 0.5 * dist / (R * 1.2) - 0.35 * t)
            flash = 2.6 * (1 - t * 2)
            if dist < flash:
                best = max(best, 1.0 - dist / max(flash, 0.5) * 0.4)
            return max(0.0, best)
        if kind == "ring":
            # a shock wave: grows, gets thinner and fainter, and breaks up
            r = R * (0.15 + 0.9 * _ease_out(t)) + self._wobble(ang, frame) * 0.6
            w = p.thickness * (1.25 - 0.55 * t) + 0.35
            h = 0.0
            if abs(dist - r) <= w:
                h = 1.0 - abs(dist - r) / w * 0.45 - 0.45 * t
                if grain < max(0.0, t - 0.45) * 1.3:
                    h = 0.0
            if dist < r and t < 0.35:                       # the flash inside, early on
                h = max(h, (0.8 - t * 2) * (1 - dist / max(r, 1)))
            return max(0.0, h)
        if kind == "debris":
            # pieces flung out at different speeds, slowing, shrinking and fading
            best = 0.0
            for a, speed, size in self.debris:
                travelled = (R * 1.15) * speed * _ease_out(t)
                wob = p.turbulence * 0.35 * math.sin(frame * 1.3 + a * 5)
                px = CX + math.cos(a) * travelled + wob
                py = CY + math.sin(a) * travelled
                rad = (0.55 + p.thickness * 0.45) * size * (1 - 0.4 * t)
                if math.hypot(x - px, y - py) <= rad and self._grain(px, py, 0) > t * 0.5:
                    best = max(best, 1.0 - 0.55 * t - 0.15 * speed)
            flash = 3.0 * (1 - t * 2.5)
            if dist < flash:
                best = max(best, 1.0)
            return max(0.0, best)
        if kind == "starburst":
            # a star that flashes up to full size and dies away
            flash = math.sin(math.pi * (0.15 + 0.85 * t))
            r = R * 1.15 * flash
            best = 0.0
            for i, (a, length) in enumerate(zip(self.spike_angles, self.spike_len)):
                arm = r * (1.0 if i % 2 == 0 else 0.6) * length
                if dist > arm:
                    continue
                da = _angle_dist(ang, a)
                width = (p.thickness * 0.55 + 0.35) * (1 - dist / max(arm, 0.5)) + 0.3
                if da < math.pi / 2 and dist * math.sin(da) <= width:
                    best = max(best, 1.0 - 0.6 * dist / max(arm, 0.5))
            core = 2.4 * flash
            if dist < core:
                best = 1.0
            return best * (0.55 + 0.45 * flash)
        if kind == "plasma":
            # a churning cloud that grows and thins out
            r = R * (0.35 + 0.75 * _ease_out(t)) + self._wobble(ang, frame) * 0.8
            if dist > r:
                return 0.0
            ph = self.phases
            v = (math.sin(x * 0.7 + ph[0] + frame * 0.8) + math.sin(y * 0.75 + ph[1] - frame * 0.6)
                 + math.sin((x - y) * 0.5 + ph[2] + frame * 0.7) + math.sin(dist * 1.1 - frame * 1.2 + ph[3])) / 4
            h = 0.72 + 0.5 * v - 0.3 * dist / r - 0.5 * t
            return max(0.0, min(1.0, h))
        raise ValueError(f"Unknown explosion type {kind!r}")


def levels(heat: float) -> int:
    """Multicolour: the bit pair for a heat. Hottest 2 (%10, the sprite's own colour), then
    1 (%01, multicolour 1), then 3 (%11, multicolour 2), then 0 (background)."""
    if heat >= 0.66:
        return 2
    if heat >= 0.42:
        return 1
    if heat >= 0.2:
        return 3
    return 0


def generate(p: Params, multi: bool = False, colour: int = 7) -> list[Sprite]:
    if p.type not in TYPES:
        raise ValueError(f"Unknown explosion type {p.type!r}")
    if not 1 <= p.frames <= 64:
        raise ValueError("The number of frames must be 1 to 64")
    if p.radius <= 0:
        raise ValueError("The radius must be more than 0")
    field = _Field(p)
    out = []
    for f in range(p.frames):
        s = Sprite(multi=multi, colour=colour)
        if multi:
            for y in range(HEIGHT):
                for x in range(12):
                    s.set(x, y, levels(field.heat(2 * x + 0.5, y, f, p.frames)))
        else:
            for y in range(HEIGHT):
                for x in range(24):
                    if field.heat(x, y, f, p.frames) >= 0.3:
                        s.set(x, y, 1)
        out.append(s)
    return out


def basic_data(sprites: list[Sprite], start: int = 1000, step: int = 10, per_line: int = 16) -> str:
    """The sprites as BASIC DATA lines (63 bytes each), with a REM before each frame."""
    lines, n = [], start
    for i, s in enumerate(sprites):
        lines.append(f"{n} rem frame {i}")
        n += step
        data = s.to_bytes()
        for k in range(0, 63, per_line):
            lines.append(f"{n} data " + ",".join(str(b) for b in data[k:k + per_line]))
            n += step
    if n - step > 63999:
        raise ValueError("The line numbers run past 63999: start lower or use a smaller step")
    return "\n".join(lines) + "\n"
