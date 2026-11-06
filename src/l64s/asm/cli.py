"""l64asm: command-line front end for the CBM prg Studio-compatible assembler.

  l64asm gameMain.asm                    # one file -> gameMain.prg
  l64asm chapter17.cbmprj                # a CBM prg Studio project, using its build list
  l64asm ch17.code-workspace             # a Kick Assembler (VS Code) project, built with Kick Assembler
  l64asm game.l64proj                    # any Linux64Studio project (Kick Assembler and C ones too)
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
    ap.add_argument("inputs", nargs="+", help=".asm files in build order, or a project (.cbmprj, .l64proj, "
                                              ".code-workspace)")
    ap.add_argument("-o", "--output", help="output .prg (default: project executable or first file's name)")
    ap.add_argument("-l", "--labels", help="write a VICE label file")
    ap.add_argument("--list", dest="listing", help="write a listing file")
    ap.add_argument("--srcmap", help="write an address->source map (JSON)")
    ap.add_argument("--debugdump", nargs="?", const="", metavar="FILE",
                    help="write a debug dump in Kick Assembler's format (default: the program's name, .dbg)")
    ap.add_argument("--raw", action="store_true", help="write a raw binary without the 2-byte load address")
    ap.add_argument("--d64", metavar="IMAGE", help="also write a disk image (.d64, .d71 or .d81) with the program")
    ap.add_argument("--disk-name", help='disk name and ID for --d64, e.g. "my game,mg"')
    ap.add_argument("--crt", metavar="TYPE", help="also write a cartridge (normal8, normal16, ultimax, magicdesk, "
                                                  "ocean, easyflash) next to the .prg")
    ap.add_argument("--illegal", action="store_true", help="allow undocumented 6510 opcodes")
    ap.add_argument("--case-sensitive", action="store_true", help="treat labels as case-sensitive")
    ap.add_argument("--text", choices=["auto", "screen", "petscii"], default="auto",
                    help="TEXT encoding: auto (\"...\" PETSCII, '...' screen codes, as CBM prg Studio), or force one")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)

    opts = Options(illegal_opcodes=a.illegal, case_sensitive=a.case_sensitive, text_encoding=a.text)
    inputs = [Path(p) for p in a.inputs]
    default_out: Path
    debug_dump = False                # the project's own setting
    if len(inputs) == 1 and inputs[0].suffix.lower() in (".cbmprj", ".l64proj", ".code-workspace"):
        from ..project.model import TOOLCHAIN_CBM, load_project
        proj = load_project(inputs[0])
        if proj.toolchain != TOOLCHAIN_CBM:
            # Kick Assembler and C (cc65): the whole project build, as the IDE does it (build events,
            # the assembler or compiler, music, the disk image)
            from ..project.build import build_project
            from ..settings import Settings
            settings = Settings.load()
            res = build_project(proj, kickass_jar=settings.kickass_jar, java=settings.java,
                                goattracker_dir=settings.goattracker_dir)
            if not a.quiet or not res.ok:
                print(res.log, file=sys.stderr if not res.ok else sys.stdout)
            for d in res.diagnostics:
                print(d, file=sys.stderr)
            if res.ok and not a.quiet and res.prg:
                print(f"{res.prg}: built")
            return 0 if res.ok else 1
        files = proj.build_paths()
        opts.padding_byte = proj.padding_byte
        default_out = proj.output_path()
        debug_dump = proj.debug_dump
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
    dbg = None
    if a.debugdump is not None or debug_dump:
        dbg = Path(a.debugdump) if a.debugdump else out.with_suffix(".dbg")
    write_outputs(result, out,
                  labels=Path(a.labels) if a.labels else None,
                  lst=Path(a.listing) if a.listing else None,
                  srcmap=Path(a.srcmap) if a.srcmap else None,
                  raw=a.raw, dbg=dbg)
    if not a.quiet and result.start is not None:
        print(f"{out}: ${result.start:04X}-${result.end - 1:04X} ({result.end - result.start} bytes, "
              f"{result.passes} passes)")
    if a.d64 and _write_d64(a.d64, a.disk_name, out, a.quiet):
        return 1
    if a.crt:
        from ..cart.crt import CartError, cartridge_from_files
        try:
            cart = cartridge_from_files(a.crt, out, out.stem, [])
        except CartError as e:
            print(f"l64asm: {e}", file=sys.stderr)
            return 1
        cart.save(out.with_suffix(".crt"))
        if not a.quiet:
            print(f"{out.with_suffix('.crt')}: {cart.type_name}, {cart.mode}")
    return 0


def _write_d64(image: str, header: str | None, prg: Path, quiet: bool) -> int:
    from ..disk.image import DiskError, build_disk
    name, _, disk_id = (header or prg.stem).partition(",")
    try:
        disk = build_disk(Path(image), name[:16], disk_id or "00", [(prg.stem[:16], prg.read_bytes(), "prg")])
    except DiskError as e:
        print(f"l64asm: {e}", file=sys.stderr)
        return 1
    if not quiet:
        print(f"{image}: {disk.blocks_free} blocks free")
    return 0


if __name__ == "__main__":
    sys.exit(main())
