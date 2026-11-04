"""l64bas: Commodore BASIC V2 tokenizer, lister and renumberer.

  l64bas game.bas                      # tokenize -> game.prg
  l64bas game.bas -o out.prg
  l64bas --list game.prg               # detokenize to stdout (or -o game.bas)
  l64bas --list --codes tok64 game.prg # control codes as Tok64/petcat ({clr}) or bastext ({cm a})
  l64bas --renumber game.bas [--start 10 --step 10]   # rewrite game.bas in place
  l64bas game.pbas [--start 10 --step 10 --prefix @]  # pBASIC (no line numbers) -> game.prg
  l64bas --preview game.pbas           # the numbered BASIC it makes, to stdout (or -o game.bas)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .renumber import renumber
from .tokenizer import BasicError, BasicErrors, detokenize, tokenize


def _report(prefix: str, errs: list[BasicError], file: str) -> None:
    for e in errs:
        where = f"{file}:{e.line}: " if e.line else f"{file}: "
        print(f"{where}{prefix}: {e.message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="l64bas", description="Commodore BASIC V2 tokenizer")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--list", action="store_true", help="detokenize a .prg into BASIC source")
    ap.add_argument("--renumber", action="store_true", help="renumber the source file in place")
    ap.add_argument("--start", type=lambda s: int(s, 0), default=10)
    ap.add_argument("--step", type=lambda s: int(s, 0), default=10)
    ap.add_argument("--prefix", default="@", help="pBASIC's label prefix")
    ap.add_argument("--codes", choices=["standard", "bastext", "tok64"], default="standard",
                    help="how --list writes control codes")
    ap.add_argument("--preview", action="store_true", help="print the numbered BASIC a .pbas file makes")
    ap.add_argument("--load-address", type=lambda s: int(s, 0), default=0x0801)
    ap.add_argument("--d64", metavar="IMAGE", help="also write a disk image (.d64, .d71 or .d81) with the program")
    ap.add_argument("--disk-name", help='disk name and ID for --d64, e.g. "my game,mg"')
    a = ap.parse_args(argv)
    src = Path(a.input)
    conv = None                       # a .pbas file's numbering, to give errors its own lines
    try:
        if a.list:
            text = detokenize(src.read_bytes(), style=a.codes)
            if a.output:
                Path(a.output).write_text(text)
            else:
                sys.stdout.write(text)
            return 0
        text = src.read_text(encoding="utf-8-sig")
        if src.suffix.lower() == ".pbas":
            from .pbasic import PBasicOptions, to_basic
            try:
                conv = to_basic(text, PBasicOptions(a.start, a.step, a.prefix))
                text = conv.text
            except BasicErrors as e:
                _report("error", e.errors, a.input)
                return 1
            if a.preview:
                if a.output:
                    Path(a.output).write_text(text)
                else:
                    sys.stdout.write(text)
                return 0
            if a.renumber:
                print("l64bas: pBASIC has no line numbers to renumber (use --start and --step)", file=sys.stderr)
                return 1
        if a.renumber:
            new, warnings = renumber(text, a.start, a.step)
            _report("warning", warnings, a.input)
            (Path(a.output) if a.output else src).write_text(new)
            return 0
        try:
            res = tokenize(text, a.load_address)
        except BasicErrors as e:
            for err in e.errors:
                err.line = conv.source_line(err.line) if conv else err.line
            raise
        for w in res.warnings:
            w.line = conv.source_line(w.line) if conv else w.line
        _report("warning", res.warnings, a.input)
        out = Path(a.output) if a.output else src.with_suffix(".prg")
        out.write_bytes(res.prg())
        print(f"{out}: {len(res.lines)} lines, ${res.start:04X}-${res.end - 1:04X}")
        if a.d64:
            from ..asm.cli import _write_d64
            return _write_d64(a.d64, a.disk_name, out, False)
        return 0
    except BasicErrors as e:
        _report("error", e.errors, a.input)
        return 1
    except BasicError as e:
        _report("error", [e], a.input)
        return 1
    except OSError as e:
        print(f"l64bas: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
