"""l64disk: create and work with 1541 disk images (.d64).

  l64disk create game.d64 "my game,mg" game.prg [more files...]
  l64disk list game.d64
  l64disk add game.d64 hiscores.seq [--name HISCORES --type seq]
  l64disk extract game.d64 GAME [-o game.prg]
  l64disk delete game.d64 GAME
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .d64 import D64, DiskError, build_disk, file_type_for


def _split_header(header: str) -> tuple[str, str]:
    name, _, disk_id = header.partition(",")
    return name, (disk_id or "00")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l64disk", description="1541 disk image (.d64) tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="make a new disk image")
    c.add_argument("image")
    c.add_argument("header", help='disk name and ID, e.g. "my game,mg"')
    c.add_argument("files", nargs="*", help="files to put on the disk (name = file name without extension)")
    lst = sub.add_parser("list", help="show the directory")
    lst.add_argument("image")
    a = sub.add_parser("add", help="add a file")
    a.add_argument("image")
    a.add_argument("file")
    a.add_argument("--name", help="name on the disk (default: file name without extension)")
    a.add_argument("--type", choices=["prg", "seq", "usr"])
    a.add_argument("--replace", action="store_true")
    x = sub.add_parser("extract", help="copy a file off the disk")
    x.add_argument("image")
    x.add_argument("name")
    x.add_argument("-o", "--output")
    d = sub.add_parser("delete", help="scratch a file")
    d.add_argument("image")
    d.add_argument("name")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "create":
            name, disk_id = _split_header(args.header)
            files = [(Path(f).stem[:16], Path(f).read_bytes(), file_type_for(Path(f))) for f in args.files]
            disk = build_disk(Path(args.image), name, disk_id, files)
            print(f"{args.image}: {len(files)} file(s), {disk.blocks_free} blocks free")
        elif args.cmd == "list":
            sys.stdout.write(D64.load(args.image).listing())
        elif args.cmd == "add":
            disk = D64.load(args.image)
            src = Path(args.file)
            disk.add_file(args.name or src.stem[:16], src.read_bytes(), args.type or file_type_for(src),
                          replace=args.replace)
            disk.validate()
            disk.save(args.image)
        elif args.cmd == "extract":
            disk = D64.load(args.image)
            e = disk.find(args.name)
            if e is None:
                raise DiskError(f"File '{args.name}' not found")
            out = Path(args.output or f"{e.name.lower()}.{e.file_type}")
            out.write_bytes(disk.read_file(e))
            print(f"{out}: {e.blocks} blocks")
        elif args.cmd == "delete":
            disk = D64.load(args.image)
            disk.delete(args.name)
            disk.save(args.image)
        return 0
    except (DiskError, OSError) as e:
        print(f"l64disk: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
