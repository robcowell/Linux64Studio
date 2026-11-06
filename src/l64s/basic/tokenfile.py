"""User-defined BASIC tokens (CBM prg Studio's token files): a `.tkn` file lists keywords and the
token each is crunched to, so a BASIC extension's keywords (Super Expander's GRAPHIC, a cartridge's
own) can be tokenized, or a keyword given another token. A BASIC file uses one by starting with

    tokenfile mytokens.tkn

(relative to the BASIC file's folder; ".tkn" is added if there's no extension).

The file is CSV: `KEYWORD, token in hex[, abbreviation]` a line; blank lines and lines starting
with # are skipped. A token can be two bytes (FE02), as the Mega65's are. The file's keywords are
tried first, in its order (so a keyword that starts another, PRINT# and PRINT, must come first),
then BASIC V2's that it doesn't name, so a file of just an extension's keywords works as well as a
whole table. Abbreviations work as the C64's do (a lower-case letter then a capital ends one).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .tokenizer import KEYWORDS, BasicError

_LINE = re.compile(r"^\s*tokenfile\s+(.+?)\s*$", re.I)


@dataclass(frozen=True)
class Token:
    keyword: str          # as written: GRAPHIC, PRINT#
    value: bytes          # 1 byte, or 2 (Mega65)
    abbreviation: str = ""


def tokenfile_line(line: str) -> str | None:
    """The file named by a `tokenfile` line, or None."""
    m = _LINE.match(line)
    return m.group(1).strip().strip('"') if m else None


def parse(text: str, name: str = "") -> list[Token]:
    out, seen = [], set()
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0]:
            raise BasicError(f"{name or 'token file'} line {n}: write KEYWORD, token in hex", n, name)
        kw, val = parts[0], parts[1].lstrip("$")
        if not re.fullmatch(r"[0-9A-Fa-f]{2}|[0-9A-Fa-f]{4}", val):
            raise BasicError(f"{name or 'token file'} line {n}: {parts[1]!r} isn't a token in hex (80-FF)", n, name)
        value = bytes.fromhex(val)
        if (len(value) == 1 and value[0] < 0x80) or value[0] == 0 or 0 in value:
            # (a two-byte token may start lower: Simons' Basic's are $64 xx; none may hold a $00, which
            # would end its line)
            raise BasicError(f"{name or 'token file'} line {n}: a token is $80 or more (or two bytes, neither "
                             f"$00), not ${val}", n, name)
        if kw.lower() in seen:
            raise BasicError(f"{name or 'token file'} line {n}: {kw} is in the file twice", n, name)
        seen.add(kw.lower())
        out.append(Token(kw, value, parts[2] if len(parts) > 2 else ""))
    return out


def load(path: Path) -> list[Token]:
    try:
        return parse(Path(path).read_text(encoding="utf-8-sig", errors="replace"), Path(path).name)
    except OSError as e:
        raise BasicError(f"Can't read the token file {Path(path).name}: {e.strerror}") from None


BUILTIN = Path(__file__).resolve().parent.parent / "data" / "tokens"


def builtin() -> dict[str, Path]:
    """The token files Linux64Studio comes with, one for each C64 BASIC extension VICE's petcat knows
    (tools/gen-basic-tokens.py made them): {name: path}, simons-basic say."""
    return {p.stem: p for p in sorted(BUILTIN.glob("*.tkn"))}


def builtin_title(path: Path) -> str:
    """A shipped file's extension's name, from its first line ("Simons' Basic")."""
    try:
        first = path.read_text(errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return path.stem
    return first.lstrip("# ").split(" (C64)")[0]


def find(name: str, folder: Path) -> Path:
    """The token file a `tokenfile` line names: in the BASIC file's folder, else one Linux64Studio
    comes with (tokenfile simons-basic)."""
    p = Path(name).expanduser()
    if not p.suffix:
        p = p.with_suffix(".tkn")
    found = p if p.is_absolute() else Path(folder) / p
    if not found.exists() and not p.is_absolute() and (BUILTIN / p.name).exists():
        return BUILTIN / p.name
    return found


def candidates(prg: bytes) -> list[str]:
    """The shipped BASIC extensions whose keywords account for every byte of a tokenized program
    that BASIC V2 can't list (outside strings and REMs). Empty if V2 lists it all, or none fits.
    Several often fit: most extensions put their tokens at $CC on."""
    from .tokenizer import BasicError, _extension_tokens
    lines = _program_lines(prg)
    if lines is None or not any(_unknown(line, {}, {}) for line in lines):
        return []
    out = []
    for name, path in builtin().items():
        try:
            one, two = _extension_tokens(load(path))
        except BasicError:
            continue
        if sum(_unknown(line, one, two) for line in lines) == 0:
            out.append(name)
    return out


def guess(prg: bytes) -> str | None:
    """The one shipped BASIC extension a program fits (candidates), or None if none or several do."""
    found = candidates(prg)
    return found[0] if len(found) == 1 else None


def _program_lines(prg: bytes) -> list[bytes] | None:
    if len(prg) < 4:
        return None
    start, mem = prg[0] | prg[1] << 8, prg[2:]
    out, off = [], 0
    while off + 4 <= len(mem) and len(out) < 10000:
        link = mem[off] | mem[off + 1] << 8
        if link == 0:
            break
        end = mem.find(b"\0", off + 4)
        if end < 0:
            return None
        out.append(mem[off + 4:end])
        nxt = link - start
        off = nxt if nxt > off else end + 1
    return out


def _unknown(line: bytes, one: dict, two: dict) -> int:
    """Bytes in a crunched line that neither BASIC V2 nor the extension's tokens account for."""
    n, i, in_quote, in_rem = 0, 0, False, False
    while i < len(line):
        b = line[i]
        i += 1
        if b == 0x22:
            in_quote = not in_quote
            continue
        if in_quote or in_rem:
            continue
        if i < len(line) and (b, line[i]) in two:
            i += 1
            continue
        if b in one:
            in_rem = one[b] == "rem"
            continue
        if b == 0x8F:                              # REM
            in_rem = True
        elif 0x80 <= b <= 0xCB or b == 0xFF or 0x20 <= b <= 0x5F:
            continue
        else:
            n += 1
    return n


