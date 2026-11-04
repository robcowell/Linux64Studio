"""1541 disk images (.d64): create, list, add, extract and delete files.

Standard 35-track layout (174,848 bytes, 683 sectors of 256 bytes):
  * track 18 sector 0 is the BAM (block availability map) with the disk name and ID
  * the directory starts at 18/1 and is chained with an interleave of 3, as the 1541 does
  * each file is a chain of sectors: bytes 0-1 point to the next track/sector, the last
    sector has track 0 and byte 1 = index of its last used byte. 254 data bytes per sector.
  * files are allocated exactly as the 1541 DOS does it (the algorithm is ported from
    Rift64's drive emulation, which is checked against a real 1541's DOS), including the
    extra block DOS takes when a file exactly fills its last sector. `validate()` gives
    such blocks back, like the DOS's V command.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TRACKS = 35
DIR_TRACK = 18
SECTORS_PER_TRACK = [0] + [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5   # index = track number
IMAGE_SIZE = sum(SECTORS_PER_TRACK) * 256                              # 174848
FILE_INTERLEAVE = 10
DIR_INTERLEAVE = 3
FIRST_SEARCH = 22   # how far from the directory track a new file's first block is looked for
PAD = 0xA0

FILE_TYPES = {"del": 0, "seq": 1, "prg": 2, "usr": 3, "rel": 4}
TYPE_NAMES = {v: k for k, v in FILE_TYPES.items()}
CLOSED = 0x80
LOCKED = 0x40


class DiskError(Exception):
    pass


def _offset(track: int, sector: int) -> int:
    if not 1 <= track <= TRACKS or not 0 <= sector < SECTORS_PER_TRACK[track]:
        raise DiskError(f"Track {track} sector {sector} is outside the disk")
    return (sum(SECTORS_PER_TRACK[1:track]) + sector) * 256


def to_petscii_name(name: str, limit: int = 16) -> bytes:
    """A file or disk name as PETSCII. Letters of either case are the C64's normal letters."""
    out = bytearray()
    for ch in name:
        o = ord(ch)
        if "a" <= ch <= "z":
            out.append(o - 32)
        elif "A" <= ch <= "Z" or 0x20 <= o <= 0x40 or ch in "[]":
            out.append(o)
        elif ch == "£":
            out.append(0x5C)
        else:
            raise DiskError(f"Character {ch!r} can't be used in a disk or file name")
    if len(out) > limit:
        raise DiskError(f"'{name}' is longer than {limit} characters")
    return bytes(out)


def from_petscii_name(raw: bytes) -> str:
    """Display form of a PETSCII name (padding removed), as the C64 shows it."""
    raw = raw.rstrip(bytes([PAD]))
    out = []
    for b in raw:
        if 0x41 <= b <= 0x5A or 0x20 <= b <= 0x40 or b in (0x5B, 0x5D):
            out.append(chr(b))
        elif 0xC1 <= b <= 0xDA:
            out.append(chr(b - 0x80).lower())
        elif b == 0x5C:
            out.append("£")
        else:
            out.append(f"{{${b:02x}}}")
    return "".join(out)


@dataclass
class DirEntry:
    name: str           # display name
    raw_name: bytes     # PETSCII, unpadded
    file_type: str      # prg, seq, usr, rel, del
    closed: bool
    locked: bool
    track: int
    sector: int
    blocks: int
    slot: tuple[int, int, int]  # (dir track, dir sector, entry index) for updates

    def type_label(self) -> str:
        t = self.file_type.upper()
        return ("" if self.closed else "*") + t + ("<" if self.locked else "")


