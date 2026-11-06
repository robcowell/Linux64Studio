#!/usr/bin/env python3
"""Make the token files (.tkn) for C64 BASIC extensions, from VICE's petcat, into
src/l64s/data/tokens/. petcat knows each extension's keywords; tokenizing a line of each with
petcat -w<dialect> gives its token. Run it again after a new VICE adds dialects; the files are
shipped, so petcat isn't needed to use them.

    python3 tools/gen-basic-tokens.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "l64s" / "data" / "tokens"
V2 = {"end", "for", "next", "data", "input#", "input", "dim", "read", "let", "goto", "run", "if", "restore",
      "gosub", "return", "rem", "stop", "on", "wait", "load", "save", "verify", "def", "poke", "print#", "print",
      "cont", "list", "clr", "cmd", "sys", "open", "close", "get", "new", "tab(", "to", "fn", "spc(", "then",
      "not", "step", "+", "-", "*", "/", "^", "and", "or", ">", "=", "<", "sgn", "int", "abs", "usr", "fre",
      "pos", "sqr", "rnd", "log", "exp", "cos", "sin", "tan", "atn", "peek", "len", "str$", "val", "asc",
      "chr$", "left$", "right$", "mid$", "go", "~"}


V2_ORDER = ["end", "for", "next", "data", "input#", "input", "dim", "read", "let", "goto", "run", "if", "restore",
            "gosub", "return", "rem", "stop", "on", "wait", "load", "save", "verify", "def", "poke", "print#",
            "print", "cont", "list", "clr", "cmd", "sys", "open", "close", "get", "new", "tab(", "to", "fn", "spc(",
            "then", "not", "step", "+", "-", "*", "/", "^", "and", "or", ">", "=", "<", "sgn", "int", "abs", "usr",
            "fre", "pos", "sqr", "rnd", "log", "exp", "cos", "sin", "tan", "atn", "peek", "len", "str$", "val",
            "asc", "chr$", "left$", "right$", "mid$", "go"]       # BASIC V2's, in ROM order ($80 on)


def dialects() -> list[tuple[str, str]]:
    """(petcat's code, the extension's name) for each C64 one."""
    text = subprocess.run(["petcat", "-help"], capture_output=True, text=True).stdout
    out = []
    for m in re.finditer(r"^\s+(\S+)\s+Basic v2\.0 with (.+) \(C64\)$", text, re.M):
        out.append((m.group(1), m.group(2).strip()))
    return out


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


symbols: list[str] = []


def keywords(code: str) -> list[str]:
    text = subprocess.run(["petcat", f"-k{code}"], capture_output=True, text=True).stdout
    symbols.clear()
    words = [w.strip() for line in text.splitlines() if "Available Keywords" not in line for w in line.split("\t")]
    seen, out = set(), []
    for w in words:
        if w and w != ">>" and w not in V2 and w not in seen and "," not in w and any(c.isalpha() for c in w):
            seen.add(w)
            out.append(w)
        elif w and w != ">>" and w not in V2 and not any(c.isalpha() for c in w) and w not in symbols:
            symbols.append(w)
    return out


dropped: list[str] = []


def tokens(code: str, words: list[str]) -> dict[str, bytes]:
    """Each keyword's token, as petcat crunches a line holding just it."""
    with tempfile.TemporaryDirectory() as d:
        src, prg = Path(d) / "k.txt", Path(d) / "k.prg"
        src.write_text("".join(f"{10 + i} {w}\n" for i, w in enumerate(words)))
        subprocess.run(["petcat", f"-w{code}", "-o", str(prg), "--", str(src)], check=True,
                       capture_output=True)
        prg_bytes = prg.read_bytes()
    start = prg_bytes[0] | prg_bytes[1] << 8
    data = prg_bytes[2:]
    out, off = {}, 0
    while off + 4 <= len(data) and (data[off] or data[off + 1]):
        nxt = (data[off] | data[off + 1] << 8) - start          # lines by their links (a token may hold $00)
        number = data[off + 2] | data[off + 3] << 8
        body = data[off + 4:nxt - 1]
        word = words[number - 10]
        # only a keyword that crunches to a token on its own (two bytes at most) goes in, and not one
        # with a $00 in it, which would end the line it's in
        if 1 <= len(body) <= 2 and (body[0] >= 0x80 or len(body) == 2) and 0 not in body:
            out[word] = body
        elif 0 in body:
            dropped.append(word)
        off = nxt
    return out


def start_address(code: str) -> int:
    """Where programs for the extension start (petcat writes them there: not always $0801)."""
    with tempfile.TemporaryDirectory() as d:
        src, prg = Path(d) / "s.txt", Path(d) / "s.prg"
        src.write_text("10 print\n")
        subprocess.run(["petcat", f"-w{code}", "-o", str(prg), "--", str(src)], check=True, capture_output=True)
        data = prg.read_bytes()
    return data[0] | data[1] << 8


def ordered(words: list[str]) -> list[str]:
    """A keyword that starts another comes after it. The tokenizer tries them in order, so that way
    it takes the longest keyword that matches, as petcat does (V2's NEXT, not an extension's NE;
    Simons' END PROC, not V2's END)."""
    out = list(words)
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(out):
            for j in range(i + 1, len(out)):
                if out[j].startswith(a) and out[j] != a:
                    out.insert(i, out.pop(j))
                    changed = True
                    break
            if changed:
                break
    return out


def main() -> int:
    version = subprocess.run(["petcat", "-version"], capture_output=True, text=True).stdout.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    for code, name in dialects():
        words = keywords(code)
        dropped.clear()
        toks = tokens(code, words)
        start = start_address(code)
        lines = [f"# {name} (C64): its keywords and tokens, from {version}: petcat -w{code}.",
                 "# Use it in a BASIC file with: tokenfile " + slug(name),
                 "# BASIC V2's keywords are here too, so the longest keyword that matches is the one taken."]
        if start != 0x0801:
            lines.append(f"# Its programs start at ${start:04X}, not $0801: build them with that load address.")
        if dropped:
            lines.append(f"# Left out, as their tokens hold a $00 (which ends a line): {', '.join(dropped)}")
        if symbols:
            lines.append(f"# Left out, as they're only symbols (so * stays BASIC V2's multiply): {' '.join(symbols)}")
        lines.append("")
        v2 = {kw: bytes([0x80 + i]) for i, kw in enumerate(V2_ORDER)}
        everything = {**v2, **{w: toks[w] for w in words if w in toks}}
        for w in ordered(list(v2) + [w for w in words if w in toks]):
            lines.append(f"{w.upper()}, {everything[w].hex().upper()}")
        (OUT / f"{slug(name)}.tkn").write_text("\n".join(lines) + "\n")
        print(f"{slug(name)}.tkn: {len(toks)} keywords ({name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
