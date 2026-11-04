"""l64bin: binary import and export.

  l64bin import game.prg --as disasm [--trace] [-o game.asm]
  l64bin import data.bin --load c000 --as data [--label tbl] [--per-line 8]
  l64bin import data.bin --load c000 --as basic [--line 1000 --step 10 --no-loader]
  l64bin export game.prg --from 3000 --to 37ff -o sprites.bin [--prg]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .binconv import (ConvertError, basic_sys_address, disassemble_to_source, export_range, load_binary,
                      to_asm_data, to_basic_data)


def _hex(s: str) -> int:
    return int(s.lstrip("$").removeprefix("0x"), 16)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l64bin", description="Binary import and export")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import", help="turn a binary into source")
    i.add_argument("file")
    i.add_argument("--as", dest="fmt", choices=["disasm", "data", "basic"], default="disasm")
    i.add_argument("--load", type=_hex, help="load address in hex (a .prg carries its own)")
    i.add_argument("--skip", type=int, default=0)
    i.add_argument("--length", type=int)
    i.add_argument("--trace", action="store_true", help="disassemble only code reachable from the entry points")
    i.add_argument("--entry", type=_hex, action="append", help="entry point (hex); default: SYS address or start")
    i.add_argument("--kickass", action="store_true")
    i.add_argument("--label", default="")
    i.add_argument("--per-line", type=int, default=16)
    i.add_argument("--radix", choices=["hex", "dec", "bin"], default="hex")
    i.add_argument("--line", type=int, default=1000)
    i.add_argument("--step", type=int, default=10)
    i.add_argument("--no-loader", action="store_true")
    i.add_argument("-o", "--output")
    e = sub.add_parser("export", help="write part of a .prg's memory to a file")
    e.add_argument("prg")
    e.add_argument("--from", dest="start", type=_hex, required=True)
    e.add_argument("--to", dest="end", type=_hex, required=True)
    e.add_argument("--prg-out", "--prg", dest="with_load", action="store_true", help="add a load address")
    e.add_argument("-o", "--output", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "import":
            b = load_binary(a.file, a.load, a.skip, a.length)
            if a.fmt == "disasm":
                entries = None
                if a.trace or a.entry:
                    entries = a.entry or [basic_sys_address(b) or b.start]
                text = disassemble_to_source(b, entries, a.kickass).source
            elif a.fmt == "data":
                text = to_asm_data(b, a.label, a.per_line, a.radix, a.kickass)
            else:
                text = to_basic_data(b, a.line, a.step, a.per_line, not a.no_loader)
            if a.output:
                Path(a.output).write_text(text)
            else:
                sys.stdout.write(text)
        else:
            b = load_binary(a.prg)
            mem = bytearray(0x10000)
            mem[b.start:b.end] = b.data
            Path(a.output).write_bytes(export_range(mem, a.start, a.end, a.with_load))
            print(f"{a.output}: ${a.start:04X}-${a.end:04X}")
        return 0
    except (ConvertError, OSError, ValueError) as err:
        print(f"l64bin: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
