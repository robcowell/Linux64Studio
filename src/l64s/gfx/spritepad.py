"""SpritePad .spd files: SpritePad 1.8's headerless format and SPD versions 1 to 5.

Layouts (from SpritePad C64 Pro's "File Format - SPD (Vn)" help pages, as summarised in
batchpad's docs/spritepad.md; multi-byte numbers are little endian):

  1.8 (no header):  background, multicolour 1, multicolour 2, then 64 bytes per sprite.
  V1 (SpritePad 2.0, Retro Game Dev Vol 2):
                    "SPD", 1, sprites - 1, animations - 1, background, mc 1, mc 2,
                    64 bytes per sprite, then 4 bytes per animation.
  V2 (SpritePad 2.3): "SPD", 2, flags, sprites (word), tiles (word), animations (word),
                    tile width, tile height, background, mc 1, mc 2 (16 bytes).
  V3 to V5 (2.8, 2.9, every Pro release saves V5):
                    "SPD", version, flags, sprites (word), tiles (word), sprite animations - 1,
                    tile animations - 1, tile width, tile height, background, mc 1, mc 2,
                    and in V4 and V5 two overlay distances (words): 16 or 20 bytes.
  V2 to V5 follow the sprites with tiles and animations, which are kept verbatim here.

The 64th byte of a sprite: bits 0-3 colour, bit 4 overlay, bit 7 multicolour; V5 uses bits 5 and 6
for expand X and Y.
"""
from __future__ import annotations

from pathlib import Path

from .sprite import HEIGHT, Sprite, SpriteSet

HEADERLESS = 0   # SpriteSet.spd_version of a SpritePad 1.8 file
_HEADER_SIZE = {1: 9, 2: 16, 3: 16, 4: 20, 5: 20}
_MAX_SPRITES = {HEADERLESS: 256, 1: 256, 2: 4096, 3: 65535, 4: 65535, 5: 65535}
_EXPAND_X, _EXPAND_Y = 0x20, 0x40


class SpritePadError(ValueError):
    pass


def _sprite(block: bytes, version: int) -> Sprite:
    attr = block[63]
    rows = [(block[r * 3] << 16) | (block[r * 3 + 1] << 8) | block[r * 3 + 2] for r in range(HEIGHT)]
    s = Sprite(rows=rows, multi=bool(attr & 0x80), colour=attr & 0x0F, attr_extra=attr & 0x70)
    if version == 5:
        s.expand_x, s.expand_y = bool(attr & _EXPAND_X), bool(attr & _EXPAND_Y)
    return s


def _attribute(s: Sprite, version: int) -> int:
    attr = s.attribute
    if version == 5:
        attr = (attr & ~(_EXPAND_X | _EXPAND_Y)) | (_EXPAND_X if s.expand_x else 0) | (_EXPAND_Y if s.expand_y else 0)
    return attr


def load_spd(path: str | Path) -> SpriteSet:
    name = Path(path).name
    data = Path(path).read_bytes()
    if data[:3] != b"SPD":
        # SpritePad 1.8: 3 colours, then whole sprites. A colour byte is never "S" (0x53).
        if len(data) < 67 or len(data) % 64 != 3:
            raise SpritePadError(f"{name} isn't a SpritePad file")
        n = (len(data) - 3) // 64
        return SpriteSet(sprites=[_sprite(data[3 + i * 64:3 + (i + 1) * 64], HEADERLESS) for i in range(n)],
                         background=data[0] & 0x0F, mcolour1=data[1] & 0x0F, mcolour2=data[2] & 0x0F,
                         attribute_bytes=True, spd_version=HEADERLESS)
    if len(data) < 4:
        raise SpritePadError(f"{name} isn't a SpritePad file")
    version = data[3]
    if version not in _HEADER_SIZE:
        raise SpritePadError(f"SpritePad format version {version} isn't supported (only versions 1 to 5)")
    hsize = _HEADER_SIZE[version]
    if len(data) < hsize:
        raise SpritePadError(f"{name} is truncated: its header is incomplete")
    if version == 1:
        n_sprites, colours = data[4] + 1, data[6:9]
    else:
        n_sprites, colours = int.from_bytes(data[5:7], "little"), data[13:16]
        if n_sprites == 0:
            raise SpritePadError(f"{name} has no sprites")
    body = data[hsize:]
    if len(body) < n_sprites * 64:
        raise SpritePadError(f"{name} is truncated: expected {n_sprites} sprites")
    sprites = [_sprite(body[i * 64:(i + 1) * 64], version) for i in range(n_sprites)]
    tail = body[n_sprites * 64:]
    if version == 1:
        anims, extra = tail[:(data[5] + 1) * 4], b""
    else:
        anims, extra = b"", data[:hsize] + tail
    return SpriteSet(sprites=sprites, background=colours[0] & 0x0F, mcolour1=colours[1] & 0x0F,
                     mcolour2=colours[2] & 0x0F, attribute_bytes=True, animations=bytes(anims),
                     spd_version=version, spd_extra=bytes(extra))


def save_spd(ss: SpriteSet, path: str | Path) -> None:
    """Write `ss` in the format it was loaded from (SPD V1 for a set that didn't come from SpritePad).
    The tiles and animations of a V2 to V5 file go back unchanged."""
    version = ss.spd_version
    if version not in _MAX_SPRITES or (version >= 2 and len(ss.spd_extra) < _HEADER_SIZE[version]):
        version = 1
    limit = _MAX_SPRITES[version]
    if not 1 <= len(ss.sprites) <= limit:
        raise SpritePadError(f"A SpritePad {'1.8' if version == HEADERLESS else f'V{version}'} file holds "
                             f"1 to {limit} sprites")
    colours = bytes([ss.background & 0x0F, ss.mcolour1 & 0x0F, ss.mcolour2 & 0x0F])
    sprites = b"".join(s.to_bytes() + bytes([_attribute(s, version)]) for s in ss.sprites)
    if version == HEADERLESS:
        out = colours + sprites
    elif version == 1:
        anims = ss.animations if ss.animations and len(ss.animations) % 4 == 0 else bytes(4)
        out = b"SPD" + bytes([1, len(ss.sprites) - 1, len(anims) // 4 - 1]) + colours + sprites + anims
    else:
        hsize = _HEADER_SIZE[version]
        header = bytearray(ss.spd_extra[:hsize])
        header[5:7] = len(ss.sprites).to_bytes(2, "little")
        header[13:16] = colours
        out = bytes(header) + sprites + ss.spd_extra[hsize:]
    Path(path).write_bytes(out)
