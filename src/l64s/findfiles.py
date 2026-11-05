"""Find in Files, as CBM prg Studio's: search the project's sources for text, a whole word or a
regular expression, with or without matching case. The texts come from the caller, so open files
are searched as they are in the editor, unsaved changes and all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCOPES = (("project", "Project"), ("open", "Open Files"), ("current", "Current File"))
MAX_MATCHES = 2000


@dataclass(frozen=True)
class Options:
    text: str
    match_case: bool = False
    whole_word: bool = False
    regex: bool = False


@dataclass(frozen=True)
class Match:
    file: str
    line: int       # 1-based
    col: int        # 0-based, in characters
    length: int     # characters matched
    text: str       # the whole line


def pattern(opts: Options) -> re.Pattern | None:
    """The compiled search, or None for an empty one. A bad regular expression raises ValueError
    saying what's wrong with it."""
    if not opts.text:
        return None
    body = opts.text if opts.regex else re.escape(opts.text)
    if opts.whole_word:
        # a "word" in 6502 source: letters, digits, _ (labels) — and @ for CBM local labels
        body = rf"(?<![\w@]){body}(?![\w@])"
    try:
        return re.compile(body, 0 if opts.match_case else re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Not a valid regular expression: {e.msg}") from None


def search(texts: dict[str, str], opts: Options, limit: int = MAX_MATCHES) -> tuple[list[Match], bool]:
    """Every match in ``texts`` ({file: text}, searched in that order), and whether there were more
    than ``limit`` (only the first ``limit`` are returned). A match never spans lines."""
    rx = pattern(opts)
    if rx is None:
        return [], False
    out: list[Match] = []
    for file, text in texts.items():
        for n, line in enumerate(text.splitlines(), start=1):
            for m in rx.finditer(line):
                if m.end() == m.start():          # a regex matching nothing (e.g. ^) isn't a result
                    continue
                if len(out) == limit:
                    return out, True
                out.append(Match(file, n, m.start(), m.end() - m.start(), line))
    return out, False


def excerpt(m: Match, context: int = 40) -> tuple[str, str, str]:
    """The line around a match for showing it: (before, match, after). The indent is dropped, a
    long run before the match is cut to ``context`` characters (starting "…"), and tabs become spaces."""
    line = m.text
    indent = len(line) - len(line.lstrip())
    start = min(m.col, indent)
    if m.col - start > context:
        start = m.col - context
    tidy = lambda t: t.replace("\t", "    ")  # noqa: E731
    before = ("…" if start > indent else "") + tidy(line[start:m.col])
    return before, tidy(line[m.col:m.col + m.length]), tidy(line[m.col + m.length:])
