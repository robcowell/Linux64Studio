"""Commodore disk images: .d64 (1541), .d71 (1571, double-sided) and .d81 (1581).

Each format is described by a DiskFormat (layouts as in Rift64's drive emulation):

  D64  35 tracks, 17-21 sectors (683 in all). Header + BAM at 18/0, directory from 18/1.
  D71  70 tracks: side two (36-70) repeats side one's zones. Side one's BAM as a D64's;
       side two's free counts at $DD-$FF of 18/0 and its bitmaps in 53/0. Track 53 is kept
       in use. Byte 3 of 18/0 is $80 (double-sided).
  D81  80 tracks of 40 sectors. Header at 40/0 (links to the directory, normally 40/3), BAM
       in 40/1 (tracks 1-40) and 40/2 (41-80) as 6-byte entries from $10.

Files are allocated exactly as each drive's DOS does it, which tests/test_disk_images.py checks
against recordings from real 1541, 1571 and 1581 drives: a new file starts at the first free
sector outward from the directory track; each further block is the format's interleave on
(10 on a 1541, 6 on a 1571, 1 on a 1581), wrapping round one short past the end of a track;
when a track is full the search carries on away from the directory track, and when that side
is full, on the other side from its start. When a file exactly fills its last sector the DOS
takes one more block, which `validate()` gives back, as the DOS's V command does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PAD = 0xA0
FILE_TYPES = {"del": 0, "seq": 1, "prg": 2, "usr": 3, "rel": 4}
TYPE_NAMES = {v: k for k, v in FILE_TYPES.items()}
CLOSED = 0x80
LOCKED = 0x40


class DiskError(Exception):
    pass


def _zone(track: int) -> int:
    return 21 if track <= 17 else 19 if track <= 24 else 18 if track <= 30 else 17


@dataclass(frozen=True)
class DiskFormat:
    kind: str                       # "d64", "d71", "d81"
    drive: str                      # "1541", "1571", "1581"
    tracks: int
    sectors: Callable[[int], int]
    dir_track: int
    header: tuple[int, int]         # header sector (name, ID, DOS type)
    name_offset: int
    id_offset: int
    dos_type_offset: int
    dos_type: bytes
    reserved_tracks: tuple[int, ...]  # not counted as free
    interleave: int
    dir_interleave: int
    first_search: int
    system_sectors: tuple[tuple[int, int], ...]
    track_offsets: list[int] = field(default_factory=list, compare=False, repr=False)

    def __post_init__(self):
        offs = [0, 0]
        for t in range(1, self.tracks + 1):
            offs.append(offs[t] + self.sectors(t) * 256)
        object.__setattr__(self, "track_offsets", offs)

    @property
    def image_size(self) -> int:
        return self.track_offsets[self.tracks + 1]

    @property
    def total_free(self) -> int:
        """Free blocks on a blank disk."""
        n = sum(self.sectors(t) for t in range(1, self.tracks + 1) if t not in self.reserved_tracks)
        return n


D64_FORMAT = DiskFormat(
    kind="d64", drive="1541", tracks=35, sectors=_zone, dir_track=18, header=(18, 0),
    name_offset=0x90, id_offset=0xA2, dos_type_offset=0xA5, dos_type=b"2A", reserved_tracks=(18,),
    interleave=10, dir_interleave=3, first_search=22, system_sectors=((18, 0),))

D71_FORMAT = DiskFormat(
    kind="d71", drive="1571", tracks=70, sectors=lambda t: _zone(t - 35 if t > 35 else t), dir_track=18,
    header=(18, 0), name_offset=0x90, id_offset=0xA2, dos_type_offset=0xA5, dos_type=b"2A",
    reserved_tracks=(18, 53), interleave=6, dir_interleave=3, first_search=52,
    system_sectors=((18, 0),) + tuple((53, s) for s in range(19)))

D81_FORMAT = DiskFormat(
    kind="d81", drive="1581", tracks=80, sectors=lambda t: 40, dir_track=40, header=(40, 0),
    name_offset=0x04, id_offset=0x16, dos_type_offset=0x19, dos_type=b"3D", reserved_tracks=(40,),
    interleave=1, dir_interleave=1, first_search=40, system_sectors=((40, 0), (40, 1), (40, 2)))

FORMATS = {f.kind: f for f in (D64_FORMAT, D71_FORMAT, D81_FORMAT)}
EXTENSIONS = tuple("." + k for k in FORMATS)


def format_for(path: str | Path) -> DiskFormat:
    kind = Path(path).suffix.lower().lstrip(".")
    if kind not in FORMATS:
        raise DiskError(f"{Path(path).name}: disk images must be .d64, .d71 or .d81")
    return FORMATS[kind]


def detect_format(data: bytes) -> DiskFormat:
    """The format of an image from its size (plain or with error bytes)."""
    n = len(data)
    for f in (D81_FORMAT, D71_FORMAT, D64_FORMAT):  # largest first
        sectors = f.image_size // 256
        if n in (f.image_size, f.image_size + sectors):
            return f
    # 40-track D64s and other extended images: treat as a D64 if big enough
    if D64_FORMAT.image_size <= n < D71_FORMAT.image_size:
        return D64_FORMAT
    raise DiskError(f"Not a disk image this tool knows ({n} bytes)")


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
    slot: tuple[int, int, int]  # (dir track, dir sector, entry index)
    type_byte: int = 0

    def type_label(self) -> str:
        t = self.file_type.upper()
        return ("" if self.closed else "*") + t + ("<" if self.locked else "")


class DiskImage:
    def __init__(self, fmt: DiskFormat | str = D64_FORMAT, data: bytes | bytearray | None = None):
        self.fmt = FORMATS[fmt] if isinstance(fmt, str) else fmt
        if data is None:
            self.data = bytearray(self.fmt.image_size)
            self.format("", "00")
        else:
            if len(data) < self.fmt.image_size:
                raise DiskError(f"Not a .{self.fmt.kind} image ({len(data)} bytes, expected {self.fmt.image_size})")
            # Error bytes or extra tracks after the standard image are kept untouched.
            self.data = bytearray(data)

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: str | Path) -> "DiskImage":
        data = Path(path).read_bytes()
        try:
            fmt = format_for(path)
        except DiskError:
            fmt = detect_format(data)
        return cls(fmt, data)

    @classmethod
    def blank(cls, kind: str, name: str = "", disk_id: str = "00") -> "DiskImage":
        d = cls(FORMATS[kind])
        d.format(name, disk_id)
        return d

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(bytes(self.data))

    def _offset(self, track: int, sector: int) -> int:
        f = self.fmt
        if not 1 <= track <= f.tracks or not 0 <= sector < f.sectors(track):
            raise DiskError(f"Track {track} sector {sector} is outside the disk")
        return f.track_offsets[track] + sector * 256

    def sector(self, track: int, sector: int) -> memoryview:
        o = self._offset(track, sector)
        return memoryview(self.data)[o:o + 256]

    # ------------------------------------------------------------------ BAM layout
    def _bam(self, track: int) -> tuple[int, int, int]:
        """(offset of the track's free count, offset of its bitmap, bitmap bytes) in self.data."""
        f = self.fmt
        if f.kind == "d81":
            count = self._offset(40, 1 if track <= 40 else 2) + 0x10 + ((track - 1) % 40) * 6
            return count, count + 1, 5
        if f.kind == "d71" and track > 35:
            return (self._offset(18, 0) + 0xDD + track - 36,
                    self._offset(53, 0) + (track - 36) * 3, 3)
        count = self._offset(18, 0) + 4 * track
        return count, count + 1, 3

    def is_free(self, track: int, sector: int) -> bool:
        _c, bitmap, _n = self._bam(track)
        return bool(self.data[bitmap + sector // 8] & (1 << (sector % 8)))

    def _set(self, track: int, sector: int, free: bool) -> None:
        count, bitmap, _n = self._bam(track)
        o = bitmap + sector // 8
        bit = 1 << (sector % 8)
        if bool(self.data[o] & bit) == free:
            return
        self.data[o] = (self.data[o] | bit) if free else (self.data[o] & ~bit & 0xFF)
        self.data[count] = (self.data[count] + (1 if free else -1)) & 0xFF

    def _allocate(self, track: int, sector: int) -> None:
        if not self.is_free(track, sector):
            raise DiskError(f"Block {track}/{sector} is already in use")
        self._set(track, sector, False)

    def free_on_track(self, track: int) -> int:
        return self.data[self._bam(track)[0]]

    @property
    def blocks_free(self) -> int:
        """Free blocks as the C64 reports them (the directory track isn't counted)."""
        return sum(self.free_on_track(t) for t in range(1, self.fmt.tracks + 1) if t not in self.fmt.reserved_tracks)

    def _mark_all_free(self) -> None:
        for t in range(1, self.fmt.tracks + 1):
            count, bitmap, nbytes = self._bam(t)
            n = self.fmt.sectors(t)
            bits = (1 << n) - 1
            self.data[count] = n
            for i in range(nbytes):
                self.data[bitmap + i] = (bits >> (8 * i)) & 0xFF

    # ------------------------------------------------------------------ format / header
    def format(self, name: str, disk_id: str = "00") -> None:
        """Make an empty disk, as the drive's N (new) command does."""
        f = self.fmt
        self.data[:f.image_size] = bytes(f.image_size)
        if f.kind == "d81":
            hdr = self.sector(40, 0)
            hdr[0], hdr[1], hdr[2] = 40, 3, 0x44           # directory at 40/3, "D"
            raw_id = self._id_bytes(disk_id)
            for s in (1, 2):
                bam = self.sector(40, s)
                bam[0:7] = bytes([40 if s == 1 else 0, 2 if s == 1 else 0xFF, 0x44, 0xBB, *raw_id, 0xC0])
            self._mark_all_free()
            self.set_header(name, disk_id)
            for s in (0, 1, 2, 3):
                self._set(40, s, False)
            d = self.sector(40, 3)
            d[0], d[1] = 0, 0xFF
            return
        hdr = self.sector(18, 0)
        hdr[0], hdr[1], hdr[2], hdr[3] = 18, 1, 0x41, 0x80 if f.kind == "d71" else 0
        self._mark_all_free()
        self.set_header(name, disk_id)
        for t, s in f.system_sectors:
            self._set(t, s, False)
        self._set(18, 1, False)
        d = self.sector(18, 1)
        d[0], d[1] = 0, 0xFF

    @staticmethod
    def _id_bytes(disk_id: str) -> bytes:
        rid = to_petscii_name(disk_id or "00", 2)
        return rid + b"0" * (2 - len(rid))

    def set_header(self, name: str, disk_id: str) -> None:
        f = self.fmt
        hdr = self.sector(*f.header)
        raw = to_petscii_name(name)
        n0 = f.name_offset
        # name (16), $A0 $A0, ID (2), $A0, DOS type (2), $A0 padding
        hdr[n0:n0 + 16] = raw + bytes([PAD]) * (16 - len(raw))
        hdr[n0 + 16], hdr[n0 + 17] = PAD, PAD
        hdr[f.id_offset:f.id_offset + 2] = self._id_bytes(disk_id)
        hdr[f.id_offset + 2] = PAD
        hdr[f.dos_type_offset:f.dos_type_offset + 2] = f.dos_type
        pad_to = 0xAB if f.kind != "d81" else 0x1D
        hdr[f.dos_type_offset + 2:pad_to] = bytes([PAD]) * (pad_to - f.dos_type_offset - 2)
        if f.kind == "d81":  # the BAM sectors repeat the ID
            for s in (1, 2):
                self.sector(40, s)[4:6] = self._id_bytes(disk_id)

    @property
    def disk_name(self) -> str:
        o = self.fmt.name_offset
        return from_petscii_name(bytes(self.sector(*self.fmt.header)[o:o + 16]))

    @property
    def disk_id(self) -> str:
        o = self.fmt.id_offset
        return from_petscii_name(bytes(self.sector(*self.fmt.header)[o:o + 2]))

    # ------------------------------------------------------------------ directory
    def _dir_start(self) -> tuple[int, int]:
        if self.fmt.kind == "d81":
            hdr = self.sector(40, 0)
            return (40, hdr[1]) if hdr[0] == 40 else (40, 3)
        return 18, 1

    def _dir_chain(self):
        t, s = self._dir_start()
        seen = set()
        limit = self.fmt.sectors(self.fmt.dir_track)
        while t and (t, s) not in seen and len(seen) < limit:
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
                if ftype == 0 and (not include_deleted or not any(e[3:])):
                    continue
                raw = bytes(e[5:21]).rstrip(bytes([PAD]))
                out.append(DirEntry(
                    name=from_petscii_name(raw), raw_name=raw,
                    file_type=TYPE_NAMES.get(ftype & 7, "?"), closed=bool(ftype & CLOSED),
                    locked=bool(ftype & LOCKED), track=e[3], sector=e[4],
                    blocks=e[30] | (e[31] << 8), slot=(t, s, i), type_byte=ftype))
        return out

    def find(self, name: str) -> DirEntry | None:
        raw = to_petscii_name(name)
        return next((e for e in self.entries() if e.raw_name == raw), None)

    @staticmethod
    def _step(n: int, sector: int, interleave: int) -> int:
        """The sector `interleave` on from `sector` on a track of n sectors. Past the end it
        wraps round one short (unless it lands on 0), as the DOS does."""
        s = sector + interleave
        if s >= n:
            s -= n
            if s:
                s -= 1
        return s

    def _free_dir_slot(self) -> tuple[int, int, int]:
        last = None
        for t, s in self._dir_chain():
            sec = self.sector(t, s)
            for i in range(8):
                if sec[i * 32 + 2] == 0:
                    return t, s, i
            last = (t, s)
        dt = self.fmt.dir_track
        n = self.fmt.sectors(dt)
        start = self._step(n, last[1], self.fmt.dir_interleave)
        for k in range(n):
            s = (start + k) % n
            if self.is_free(dt, s):
                self._set(dt, s, False)
                prev = self.sector(*last)
                prev[0], prev[1] = dt, s
                new = self.sector(dt, s)
                new[:] = bytes(256)
                new[0], new[1] = 0, 0xFF
                return dt, s, 0
        raise DiskError("The directory is full")

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

    def _take(self, track: int, start: int) -> tuple[int, int] | None:
        """Allocate the first free sector on `track`, scanning from `start`."""
        f = self.fmt
        if not 1 <= track <= f.tracks or track == f.dir_track or not self.free_on_track(track):
            return None
        n = f.sectors(track)
        for k in range(n):
            s = (start + k) % n
            if self.is_free(track, s):
                self._set(track, s, False)
                return track, s
        return None

    def _allocate_next(self, last: tuple[int, int] | None) -> tuple[int, int]:
        """Allocate a file's next block the way the drive's DOS does."""
        f = self.fmt
        dt = f.dir_track
        if last is None:
            for dist in range(1, f.first_search + 1):
                found = self._take(dt - dist, 0) or self._take(dt + dist, 0)
                if found:
                    return found
            raise DiskError("The disk is full")
        step = lambda t, s: self._step(f.sectors(t), s, f.interleave)  # noqa: E731
        track, sector = last
        found = self._take(track, step(track, sector))
        if found:
            return found
        for _pass in range(3):
            if track < dt:
                for t in range(track, 0, -1):
                    found = self._take(t, step(t, sector))
                    if found:
                        return found
                track = dt + 1
            else:
                for t in range(track, f.tracks + 1):
                    found = self._take(t, step(t, sector))
                    if found:
                        return found
                track = dt - 1
            sector = 0
        raise DiskError("The disk is full")

    def add_file(self, name: str, data: bytes, file_type: str = "prg", replace: bool = False) -> DirEntry:
        raw = to_petscii_name(name)
        if not raw:
            raise DiskError("A file needs a name")
        if file_type not in ("prg", "seq", "usr"):
            raise DiskError(f"Can't write {file_type.upper()} files")
        if self.find(name):
            if not replace:
                raise DiskError(f"'{name}' is already on the disk")
            self.delete(name)
        blocks = max(1, (len(data) + 253) // 254)
        if blocks > self.blocks_free:
            raise DiskError(f"'{name}' needs {blocks} blocks but only {self.blocks_free} are free")
        slot = self._free_dir_slot()  # first: it may use a block on the directory track
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

        Blocks no closed file uses (like the extra block taken when a file exactly fills its
        last sector) are freed, and unclosed files are removed.
        """
        self._mark_all_free()
        for t, s in self.fmt.system_sectors:
            self._set(t, s, False)
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
        lines = [f'0 "{self.disk_name:<16}" {self.disk_id} {self.fmt.dos_type.decode()}']
        for e in self.entries():
            lines.append(f'{e.blocks:<5}{chr(34) + e.name + chr(34):<18} {e.type_label()}')
        lines.append(f"{self.blocks_free} BLOCKS FREE.")
        return "\n".join(lines) + "\n"

    def allocation_map(self) -> str:
        """Where everything is, in the text format of Rift64's real-drive fixtures."""
        lines = []
        for e in self.entries():
            chain = " ".join(f"{t}/{s}" for t, s in self._file_chain(e.track, e.sector))
            lines.append(f"{e.name} type {e.type_byte:x} blocks {e.blocks} chain {chain}")
        lines.append(f"free {self.blocks_free}")
        for t in range(1, self.fmt.tracks + 1):
            used = [str(s) for s in range(self.fmt.sectors(t)) if not self.is_free(t, s)]
            if used:
                lines.append(f"track {t} used {','.join(used)}")
        return "\n".join(lines) + "\n"


def file_type_for(path: Path) -> str:
    return {".prg": "prg", ".seq": "seq", ".usr": "usr"}.get(Path(path).suffix.lower(), "seq")


def build_disk(path: Path, disk_name: str, disk_id: str, files: list[tuple[str, bytes, str]],
               kind: str | None = None) -> DiskImage:
    """Write a new disk image (format from `kind` or the file extension) with `files` in order."""
    fmt = FORMATS[kind] if kind else format_for(path)
    d = DiskImage(fmt)
    d.format(disk_name, disk_id)
    for name, data, ftype in files:
        d.add_file(name, data, ftype)
    d.validate()
    d.save(path)
    return d
