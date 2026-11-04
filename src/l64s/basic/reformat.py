"""Reformatting BASIC (CBM prg Studio's Reformat BASIC Code, and its Compress and Uncompress).

General formatting: a space after the line number, blank lines removed, the case of quoted
strings and of REMs changed. Source compression: REMs removed, spaces removed (outside strings,
and in REMs if wanted), zeros taken out of DATA (`data 0,0.5` → `data ,.5`, which READ reads the
same). Expand: keywords in full with a space round them (`?a` → `print a`). Compress writes
keywords abbreviated (`print` → `?`, `poke` → `pO`), Uncompress in full.

Only the text that matters is touched: strings, {codes} and REMs are left as they're written. Each
changed line is tokenized before and after: if it would do anything different (beyond what the
options ask for: strings' case, REMs, DATA zeros), it's left as it was, with a warning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .renumber import find_line_refs
from .tokenizer import (DATA, KEYWORDS, PRINT, REM, BasicError, _source_bytes, crunch, match_keyword)

_NUMBERED = re.compile(r"^(\s*)(\d+)(\s*)(.*)$")
_SKIP = re.compile(r"^\s*(#(end)?region\b|@\w+\s*$|namespace\b|tokenfile\s)", re.I)  # folds, pBASIC labels
FUNCTIONS = set(range(0xB4, 0xCB)) | {0xA3, 0xA6}            # sgn..mid$, tab(, spc(: no space after
SYMBOLS = {0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xB1, 0xB2, 0xB3}    # + - * / ^ > = <


@dataclass
class Piece:
    kind: str            # kw, space, string, rem, data, other
    start: int
    end: int
    token: int = 0


def scan(body: str) -> list[Piece]:
    """A line's text (after its number) in pieces, with where each is in `body`, as the
    tokenizer sees it."""
    src = _source_bytes(body, 0)
    out: list[Piece] = []
    i, n = 0, len(src)
    while i < n:
        b, literal, _shifted, s, e = src[i]
        if b == 0x22 and not literal:
            j = i + 1
            while j < n and not (src[j][0] == 0x22 and not src[j][1]):
                j += 1
            end = src[j][4] if j < n else len(body)
            out.append(Piece("string", s, end))
            i = j + 1
            continue
        if b == 0x20 and not literal:
            out.append(Piece("space", s, e))
            i += 1
            continue
        if b == 0x3F and not literal:
            out.append(Piece("kw", s, e, PRINT))
            i += 1
            continue
        m = None if literal or 0x30 <= b <= 0x3B else match_keyword(src, i)
        if m:
            tok, k = m[0], m[1]
            out.append(Piece("kw", s, src[i + k - 1][4], tok))
            i += k
            if tok == REM:
                if i < n:
                    out.append(Piece("rem", src[i][3], len(body)))
                return out
            if tok == DATA:
                j = i
                q = False
                while j < n and not (src[j][0] == 0x3A and not q):
                    if src[j][0] == 0x22:
                        q = not q
                    j += 1
                if j > i:
                    out.append(Piece("data", src[i][3], src[j - 1][4]))
                i = j
            continue
        out.append(Piece("other", s, e))
        i += 1
    return out


def _text(body: str, p: Piece) -> str:
    return body[p.start:p.end]


# ---------------------------------------------------------------- what a line does
def _signature(body: str, strings=True, rem=True, data=True) -> tuple:
    """What tokenizing the line gives, without the spaces that don't matter."""
    out: list = []
    b = crunch(body, 0)
    i, mode = 0, ""
    while i < len(b):
        c = b[i]
        if mode == "rem":
            out.append(("rem", bytes(x for x in b[i:] if x != 0x20)) if rem else ("rem",))
            break
        if mode == "data":
            j = i
            while j < len(b) and b[j] != 0x3A:
                j += 1
            items = bytes(b[i:j]).split(b",")
            out.append(("data", tuple(x.strip(b" ") for x in items)) if data else ("data", len(items)))
            i, mode = j, ""
            continue
        if c == 0x22:
            j = b.find(b'"', i + 1)
            j = len(b) if j < 0 else j
            out.append(("str", bytes(b[i + 1:j])) if strings else ("str", j - i))
            i = j + 1
            continue
        if c != 0x20:
            out.append(c)
            if c == REM:
                mode = "rem"
            elif c == DATA:
                mode = "data"
        i += 1
    return tuple(out)


