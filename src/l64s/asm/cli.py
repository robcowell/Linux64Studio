"""l64asm: command-line front end for the CBM prg Studio-compatible assembler.

  l64asm gameMain.asm                    # one file -> gameMain.prg
  l64asm chapter17.cbmprj                # a CBM prg Studio project, using its build list
  l64asm a.asm b.asm -o game.prg -l game.vs --list game.lst
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .assembler import Assembler, Options
from .output import write_outputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l64asm", description="6502 assembler compatible with CBM prg Studio syntax")
    ap.add_argument("inputs", nargs="+", help=".asm files in build order, or a .cbmprj/.l64proj project")
    ap.add_argument("-o", "--output", help="output .prg (default: project executable or first file's name)")
    ap.add_argument("-l", "--labels", help="write a VICE label file")
    ap.add_argument("--list", dest="listing", help="write a listing file")
    ap.add_argument("--srcmap", help="write an address->source map (JSON)")
    ap.add_argument("--raw", action="store_true", help="write a raw binary without the 2-byte load address")
    ap.add_argument("--illegal", action="store_true", help="allow undocumented 6510 opcodes")
    ap.add_argument("--case-sensitive", action="store_true", help="treat labels as case-sensitive")
    ap.add_argument("--text", choices=["screen", "petscii"], default="screen", help="TEXT directive encoding")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)

    opts = Options(illegal_opcodes=a.illegal, case_sensitive=a.case_sensitive, text_encoding=a.text)
    inputs = [Path(p) for p in a.inputs]
    default_out: Path
    if len(inputs) == 1 and inputs[0].suffix.lower() in (".cbmprj", ".l64proj"):
        from ..project.model import load_project
        proj = load_project(inputs[0])
        files = proj.build_paths()
        opts.padding_byte = proj.padding_byte
        default_out = proj.output_path()
    else:
        files = inputs
        default_out = inputs[0].with_suffix(".prg")

    result = Assembler(opts).assemble_files(files)
    for d in result.diagnostics:
        print(d, file=sys.stderr)
    if not result.ok:
        print(f"l64asm: {len(result.errors)} error(s)", file=sys.stderr)
        return 1
    out = Path(a.output) if a.output else default_out
    write_outputs(result, out,
                  labels=Path(a.labels) if a.labels else None,
                  lst=Path(a.listing) if a.listing else None,
                  srcmap=Path(a.srcmap) if a.srcmap else None,
                  raw=a.raw)
    if not a.quiet and result.start is not None:
        print(f"{out}: ${result.start:04X}-${result.end - 1:04X} ({result.end - result.start} bytes, "
              f"{result.passes} passes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
