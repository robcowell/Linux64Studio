"""1541 disk images (.d64). Kept for existing callers; the work is done in disk/image.py."""
from __future__ import annotations

from pathlib import Path

from .image import (CLOSED, D64_FORMAT, FILE_TYPES, LOCKED, PAD, TYPE_NAMES, DirEntry,  # noqa: F401
                    DiskError, DiskImage, build_disk, file_type_for, from_petscii_name, to_petscii_name)

TRACKS = D64_FORMAT.tracks
DIR_TRACK = D64_FORMAT.dir_track
SECTORS_PER_TRACK = [0] + [D64_FORMAT.sectors(t) for t in range(1, TRACKS + 1)]
IMAGE_SIZE = D64_FORMAT.image_size


class D64(DiskImage):
    def __init__(self, data: bytes | bytearray | None = None):
        super().__init__(D64_FORMAT, data)

    @classmethod
    def load(cls, path: str | Path) -> "D64":
        return cls(Path(path).read_bytes())