# ---------------------------------------------------------------- abbreviations
def _abbreviations() -> dict[int, str]:
    """The shortest way to write each keyword that tokenizes back to it (? for PRINT)."""
    out = {PRINT: "?"}
    for i, kw in enumerate(KEYWORDS):
        tok = 0x80 + i
        if tok in out:
            continue
        for j in range(1, len(kw) - 1):
            if not kw[j].isalpha():
                break
            s = kw[:j] + kw[j].upper()
            try:
                if crunch(s, 0) == bytes([tok]):
                    out[tok] = s
                    break
            except BasicError:
                pass
        out.setdefault(tok, kw)
    return out


ABBREVIATIONS = _abbreviations()


def _case(text: str, how: str | None) -> str:
    """Change the letters' case, leaving {codes} alone."""
    if not how:
        return text
    return re.sub(r"\{[^}]*\}|[^{]+", lambda m: m.group(0) if m.group(0).startswith("{")
                  else (m.group(0).lower() if how == "lower" else m.group(0).upper()), text)


def _zeros(data: str) -> str:
    """DATA items that are 0 left empty, and 0.5 written .5 (READ reads them the same)."""
    out, item, q = [], "", False
    for ch in data + ",":
        if ch == '"':
            q = not q
        if ch == "," and not q:
            s = item.strip()
            if s and not s.startswith('"'):
                if re.fullmatch(r"[-+]?0+", s):
                    item = item.replace(s, "")
                elif re.fullmatch(r"[-+]?0+\.\d*", s):
                    item = item.replace(s, re.sub(r"0+\.", ".", s, count=1))
            out.append(item)
            item = ""
        else:
            item += ch
    return ",".join(out)


# ---------------------------------------------------------------- one line
@dataclass
class Options:
    space_after_number: bool = True
    remove_blank_lines: bool = True
    strings_case: str | None = None       # "lower", "upper" or None
    comments_case: str | None = None
    remove_rems: bool = False
    remove_spaces: bool = False
    spaces_after_rem: bool = False
    remove_zeros: bool = False
    expand: bool = False                  # keywords in full, spaced out
    keywords: str | None = None           # "abbreviate" (Compress), "full" or "FULL" (Uncompress)


def _join(parts: list[tuple[str, str, int]]) -> str:
    """Expand: put a space round keywords, as listings are usually written."""
    out = ""
    prev = ""            # kind of the last piece: kw-stmt, kw-func, kw-sym, sep, word, string
    for text, kind, tok in parts:
        if kind == "space":
            continue
        if kind == "kw":
            k = "func" if tok in FUNCTIONS else "sym" if tok in SYMBOLS else "stmt"
        elif kind == "other" and text == ":":
            k = "sep"
        elif kind == "other" and text in "()+-*/^=<>,;#":
            k = "punct"
        else:
            k = kind
        need = False
        if out and not out.endswith(" "):
            if prev == "stmt" and k not in ("sep", "punct") and not (k == "other" and text in ")"):
                need = True
            elif k == "stmt" and prev not in ("sep",) and prev:
                need = True
            elif k in ("rem", "data") and prev == "stmt":
                need = True
            elif prev == "stmt" and k == "punct" and text in "(\"":
                need = True
        if k in ("rem", "data"):
            text = text.lstrip(" ")
        out += (" " if need else "") + text
        prev = k
    return out


