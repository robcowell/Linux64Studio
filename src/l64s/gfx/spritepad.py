"""SpritePad .spd files (format version 1, as used by Retro Game Dev Vol 2 and SpritePad 2.0).

Layout (all single bytes):
  "SPD", version (1), sprite count - 1, animation count - 1,
  background colour, multicolour 1, multicolour 2,
  then 64 bytes per sprite (63 bytes of image + attribute byte: bit 7 multicolour,
  bits 0-3 sprite colour), then 4 bytes per animation.
"""
from __future__ import annotations

from pathlib import Path

from .sprite import HEIGHT, Sprite, SpriteSet


class SpritePadError(ValueError):
    pass


def load_spd(path: str | Path) -> SpriteSet:
    data = Path(path).read_bytes()
    if len(data) < 9 or data[:3] != b"SPD":
        raise SpritePadError(f"{Path(path).name} isn't a SpritePad file")
    version = data[3]
    if version != 1:
        raise SpritePadError(f"SpritePad format version {version} isn't supported (only version 1)")
    n_sprites, n_anims = data[4] + 1, data[5] + 1
    body = data[9:]
    if len(body) < n_sprites * 64:
        raise SpritePadError(f"{Path(path).name} is truncated: expected {n_sprites} sprites")
    sprites = []
    for i in range(n_sprites):
        block = body[i * 64:(i + 1) * 64]
        attr = block[63]
        rows = [(block[r * 3] << 16) | (block[r * 3 + 1] << 8) | block[r * 3 + 2] for r in range(HEIGHT)]
        sprites.append(Sprite(rows=rows, multi=bool(attr & 0x80), colour=attr & 0x0F, attr_extra=attr & 0x70))
    anims = body[n_sprites * 64:n_sprites * 64 + n_anims * 4]
    return SpriteSet(sprites=sprites, background=data[6] & 0x0F, mcolour1=data[7] & 0x0F,
                     mcolour2=data[8] & 0x0F, attribute_bytes=True, animations=bytes(anims))


def save_spd(ss: SpriteSet, path: str | Path) -> None:
    if not 1 <= len(ss.sprites) <= 256:
        raise SpritePadError("A SpritePad file holds 1 to 256 sprites")
    anims = ss.animations if ss.animations and len(ss.animations) % 4 == 0 else bytes(4)
    out = bytearray(b"SPD")
    out += bytes([1, len(ss.sprites) - 1, len(anims) // 4 - 1,
                  ss.background & 0x0F, ss.mcolour1 & 0x0F, ss.mcolour2 & 0x0F])
    for s in ss.sprites:
        out += s.to_bytes() + bytes([s.attribute])
    out += anims
    Path(path).write_bytes(bytes(out))
