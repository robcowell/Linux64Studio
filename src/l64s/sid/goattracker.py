"""GoatTracker integration: songs (.sng) and sound effects (.ins) made with GoatTracker 2 or
SidMonkey (the GTK4 edition at github.com/robcowell/goattracker), packed for your program with
its command-line tools.

  gt2reloc  packs a song with the playroutine at a chosen address: SID, PRG or BIN by the
            output file's extension. Entry points: init = start (A = subtune), play = start+3,
            sound effect = start+6 when sound effect support is on (A/Y = data, X = 0/7/14).
  ins2snd2  turns an instrument into sound effect data for the player's sound effect support.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SONG_EXTS = (".sng",)
SFX_EXTS = (".ins",)
TOOLS = ("goattrk2", "sidmonkey", "gt2reloc", "ins2snd2")
DEFAULT_DIRS = [Path.home() / "goattracker" / "linux", Path.home() / "goattracker" / "src"]


class MusicError(Exception):
    pass


def find_tool(name: str, folder: str = "") -> str | None:
    """A GoatTracker tool: from the configured folder, ~/goattracker/linux, then PATH."""
    dirs = ([Path(folder).expanduser()] if folder else []) + DEFAULT_DIRS
    for d in dirs:
        p = d / name
        if p.is_file() and p.stat().st_mode & 0o111:
            return str(p)
    return shutil.which(name)


# ---------------------------------------------------------------------- file headers

@dataclass
class SongInfo:
    format: str     # GTS5 etc.
    name: str
    author: str
    copyright: str
    subtunes: int


def read_song_info(path: str | Path) -> SongInfo:
    data = Path(path).read_bytes()[:101]
    if len(data) < 101 or data[:3] != b"GTS" or data[3:4] not in b"2345":
        if data[:4] == b"GTS!":
            return SongInfo("GTS!", "(GoatTracker 1 song)", "", "", 1)
        raise MusicError(f"{Path(path).name} isn't a GoatTracker 2 song")

    def text(b: bytes) -> str:
        return b.split(b"\0")[0].decode("latin-1").strip()
    return SongInfo(data[:4].decode(), text(data[4:36]), text(data[36:68]), text(data[68:100]), data[100])


def read_instrument_name(path: str | Path) -> str:
    data = Path(path).read_bytes()
    if data[:3] != b"GTI" or len(data) < 29:
        raise MusicError(f"{Path(path).name} isn't a GoatTracker instrument")
    return data[13:29].split(b"\0")[0].decode("latin-1").strip()


# ---------------------------------------------------------------------- packing songs

@dataclass
class PackOptions:
    address: int = 0x1000      # player start (page-aligned: gt2reloc takes the high byte)
    zeropage: int = 0xFC       # two consecutive zeropage bytes
    sfx: bool = False          # sound effect support (jsr start+6)
    volume: bool = False       # volume change support
    ntsc: bool = False
    author_info: bool = True   # store name/author in .sid headers
    extra: list[str] = field(default_factory=list)  # any other gt2reloc options, e.g. ["-B1"]

    @classmethod
    def from_dict(cls, d: dict) -> "PackOptions":
        return cls(address=int(d.get("address", 0x1000)), zeropage=int(d.get("zeropage", 0xFC)),
                   sfx=bool(d.get("sfx", False)), volume=bool(d.get("volume", False)),
                   ntsc=bool(d.get("ntsc", False)), author_info=bool(d.get("author_info", True)),
                   extra=list(d.get("extra", [])))

    def to_dict(self) -> dict:
        return {"address": self.address, "zeropage": self.zeropage, "sfx": self.sfx, "volume": self.volume,
                "ntsc": self.ntsc, "author_info": self.author_info, "extra": list(self.extra)}

    def args(self) -> list[str]:
        if self.address & 0xFF:
            raise MusicError(f"The player address ${self.address:04X} must start a page (end in 00)")
        if not 0 <= self.zeropage <= 0xFE:
            raise MusicError(f"Zeropage address ${self.zeropage:02X} needs two bytes below $100")
        a = [f"-W{self.address >> 8:02X}", f"-Z{self.zeropage:02X}", f"-D{int(self.sfx)}",
             f"-E{int(self.volume)}", f"-H{int(self.author_info)}", "-N" if self.ntsc else "-P"]
        return a + list(self.extra)

    def entry_points(self) -> dict[str, int]:
        e = {"init": self.address, "play": self.address + 3}
        if self.sfx:
            e["sfx"] = self.address + 6
        if self.volume:
            e["volume"] = self.address + (9 if self.sfx else 6)
        return e


@dataclass
class PackResult:
    output: Path
    log: str
    start: int
    size: int

    @property
    def end(self) -> int:
        return self.start + self.size


def pack_song(song: Path, output: Path, options: PackOptions, folder: str = "") -> PackResult:
    """Pack a song with gt2reloc. The output format follows the extension (.sid, .prg or .bin)."""
    tool = find_tool("gt2reloc", folder)
    if not tool:
        raise MusicError("gt2reloc not found: set the GoatTracker folder in Preferences")
    if not song.is_file():
        # gt2reloc doesn't fail on a missing song: it quietly packs an empty one.
        raise MusicError(f"Song {song.name} not found")
    if output.suffix.lower() not in (".sid", ".prg", ".bin"):
        raise MusicError(f"Packed music must be .sid, .prg or .bin, not {output.name}")
    args = options.args()
    output.parent.mkdir(parents=True, exist_ok=True)
    # gt2reloc takes bare file names, so run it in the song's folder with the output beside it.
    tmp = song.parent / f".l64s-pack{output.suffix.lower()}"
    try:
        proc = subprocess.run([tool, song.name, tmp.name, *args], cwd=song.parent, capture_output=True,
                              text=True, errors="replace", timeout=60)
        log = proc.stdout + proc.stderr
        if proc.returncode != 0 or not tmp.is_file():
            raise MusicError(f"gt2reloc failed packing {song.name}:\n{log.strip()}")
        m = re.search(r"song file:\s*(\S*)", log)
        if m is not None and not m.group(1):
            raise MusicError(f"gt2reloc couldn't load {song.name}")
        shutil.move(str(tmp), output)
    finally:
        tmp.unlink(missing_ok=True)
    size = int(m2.group(1)) if (m2 := re.search(r"Total size:\s*(\d+)", log)) else output.stat().st_size
    return PackResult(output, log, options.address, size)


# ---------------------------------------------------------------------- sound effects

def convert_sfx(instrument: Path, output: Path, label: str = "", folder: str = "", kickass: bool = False,
                c_project: bool = False) -> bytes:
    """Turn a GoatTracker instrument into sound effect data (ins2snd2).

    A .bin output gets the raw data; .asm/.s gets byte lines in the project's syntax (ins2snd2's
    own source output is DASM syntax, which neither assembler here reads). In a C project a .c gets
    a C array and a .s an exported ca65 table, both named ``label`` for C.
    """
    tool = find_tool("ins2snd2", folder)
    if not tool:
        raise MusicError("ins2snd2 not found: set the GoatTracker folder in Preferences")
    if not instrument.is_file():
        raise MusicError(f"Instrument {instrument.name} not found")
    tmp = output.parent / f".l64s-sfx-{output.stem}.bin"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run([tool, str(instrument), str(tmp), "-b"], capture_output=True, text=True,
                              errors="replace", timeout=30)
        if proc.returncode != 0 or not tmp.is_file():
            raise MusicError(f"ins2snd2 can't convert {instrument.name}: {(proc.stdout + proc.stderr).strip()}")
        data = tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)
    sfx = output.suffix.lower()
    name = label or re.sub(r"\W", "_", instrument.stem)
    if sfx == ".bin":
        output.write_bytes(data)
    elif c_project and sfx in (".c", ".s"):
        from ..syntax import C, CA65, table
        head = f"Sound effect from {instrument.name} (ins2snd2)"
        if sfx == ".c":
            output.write_text(table(C, name, data, comment_text=head))
        else:
            output.write_text(f"; {head}\n        .export _{name}\n        .segment \"RODATA\"\n"
                              + table(CA65, "_" + name, data))
    else:
        directive = ".byte" if kickass else "byte"
        lines = [f"{name}:" if kickass else name]
        lines += [f"        {directive} " + ", ".join(f"${b:02X}" for b in data[i:i + 16])
                  for i in range(0, len(data), 16)]
        output.write_text(("// " if kickass else "; ") + f"Sound effect from {instrument.name} (ins2snd2)\n"
                          + "\n".join(lines) + "\n")
    return data


# ---------------------------------------------------------------------- code to use it

def player_code(include: str, options: PackOptions, packed_as: str, kickass: bool = False) -> str:
    """Assembler source showing how to include packed music and call the player."""
    e = options.entry_points()
    a = options.address
    c = "//" if kickass else ";"
    if kickass:
        skip = {".sid": ", $7E", ".prg": ", 2", ".bin": ""}[packed_as]
        inc = f'*= ${a:04X} "Music"\n    .import binary "{include}"{skip}'
        ind = "    "
    else:
        skip = {".sid": ", 126", ".prg": ", 2", ".bin": ""}[packed_as]
        inc = f"*=${a:04X}\n        incbin {include}{skip}"
        ind = "        "
    out = [f"{c} Music packed by GoatTracker's gt2reloc at ${a:04X}", inc, "",
           f"{c} Once, at start-up:", f"{ind}lda #0{'' if kickass else '      '}  {c} subtune number, from 0",
           f"{ind}jsr ${e['init']:04X}", "", f"{c} Every frame (e.g. in your raster interrupt):",
           f"{ind}jsr ${e['play']:04X}"]
    if "sfx" in e:
        out += ["", f"{c} Play a sound effect:", f"{ind}lda #<effect", f"{ind}ldy #>effect",
                f"{ind}ldx #14{'' if kickass else '     '}  {c} channel: 0, 7 or 14 for voices 1-3",
                f"{ind}jsr ${e['sfx']:04X}"]
    if "volume" in e:
        out += ["", f"{c} Change the volume:", f"{ind}lda #15{'' if kickass else '     '}  {c} 0-15",
                f"{ind}jsr ${e['volume']:04X}"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- editors

def launch_editor(which: str, path: Path | None = None, folder: str = "") -> subprocess.Popen:
    """Open a song (or nothing) in GoatTracker GTK Edition ("goattrk2") or SidMonkey."""
    tool = find_tool(which, folder)
    if not tool:
        raise MusicError(f"{which} not found: set the GoatTracker folder in Preferences")
    # GoatTracker loads songs by bare name from the current folder (its name buffer is short).
    args = [tool] + ([path.name] if path else [])
    return subprocess.Popen(args, cwd=str(path.parent) if path else None, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