def reformat_body(body: str, o: Options) -> str:
    """One line's text (after its number), reformatted."""
    pieces = scan(body)
    parts: list[tuple[str, str, int]] = []
    for p in pieces:
        t = _text(body, p)
        if p.kind == "kw":
            if o.keywords == "abbreviate":
                t = ABBREVIATIONS.get(p.token, t)
            elif o.keywords in ("full", "FULL") or o.expand:
                full = KEYWORDS[p.token - 0x80]
                t = full.upper() if o.keywords == "FULL" else full
        elif p.kind == "string":
            t = '"' + _case(t[1:], o.strings_case) if t.startswith('"') else t
        elif p.kind == "rem":
            t = _case(t, o.comments_case)
            if o.spaces_after_rem:
                t = re.sub(r" +", "", t)
        elif p.kind == "data":
            if o.remove_zeros:
                t = _zeros(t)
            if o.remove_spaces:
                t = re.sub(r'"[^"]*"|\s*,\s*|^\s+', lambda m: m.group(0) if m.group(0).startswith('"')
                           else ("," if "," in m.group(0) else ""), t)
        elif p.kind == "space" and o.remove_spaces:
            t = ""
        parts.append((t, p.kind, p.token))
    if o.remove_rems:
        cut = next((i for i, (_t, k, tok) in enumerate(parts) if k == "kw" and tok == REM), None)
        if cut is not None:                 # the REM and the ':' before it
            parts = parts[:cut]
            while parts and parts[-1][1] == "space":
                parts.pop()
            if parts and parts[-1][0] == ":":
                parts.pop()
            while parts and parts[-1][1] == "space":
                parts.pop()
    if o.expand:
        return _join(parts)
    return "".join(t for t, _k, _tok in parts)


def reformat(text: str, o: Options) -> tuple[str, list[BasicError]]:
    """A whole program (numbered BASIC or pBASIC) reformatted. Returns (text, warnings)."""
    lines = text.split("\n")
    trailing = text.endswith("\n")
    if trailing:
        lines = lines[:-1]
    targets = set()
    for ln in lines:
        m = _NUMBERED.match(ln)
        for r in find_line_refs(m.group(4) if m else ln):
            body = m.group(4) if m else ln
            targets.add(int(body[r.start:r.end]))
    warnings: list[BasicError] = []
    out: list[str] = []
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            if not o.remove_blank_lines:
                out.append(line)
            continue
        if _SKIP.match(line):
            out.append(line)
            continue
        m = _NUMBERED.match(line)
        head, body = (m.group(1) + m.group(2), m.group(4)) if m else ("", line)
        gap = (m.group(3) if m else "")
        try:
            new = reformat_body(body, o)
            same = _signature(new, strings=not o.strings_case, rem=not (o.comments_case or o.spaces_after_rem),
                              data=not o.remove_zeros)
            old = _signature(body, strings=not o.strings_case, rem=not (o.comments_case or o.spaces_after_rem),
                             data=not o.remove_zeros)
            if o.remove_rems:
                same = tuple(x for x in same if x != REM and not (isinstance(x, tuple) and x[0] == "rem"))
                old = tuple(x for x in old if x != REM and not (isinstance(x, tuple) and x[0] == "rem"))
                while old and old[-1] == 0x3A and (not same or same[-1] != 0x3A):
                    old = old[:-1]
        except BasicError as e:
            warnings.append(BasicError(f"Left as it was: {e.message}", n))
            out.append(line)
            continue
        if same != old:
            warnings.append(BasicError("Left as it was: reformatting it would change what it does", n))
            out.append(line)
            continue
        if not new.strip() and o.remove_rems:
            number = int(m.group(2)) if m else None
            if number is not None and number in targets:
                out.append(f"{head} rem")       # a GOTO goes here: keep the line, without the remark
                warnings.append(BasicError(f"Line {number} is only a REM, but a jump goes to it: kept as "
                                           f"'{number} rem'", n))
            continue
        if m:
            gap = " " if o.space_after_number else gap
            out.append(f"{head}{gap}{new}")
        else:
            out.append(new)
    return "\n".join(out) + ("\n" if trailing else ""), warnings