class D64:
    def __init__(self, data: bytes | bytearray | None = None):
        if data is None:
            self.data = bytearray(IMAGE_SIZE)
            self.format("", "00")
        else:
            if len(data) < IMAGE_SIZE:
                raise DiskError(f"Not a 35-track .d64 image ({len(data)} bytes, expected {IMAGE_SIZE})")
            # Images with error bytes (175,531) or 40 tracks keep their extra bytes untouched.
            self.data = bytearray(data)

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: str | Path) -> "D64":
        return cls(Path(path).read_bytes())

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(bytes(self.data))

    def sector(self, track: int, sector: int) -> memoryview:
        o = _offset(track, sector)
        return memoryview(self.data)[o:o + 256]

    # ------------------------------------------------------------------ BAM
    def format(self, name: str, disk_id: str = "00") -> None:
        self.data[:IMAGE_SIZE] = bytes(IMAGE_SIZE)
        bam = self.sector(DIR_TRACK, 0)
        bam[0], bam[1], bam[2], bam[3] = DIR_TRACK, 1, 0x41, 0  # dir at 18/1, DOS version 'A'
        for t in range(1, TRACKS + 1):
            n = SECTORS_PER_TRACK[t]
            bits = (1 << n) - 1
            o = 4 * t
            bam[o] = n
            bam[o + 1], bam[o + 2], bam[o + 3] = bits & 0xFF, (bits >> 8) & 0xFF, (bits >> 16) & 0xFF
        bam[0x90:0xAB] = bytes([PAD]) * (0xAB - 0x90)
        self.set_header(name, disk_id)
        self._allocate(DIR_TRACK, 0)
        self._allocate(DIR_TRACK, 1)
        d = self.sector(DIR_TRACK, 1)
        d[0], d[1] = 0, 0xFF

    def set_header(self, name: str, disk_id: str) -> None:
        bam = self.sector(DIR_TRACK, 0)
        raw = to_petscii_name(name)
        bam[0x90:0xA0] = raw + bytes([PAD]) * (16 - len(raw))
        rid = to_petscii_name(disk_id or "00", 2)
        rid = rid + b"0" * (2 - len(rid))
        bam[0xA0], bam[0xA1] = PAD, PAD
        bam[0xA2:0xA4] = rid
        bam[0xA4] = PAD
        bam[0xA5:0xA7] = b"2A"
        bam[0xA7:0xAB] = bytes([PAD]) * 4

    @property
    def disk_name(self) -> str:
        return from_petscii_name(bytes(self.sector(DIR_TRACK, 0)[0x90:0xA0]))

    @property
    def disk_id(self) -> str:
        return from_petscii_name(bytes(self.sector(DIR_TRACK, 0)[0xA2:0xA4]))

    def is_free(self, track: int, sector: int) -> bool:
        bam = self.sector(DIR_TRACK, 0)
        return bool(bam[4 * track + 1 + sector // 8] & (1 << (sector % 8)))

    def _set(self, track: int, sector: int, free: bool) -> None:
        bam = self.sector(DIR_TRACK, 0)
        o = 4 * track + 1 + sector // 8
        bit = 1 << (sector % 8)
        was = bool(bam[o] & bit)
        if was == free:
            return
        bam[o] = (bam[o] | bit) if free else (bam[o] & ~bit)
        bam[4 * track] += 1 if free else -1

    def _allocate(self, track: int, sector: int) -> None:
        if not self.is_free(track, sector):
            raise DiskError(f"Block {track}/{sector} is already in use")
        self._set(track, sector, False)

    def free_on_track(self, track: int) -> int:
        return self.sector(DIR_TRACK, 0)[4 * track]

    @property
    def blocks_free(self) -> int:
        """Free blocks as the C64 reports them (track 18 isn't counted)."""
        return sum(self.free_on_track(t) for t in range(1, TRACKS + 1) if t != DIR_TRACK)

    # ------------------------------------------------------------------ directory
    def _dir_chain(self):
        t, s = DIR_TRACK, 1
        seen = set()
        while t and (t, s) not in seen and len(seen) < 40:
            seen.add((t, s))
            yield t, s
            sec = self.sector(t, s)
            t, s = sec[0], sec[1]

    def entries(self, include_deleted: bool = False) -> list[DirEntry]:
        out = []
        for t, s in self._dir_chain():
            sec = self.sector(t, s)
            for i in range(8):
                e = sec[i * 32:(i + 1) * 32]
                ftype = e[2]
                if ftype == 0 and not include_deleted:
                    continue
                if ftype == 0 and not any(e[3:]):
                    continue
                raw = bytes(e[5:21]).rstrip(bytes([PAD]))
                out.append(DirEntry(
                    name=from_petscii_name(raw), raw_name=raw,
                    file_type=TYPE_NAMES.get(ftype & 7, "?"), closed=bool(ftype & CLOSED),
                    locked=bool(ftype & LOCKED), track=e[3], sector=e[4],
                    blocks=e[30] | (e[31] << 8), slot=(t, s, i)))
        return out

    def find(self, name: str) -> DirEntry | None:
        raw = to_petscii_name(name)
        return next((e for e in self.entries() if e.raw_name == raw), None)

    def _free_dir_slot(self) -> tuple[int, int, int]:
        last = None
        for t, s in self._dir_chain():
            sec = self.sector(t, s)
            for i in range(8):
                if sec[i * 32 + 2] == 0:
                    return t, s, i
            last = (t, s)
        # Chain a new directory sector, interleave 3 on track 18 (wrapping as the DOS does).
        n = SECTORS_PER_TRACK[DIR_TRACK]
        cand = self._step(DIR_TRACK, last[1], DIR_INTERLEAVE)
        for k in range(n):
            s = (cand + k) % n
            if s and self.is_free(DIR_TRACK, s):
                self._allocate(DIR_TRACK, s)
                prev = self.sector(*last)
                prev[0], prev[1] = DIR_TRACK, s
                new = self.sector(DIR_TRACK, s)
                new[:] = bytes(256)
                new[0], new[1] = 0, 0xFF
                return DIR_TRACK, s, 0
        raise DiskError("The directory is full (144 files)")

    # ------------------------------------------------------------------ files
    def _file_chain(self, track: int, sector: int):
        seen = set()
        while track:
            if (track, sector) in seen:
                raise DiskError("A file's block chain loops back on itself")
            seen.add((track, sector))
            yield track, sector
            sec = self.sector(track, sector)
            track, sector = sec[0], sec[1]

    def read_file(self, name_or_entry: str | DirEntry) -> bytes:
        e = name_or_entry if isinstance(name_or_entry, DirEntry) else self.find(name_or_entry)
        if e is None:
            raise DiskError(f"File '{name_or_entry}' not found")
        out = bytearray()
        for t, s in self._file_chain(e.track, e.sector):
            sec = self.sector(t, s)
            if sec[0] == 0:
                last = sec[1]
                out += sec[2:last + 1] if last >= 2 else b""
            else:
                out += sec[2:256]
        return bytes(out)

    @staticmethod
    def _step(track: int, sector: int, interleave: int) -> int:
        """The sector `interleave` on from `sector`. Past the end of the track it wraps round
        one short (unless it lands on 0), as the DOS does."""
        n = SECTORS_PER_TRACK[track]
        s = sector + interleave
        if s >= n:
            s -= n
            if s:
                s -= 1
        return s

    def _take(self, track: int, start: int) -> tuple[int, int] | None:
        """Allocate the first free sector on `track`, scanning from `start`."""
        if not 1 <= track <= TRACKS or track == DIR_TRACK or not self.free_on_track(track):
            return None
        n = SECTORS_PER_TRACK[track]
        for k in range(n):
            s = (start + k) % n
            if self.is_free(track, s):
                self._set(track, s, False)
                return track, s
        return None

    def _allocate_next(self, last: tuple[int, int] | None) -> tuple[int, int]:
        """Allocate a file's next block the way the DOS does.

        A new file starts at the first free sector outward from the directory track
        (17, 19, 16, 20, ...). Each further block is 10 sectors on from the last; when a
        track is full the search carries on away from the directory, and when that side is
        full, on the other side from its start.
        """
        if last is None:
            for dist in range(1, FIRST_SEARCH + 1):
                found = self._take(DIR_TRACK - dist, 0) or self._take(DIR_TRACK + dist, 0)
                if found:
                    return found
            raise DiskError("The disk is full")
        track, sector = last
        found = self._take(track, self._step(track, sector, FILE_INTERLEAVE))
        if found:
            return found
        for _pass in range(3):
            if track < DIR_TRACK:
                for t in range(track, 0, -1):
                    found = self._take(t, self._step(t, sector, FILE_INTERLEAVE))
                    if found:
                        return found
                track = DIR_TRACK + 1
            else:
                for t in range(track, TRACKS + 1):
                    found = self._take(t, self._step(t, sector, FILE_INTERLEAVE))
                    if found:
                        return found
                track = DIR_TRACK - 1
            sector = 0
        raise DiskError("The disk is full")

    def add_file(self, name: str, data: bytes, file_type: str = "prg", replace: bool = False) -> DirEntry:
        raw = to_petscii_name(name)
        if not raw:
            raise DiskError("A file needs a name")
        if file_type not in ("prg", "seq", "usr"):
            raise DiskError(f"Can't write {file_type.upper()} files")
        existing = self.find(name)
        if existing:
            if not replace:
                raise DiskError(f"'{name}' is already on the disk")
            self.delete(name)
        blocks = max(1, (len(data) + 253) // 254)
        if blocks > self.blocks_free:
            raise DiskError(f"'{name}' needs {blocks} blocks but only {self.blocks_free} are free")
        slot = self._free_dir_slot()  # allocate the directory slot first: it may use a track 18 block
        chain: list[tuple[int, int]] = []
        for _ in range(blocks):
            chain.append(self._allocate_next(chain[-1] if chain else None))
        # When the data exactly fills its last sector, the DOS has already taken the next
        # sector for data that never comes. It stays used, in no file, until validate().
        if data and len(data) % 254 == 0 and self.blocks_free:
            try:
                self._allocate_next(chain[-1])
            except DiskError:
                pass
        for i, (t, s) in enumerate(chain):
            sec = self.sector(t, s)
            sec[:] = bytes(256)
            chunk = data[i * 254:(i + 1) * 254]
            sec[2:2 + len(chunk)] = chunk
            if i + 1 < len(chain):
                sec[0], sec[1] = chain[i + 1]
            else:
                sec[0], sec[1] = 0, len(chunk) + 1
        dt, ds, di = slot
        e = self.sector(dt, ds)[di * 32:(di + 1) * 32]
        e[2:32] = bytes(30)
        e[2] = CLOSED | FILE_TYPES[file_type]
        e[3], e[4] = chain[0]
        e[5:21] = raw + bytes([PAD]) * (16 - len(raw))
        e[30], e[31] = blocks & 0xFF, blocks >> 8
        return self.find(name)

    def delete(self, name_or_entry: str | DirEntry) -> None:
        e = name_or_entry if isinstance(name_or_entry, DirEntry) else self.find(name_or_entry)
        if e is None:
            raise DiskError(f"File '{name_or_entry}' not found")
        for t, s in self._file_chain(e.track, e.sector):
            self._set(t, s, True)
        dt, ds, di = e.slot
        self.sector(dt, ds)[di * 32 + 2] = 0

    def validate(self) -> None:
        """Rebuild the BAM from the directory, as the DOS's V command does.

        Blocks not used by any closed file are freed (such as the extra block the DOS takes
        when a file exactly fills its last sector), and unclosed files are removed.
        """
        bam = self.sector(DIR_TRACK, 0)
        for t in range(1, TRACKS + 1):
            n = SECTORS_PER_TRACK[t]
            bits = (1 << n) - 1
            o = 4 * t
            bam[o] = n
            bam[o + 1], bam[o + 2], bam[o + 3] = bits & 0xFF, (bits >> 8) & 0xFF, (bits >> 16) & 0xFF
        self._set(DIR_TRACK, 0, False)
        for t, s in self._dir_chain():
            self._set(t, s, False)
        for e in self.entries():
            dt, ds, di = e.slot
            if not e.closed:
                self.sector(dt, ds)[di * 32 + 2] = 0
                continue
            for t, s in self._file_chain(e.track, e.sector):
                self._set(t, s, False)

    def listing(self) -> str:
        """The directory as LOAD"$",8 + LIST shows it."""
        lines = [f'0 "{self.disk_name:<16}" {self.disk_id} 2A']
        for e in self.entries():
            name = f'"{e.name}"'
            lines.append(f"{e.blocks:<5}{name:<18} {e.type_label()}")
        lines.append(f"{self.blocks_free} BLOCKS FREE.")
        return "\n".join(lines) + "\n"


def file_type_for(path: Path) -> str:
    sfx = path.suffix.lower()
    return {".prg": "prg", ".seq": "seq", ".usr": "usr"}.get(sfx, "seq")


def build_disk(path: Path, disk_name: str, disk_id: str, files: list[tuple[str, bytes, str]]) -> D64:
    """Write a new .d64 containing `files` [(name on disk, data, type)], in order."""
    d = D64()
    d.format(disk_name, disk_id)
    for name, data, ftype in files:
        d.add_file(name, data, ftype)
    d.validate()
    d.save(path)
    return d