def table(tokens: list[Token]) -> list[tuple[bytes, int | bytes, str]]:
    """The tokenizer's keyword table: (keyword as PETSCII, its token, keyword in lower case)."""
    def petscii(kw: str) -> bytes:
        return bytes(ord(c) - 32 if "a" <= c <= "z" else ord(c) for c in kw.lower())
    out = []
    named = set()
    for t in tokens:
        named.add(t.keyword.lower())
        out.append((petscii(t.keyword), t.value[0] if len(t.value) == 1 else t.value, t.keyword.lower()))
    for i, kw in enumerate(KEYWORDS):
        if kw not in named:
            out.append((petscii(kw), 0x80 + i, kw))
    return out


def default_text(project: str = "") -> str:
    """A token file with BASIC V2's tokens, to edit (Tools → Create Token File)."""
    from .reformat import ABBREVIATIONS
    lines = [f"# BASIC V2 tokens{' for ' + project if project else ''}.",
             "# <keyword>,<token value (in hex)>,<abbreviation (if there is one)>",
             "#",
             "# A keyword that starts another must come before it (PRINT# before PRINT).",
             "# Add an extension's keywords (GRAPHIC, CD) and use it with: tokenfile <this file>",
             "# Blank lines and lines starting with # are skipped.", ""]
    for i, kw in enumerate(KEYWORDS):
        tok = 0x80 + i
        ab = ABBREVIATIONS.get(tok, kw)
        lines.append(f"{kw.upper()}, {tok:02X}" + (f", {ab}" if ab != kw else ""))
    return "\n".join(lines) + "\n"
