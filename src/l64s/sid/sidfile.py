"""PSID/RSID .sid music files: header, and the C64 data inside them.

Header (big-endian): magic "PSID"/"RSID", version (1-4), data offset (0x76 for v1, 0x7C
later), load address (0 = the first two data bytes hold it), init address, play address
(0 = the tune installs its own interrupt), number of songs, start song, speed bits, then
32-byte name, author and released strings. Version 2+ adds flags (clock and SID model).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


class SidError(Exception):
    pass


CLOCKS = {0: "unknown", 1: "PAL", 2: "NTSC", 3: "PAL and NTSC"}
MODELS = {0: "unknown", 1: "6581", 2: "8580", 3: "6581 and 8580"}


@dataclass
class SidFile:
    magic: str
    version: int
    data_offset: int
    load: int            # the real load address (from the data if the header says 0)
    init: int
    play: int
    songs: int
    start_song: int
    speed: int
    name: str
    author: str
    released: str
    flags: int
    data: bytes          # the C64 bytes that load at `load` (no load address)
    load_in_data: bool   # the header's load address was 0, so the data starts with it

    @property
    def end(self) -> int:
        return self.load + len(self.data)

    @property
    def clock(self) -> str:
        return CLOCKS[(self.flags >> 2) & 3] if self.version >= 2 else "unknown"

    @property
    def model(self) -> str:
        return MODELS[(self.flags >> 4) & 3] if self.version >= 2 else "unknown"

    @property
    def skip(self) -> int:
        """Bytes to skip to reach the music data in the file (header + any load address)."""
        return self.data_offset + (2 if self.load_in_data else 0)

    def prg(self) -> bytes:
        return bytes([self.load & 0xFF, self.load >> 8]) + self.data

    def speed_of(self, song: int) -> str:
        """'VBI' (once a frame) or 'CIA' (its own timer) for a 1-based song number."""
        return "CIA" if (self.speed >> min(song - 1, 31)) & 1 else "VBI"


def _text(raw: bytes) -> str:
    return raw.split(b"\0")[0].decode("latin-1").strip()


def parse_sid(data: bytes) -> SidFile:
    if len(data) < 0x76 or data[:4] not in (b"PSID", b"RSID"):
        raise SidError("Not a SID music file (no PSID/RSID header)")
    version, offset, load, init, play, songs, start, speed = struct.unpack(">HHHHHHHI", data[4:22])
    if version not in (1, 2, 3, 4) or offset not in (0x76, 0x7C) or offset > len(data):
        raise SidError(f"Unsupported SID header (version {version}, data offset {offset})")
    flags = struct.unpack(">H", data[0x76:0x78])[0] if version >= 2 and len(data) >= 0x78 else 0
    body = data[offset:]
    in_data = load == 0
    if in_data:
        if len(body) < 2:
            raise SidError("The SID file has no data")
        load = body[0] | (body[1] << 8)
        body = body[2:]
    if load + len(body) > 0x10000:
        raise SidError(f"The music runs past $FFFF (loads at ${load:04X}, {len(body)} bytes)")
    return SidFile(data[:4].decode(), version, offset, load, init or load, play, songs, start, speed,
                   _text(data[0x16:0x36]), _text(data[0x36:0x56]), _text(data[0x56:0x76]), flags,
                   bytes(body), in_data)


def load_sid(path: str | Path) -> SidFile:
    return parse_sid(Path(path).read_bytes())


def usage_code(sid: SidFile, include: str, kickass: bool = False) -> str:
    """Assembler source that includes the music and plays it (CBM prg Studio or Kick Assembler syntax)."""
    tune = max(0, sid.start_song - 1)
    if kickass:
        return f"""\
// {sid.name} by {sid.author}: ${sid.load:04X}-${sid.end - 1:04X}, init ${sid.init:04X}, play ${sid.play:04X}
*= ${sid.load:04X} "Music"
    .import binary "{include}", ${sid.skip:X}     // skip the SID header{" and load address" if sid.load_in_data else ""}

// Once, at start-up:
    lda #{tune}              // tune number - 1
    jsr ${sid.init:04X}

// Every frame (e.g. in your raster interrupt):
    jsr ${sid.play:04X}
"""
    return f"""\
; {sid.name} by {sid.author}: ${sid.load:04X}-${sid.end - 1:04X}, init ${sid.init:04X}, play ${sid.play:04X}
*=${sid.load:04X}
        incbin {include}        ; the music data, extracted from the .sid

; Once, at start-up:
        lda #{tune}             ; tune number - 1
        jsr ${sid.init:04X}

; Every frame (e.g. in your raster interrupt):
        jsr ${sid.play:04X}
"""
