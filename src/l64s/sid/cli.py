"""l64sid: SID music files and GoatTracker songs from the command line.

  l64sid info tune.sid                    # header, memory, init/play
  l64sid extract tune.sid -o music.bin    # the music data (.bin) or with load address (.prg)
  l64sid pack song.sng music.bin --address 1000 --zeropage fc [--sfx] [--volume] [--ntsc]
  l64sid sfx effect.ins effect.asm [--label shot] [--kickass]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .goattracker import MusicError, PackOptions, convert_sfx, pack_song, player_code
from .sidfile import SidError, load_sid, usage_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l64sid", description="SID music tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("info", help="describe a .sid")
    i.add_argument("sid")
    i.add_argument("--kickass", action="store_true", help="show Kick Assembler code")
    x = sub.add_parser("extract", help="write a .sid's music as .bin or .prg")
    x.add_argument("sid")
    x.add_argument("-o", "--output")
    p = sub.add_parser("pack", help="pack a GoatTracker song with gt2reloc")
    p.add_argument("song")
    p.add_argument("output", help=".bin, .prg or .sid")
    p.add_argument("--address", default="1000", help="player address in hex (a page start)")
    p.add_argument("--zeropage", default="fc")
    p.add_argument("--sfx", action="store_true")
    p.add_argument("--volume", action="store_true")
    p.add_argument("--ntsc", action="store_true")
    p.add_argument("--goattracker", default="", help="folder with gt2reloc")
    s = sub.add_parser("sfx", help="convert a GoatTracker instrument to sound effect data")
    s.add_argument("instrument")
    s.add_argument("output", help=".asm (byte lines) or .bin")
    s.add_argument("--label", default="")
    s.add_argument("--kickass", action="store_true")
    s.add_argument("--goattracker", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "info":
            t = load_sid(a.sid)
            print(f"{t.magic} v{t.version}: {t.name} / {t.author} / {t.released}")
            print(f"Memory ${t.load:04X}-${t.end - 1:04X}, init ${t.init:04X}, play ${t.play:04X}, "
                  f"{t.songs} tune(s), {t.clock}, SID {t.model}\n")
            print(usage_code(t, Path(a.sid).name if a.kickass else Path(a.sid).with_suffix(".bin").name, a.kickass))
        elif a.cmd == "extract":
            t = load_sid(a.sid)
            out = Path(a.output or Path(a.sid).with_suffix(".bin"))
            out.write_bytes(t.prg() if out.suffix.lower() == ".prg" else t.data)
            print(f"{out}: ${t.load:04X}-${t.end - 1:04X}")
        elif a.cmd == "pack":
            opts = PackOptions(address=int(a.address.lstrip("$"), 16), zeropage=int(a.zeropage.lstrip("$"), 16),
                               sfx=a.sfx, volume=a.volume, ntsc=a.ntsc)
            r = pack_song(Path(a.song), Path(a.output), opts, a.goattracker)
            print(f"{r.output}: ${r.start:04X}-${r.end - 1:04X} ({r.size} bytes)\n")
            print(player_code(r.output.name, opts, r.output.suffix.lower()))
        else:
            data = convert_sfx(Path(a.instrument), Path(a.output), a.label, a.goattracker, a.kickass)
            print(f"{a.output}: {len(data)} bytes")
        return 0
    except (SidError, MusicError, OSError, ValueError) as e:
        print(f"l64sid: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
