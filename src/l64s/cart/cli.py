"""l64cart: make and inspect C64 cartridge images (.crt).

  l64cart make normal8 cart.prg -o game.crt [--name "MY GAME"]
  l64cart make ocean boot.prg --bank level1.bin --bank level2.bin -o game.crt
  l64cart info game.crt
  l64cart types
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .crt import CART_TYPES, CartError, cartridge_from_files, load_crt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l64cart", description="C64 cartridge (.crt) tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="make a .crt from a program (bank 0) and optional bank files")
    mk.add_argument("type", choices=list(CART_TYPES))
    mk.add_argument("program", help=".prg assembled at the cartridge's address ($8000, or $E000 for Ultimax)")
    mk.add_argument("-o", "--output")
    mk.add_argument("--name", default="")
    mk.add_argument("--bank", action="append", default=[], help="data file for the next banks (repeatable)")
    info = sub.add_parser("info", help="describe a .crt")
    info.add_argument("crt")
    sub.add_parser("types", help="list the cartridge types")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "types":
            for k, t in CART_TYPES.items():
                print(f"{k:<10} {t.label}")
        elif a.cmd == "make":
            prg = Path(a.program)
            cart = cartridge_from_files(a.type, prg, a.name or prg.stem, [Path(b) for b in a.bank])
            out = Path(a.output or prg.with_suffix(".crt"))
            cart.save(out)
            print(f"{out}: {cart.type_name}, {cart.mode}, {len({c.bank for c in cart.chips})} bank(s), "
                  f"{cart.size // 1024}K")
        else:
            cart = load_crt(a.crt)
            print(f"Name: {cart.name}\nType: {cart.type_name} (hardware {cart.hardware})\n"
                  f"Mode: {cart.mode} (EXROM {cart.exrom}, GAME {cart.game})\nSize: {cart.size // 1024}K")
            for c in cart.chips:
                print(f"  bank {c.bank:<3} ${c.address:04X} {len(c.data):>6} bytes")
        return 0
    except (CartError, OSError) as e:
        print(f"l64cart: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
