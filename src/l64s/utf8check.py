"""UTF-8 check (CBM prg Studio's Tools → UTF-8 Check): find the characters in a source that aren't
plain ASCII, the ones that slip in when code is pasted from a web page, a PDF or a word processor
(curly quotes, dashes, non-breaking spaces, a byte order mark), which the assembler and the C64
can't take, and put ASCII in their place.

In BASIC, £ π ← ↑ are allowed: they stand for the C64's own characters and the tokenizer reads them.
A file that isn't UTF-8 at all is reported too, with where it stops being UTF-8.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

REPLACEMENTS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'", "`": None,
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "―": "-", "‒": "-", "‐": "-", "‑": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    "…": "...", "×": "*", "÷": "/", "•": "*", "·": ".",
    "﻿": "", "​": "", "‌": "", "‍": "", "⁠": "", "­": "",
    "→": "->", "←": "<-", "≤": "<=", "≥": ">=", "≠": "<>",
}
BASIC_OK = set("£π←↑")


@dataclass(frozen=True)
class Finding:
    file: str
    line: int            # 1-based
    column: int          # 1-based
    char: str
    replacement: str | None    # None: no obvious ASCII for it

    @property
    def code(self) -> str:
        return f"U+{ord(self.char):04X}"

    @property
    def name(self) -> str:
        return unicodedata.name(self.char, "unnamed").title() if self.char else "not UTF-8"

    def describe(self) -> str:
        if not self.char:
            return "the file isn't UTF-8 from here (it was read as Windows-1252)"
        shown = {" ": "(no-break space)", "﻿": "(byte order mark)", "​": "(zero width space)",
                 "\t": "(tab)"}.get(self.char, self.char)
        fix = "" if self.replacement is None else (f" → {self.replacement!r}" if self.replacement else " → (remove)")
        return f"{shown}  {self.code} {self.name}{fix}"


def check_text(text: str, file: str = "", basic: bool = False) -> list[Finding]:
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        for c, ch in enumerate(line, start=1):
            if ord(ch) < 0x80 and ch != "\x7f" and (ch >= " " or ch == "\t"):
                continue
            if basic and ch in BASIC_OK:
                continue
            rep = REPLACEMENTS.get(ch)
            if rep is None and ch not in REPLACEMENTS:
                decomposed = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
                rep = decomposed or None             # é → e, ﬁ → fi
            out.append(Finding(file, n, c, ch, rep))
    return out


def read(path: Path) -> tuple[str, Finding | None]:
    """A file's text, and where it isn't UTF-8 (read as Windows-1252 then), if anywhere."""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError as e:
        line = data[:e.start].count(b"\n") + 1
        col = e.start - (data.rfind(b"\n", 0, e.start) + 1) + 1
        return data.decode("cp1252", errors="replace"), Finding(str(path), line, col, "", None)


def check_file(path: Path, text: str | None = None) -> list[Finding]:
    basic = Path(path).suffix.lower() in (".bas", ".pbas")
    bad = None
    if text is None:
        text, bad = read(path)
    found = check_text(text, str(path), basic)
    return ([bad] if bad else []) + found


def fix(text: str, basic: bool = False) -> tuple[str, int, int]:
    """Text with ASCII in place of what has an obvious replacement. Returns (text, how many were
    replaced, how many were left: no ASCII for them)."""
    out, done, left = [], 0, 0
    for ch in text:
        if ord(ch) < 0x80 or (basic and ch in BASIC_OK) or ch in "\n\r":
            out.append(ch)
            continue
        rep = REPLACEMENTS.get(ch)
        if rep is None and ch not in REPLACEMENTS:
            rep = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode() or None
        if rep is None:
            out.append(ch)
            left += 1
        else:
            out.append(rep)
            done += 1
    return "".join(out), done, left
