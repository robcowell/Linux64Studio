"""VICE snapshots (.vsf): reading their CPU registers and RAM, keeping notes about them, and
comparing two.

A .vsf starts "VICE Snapshot File\\x1a", a version, the machine name, then (since VICE 2.x)
"VICE Version\\x1a" and four version bytes plus a revision, then modules. Each module is a
16-byte name, major and minor version bytes, and a 4-byte little-endian size that includes
this 22-byte header. MAINCPU holds the clock (8 bytes) then A, X, Y, SP, PC (2 bytes) and the
status; C64MEM holds the processor port and cartridge lines (4 bytes) then the 64K of RAM.
"""
from __future__ import annotations

import json
import re
import struct
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAGIC = b"VICE Snapshot File\x1a"
VERSION_MAGIC = b"VICE Version\x1a"
SIM_MODULE = "L64SIM"              # the simulator's own module: its I/O and chips' state


def is_simulator_snapshot(path) -> bool:
    try:
        return read_vsf(path).simulated
    except (OSError, SnapshotError):
        return False


class SnapshotError(ValueError):
    pass


@dataclass
class Snapshot:
    path: Path
    machine: str
    vice_version: str
    registers: dict[str, int]       # A X Y SP PC FL
    clock: int
    ram: bytes                      # 64K
    modules: list[str]
    module_data: dict[str, bytes] = field(default_factory=dict)     # each module's bytes, by name

    @property
    def simulated(self) -> bool:
        """Taken on Linux64Studio's simulated C64 (emu.sim), not in VICE."""
        return SIM_MODULE in self.module_data


def read_vsf(path: str | Path) -> Snapshot:
    p = Path(path)
    data = p.read_bytes()
    if not data.startswith(MAGIC):
        raise SnapshotError(f"{p.name} isn't a VICE snapshot")
    machine = data[21:37].split(b"\0")[0].decode("latin-1")
    off = 37
    version = ""
    if data[off:off + len(VERSION_MAGIC)] == VERSION_MAGIC:
        v = data[off + len(VERSION_MAGIC):off + len(VERSION_MAGIC) + 4]
        version = ".".join(str(x) for x in v[:3])
        off += len(VERSION_MAGIC) + 8
    modules: dict[str, tuple[int, int, bytes]] = {}
    names = []
    while off + 22 <= len(data):
        name = data[off:off + 16].split(b"\0")[0].decode("latin-1")
        major, minor = data[off + 16], data[off + 17]
        size = struct.unpack_from("<I", data, off + 18)[0]
        if size < 22 or off + size > len(data):
            raise SnapshotError(f"{p.name} is damaged (module {name or '?'} runs past the end)")
        modules[name] = (major, minor, data[off + 22:off + size])
        names.append(name)
        off += size
    if "MAINCPU" not in modules or "C64MEM" not in modules:
        raise SnapshotError(f"{p.name} isn't a C64 snapshot (machine {machine})")
    major, _minor, cpu = modules["MAINCPU"]
    if major != 1 or len(cpu) < 15:
        raise SnapshotError(f"Unsupported CPU data in {p.name} (MAINCPU version {major})")
    clock = struct.unpack_from("<Q", cpu, 0)[0]
    regs = {"A": cpu[8], "X": cpu[9], "Y": cpu[10], "SP": cpu[11], "PC": cpu[12] | (cpu[13] << 8), "FL": cpu[14]}
    major, _minor, mem = modules["C64MEM"]
    if major != 0 or len(mem) < 4 + 0x10000:
        raise SnapshotError(f"Unsupported memory data in {p.name} (C64MEM version {major})")
    return Snapshot(p, machine, version, regs, clock, bytes(mem[4:4 + 0x10000]), names,
                    {n: body for n, (_a, _b, body) in modules.items()})


# ---------------------------------------------------------------------- notes kept beside each .vsf

@dataclass
class Info:
    name: str
    note: str = ""
    created: float = field(default_factory=time.time)
    program: str = ""              # the .prg that was running
    program_stamp: str = ""        # its size and mtime, to spot a rebuilt program
    pc: int | None = None

    @classmethod
    def load(cls, vsf: Path) -> "Info":
        side = vsf.with_suffix(".json")
        try:
            d = json.loads(side.read_text())
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls(name=vsf.stem, created=vsf.stat().st_mtime if vsf.exists() else time.time())

    def save(self, vsf: Path) -> None:
        vsf.with_suffix(".json").write_text(json.dumps(asdict(self), indent=1))


def program_stamp(prg: Path | None) -> str:
    if not prg or not prg.exists():
        return ""
    st = prg.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def safe_name(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 _.-]", "_", name.strip())[:60].strip(" .")
    return s or "snapshot"


def unique_path(folder: Path, name: str) -> Path:
    base = safe_name(name)
    p = folder / f"{base}.vsf"
    n = 2
    while p.exists():
        p = folder / f"{base} ({n}).vsf"
        n += 1
    return p


def list_snapshots(folder: Path) -> list[tuple[Path, Info]]:
    if not folder.is_dir():
        return []
    out = [(p, Info.load(p)) for p in folder.glob("*.vsf")]
    return sorted(out, key=lambda pi: pi[1].created, reverse=True)


def delete_snapshot(vsf: Path) -> None:
    vsf.unlink(missing_ok=True)
    vsf.with_suffix(".json").unlink(missing_ok=True)


def rename_snapshot(vsf: Path, new_name: str) -> Path:
    info = Info.load(vsf)                       # read the notes before anything moves
    dest = unique_path(vsf.parent, new_name)
    vsf.rename(dest)
    vsf.with_suffix(".json").unlink(missing_ok=True)
    info.name = new_name.strip() or dest.stem
    info.save(dest)
    return dest


# ---------------------------------------------------------------------- comparing

@dataclass
class Diff:
    registers: dict[str, tuple[int, int]]       # name -> (before, after), changed only
    ranges: list[tuple[int, int]]               # changed RAM, inclusive, merged
    changed_bytes: int
    clock_delta: int


def compare(a: Snapshot, b: Snapshot, gap: int = 4) -> Diff:
    """What changed from a to b. Changed bytes up to `gap` apart are reported as one range."""
    regs = {k: (a.registers[k], b.registers[k]) for k in a.registers if a.registers[k] != b.registers.get(k)}
    ranges: list[tuple[int, int]] = []
    count = 0
    ra, rb = a.ram, b.ram
    i = 0
    while i < 0x10000:
        if ra[i] != rb[i]:
            count += 1
            if ranges and i - ranges[-1][1] <= gap:
                ranges[-1] = (ranges[-1][0], i)
            else:
                ranges.append((i, i))
        i += 1
    return Diff(regs, ranges, count, b.clock - a.clock)
