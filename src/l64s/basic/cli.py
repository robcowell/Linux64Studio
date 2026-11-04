"""l64bas: Commodore BASIC V2 tokenizer, lister and renumberer.

  l64bas game.bas                      # tokenize -> game.prg
  l64bas game.bas -o out.prg
  l64bas --list game.prg               # detokenize to stdout (or -o game.bas)
  l64bas --renumber game.bas [--start 10 --step 10]   # rewrite game.bas in place
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
    ap.add_argument("--load-address", type=lambda s: int(s, 0), default=0x0801)
    a = ap.parse_args(argv)
    src = Path(a.input)
    try:
        if a.list:
            text = detokenize(src.read_bytes())
            if a.output:
                Path(a.output).write_text(text)
            else:
                sys.stdout.write(text)
            return 0
        text = src.read_text(encoding="utf-8-sig")
        if a.renumber:
            new, warnings = renumber(text, a.start, a.step)
            _report("warning", warnings, a.input)
            (Path(a.output) if a.output else src).write_text(new)
            return 0
        res = tokenize(text, a.load_address)
        _report("warning", res.warnings, a.input)
        out = Path(a.output) if a.output else src.with_suffix(".prg")
        out.write_bytes(res.prg())
        print(f"{out}: {len(res.lines)} lines, ${res.start:04X}-${res.end - 1:04X}")
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
