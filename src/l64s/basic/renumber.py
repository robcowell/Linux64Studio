"""Renumbering BASIC programs, updating GOTO/GOSUB/THEN/ON...GOTO/RUN/LIST references."""
from __future__ import annotations

from dataclasses import dataclass

from .tokenizer import KEYWORDS, MAX_LINE_NUMBER, BasicError, BasicErrors, parse_source

_REF_KEYWORDS = {"goto", "gosub", "then", "run", "list"}


@dataclass
class Ref:
    start: int  # character offsets of a line number in the line's text
    end: int


def find_line_refs(body: str) -> list[Ref]:
    """Line numbers used as jump targets in one line's text (after its line number).

    Scans the way the ROM's tokenizer does, so keywords inside strings, REM and DATA
    are ignored.
    """
    refs: list[Ref] = []
    low = body.lower()
    n = len(body)
    i = 0
    in_quote = in_data = False
    while i < n:
        ch = low[i]
        if ch == "{":  # control code, never part of a keyword
            close = body.find("}", i)
            i = n if close == -1 else close + 1
            continue
        if ch == '"':
            in_quote = not in_quote
            i += 1
            continue
        if in_quote or ch == " ":
            i += 1
            continue
        if in_data:
            if ch == ":":
                in_data = False
            i += 1
            continue
        if "0" <= ch <= ";":
            i += 1
            continue
        kw = next((k for k in KEYWORDS if low.startswith(k, i)), None)
        if kw is None:
            i += 1
            continue
        i += len(kw)
        if kw == "rem":
            break
        if kw == "data":
            in_data = True
            continue
        if kw == "go":  # GO TO
            j = i
            while j < n and body[j] == " ":
                j += 1
            if low.startswith("to", j):
                i = j + 2
                kw = "goto"
            else:
                continue
        if kw not in _REF_KEYWORDS:
            continue
        # Read the number list: GOTO a,b,c (from ON ... GOTO) or LIST a-b
        while True:
            j = i
            while j < n and body[j] == " ":
                j += 1
            k = j
            while k < n and body[k].isdigit():
                k += 1
            if k == j:
                break
            refs.append(Ref(j, k))
            i = k
            while i < n and body[i] == " ":
                i += 1
            sep = "-" if kw == "list" else ","
            if kw in ("goto", "gosub", "list") and i < n and body[i] == sep:
                i += 1
                continue
            break
    return refs


def renumber(text: str, start: int = 10, step: int = 10) -> tuple[str, list[BasicError]]:
    """Renumber a whole program. Returns (new text, warnings about references to missing lines)."""
    if start < 0 or step < 1:
        raise BasicErrors([BasicError("Start must be 0 or more and the step at least 1")])
    entries, _ = parse_source(text)
    last = start + step * (len(entries) - 1) if entries else start
    if last > MAX_LINE_NUMBER:
        raise BasicErrors([BasicError(f"Renumbering would need line {last}, above {MAX_LINE_NUMBER}; "
                                      f"use a smaller start or step")])
    mapping = {old: start + i * step for i, (old, _b, _s) in enumerate(entries)}
    warnings: list[BasicError] = []
    out = []
    # fold lines (#region, #endregion) aren't numbered: keep each before the line that followed it
    import re
    folds = [(n, line) for n, line in enumerate(text.splitlines(), start=1)
             if re.match(r"^\s*(#(end)?region\b|tokenfile\s)", line, re.I)]
    for old, body, src_line in entries:
        while folds and folds[0][0] < src_line:
            out.append(folds.pop(0)[1])
        refs = find_line_refs(body)
        pieces, pos = [], 0
        for r in refs:
            target = int(body[r.start:r.end])
            pieces.append(body[pos:r.start])
            if target in mapping:
                pieces.append(str(mapping[target]))
            else:
                pieces.append(body[r.start:r.end])
                warnings.append(BasicError(f"Line {old} refers to line {target}, which doesn't exist", src_line))
            pos = r.end
        pieces.append(body[pos:])
        out.append(f"{mapping[old]} {''.join(pieces)}")
    out += [line for _n, line in folds]
    return "\n".join(out) + "\n", warnings
