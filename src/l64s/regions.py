"""Foldable regions (CBM prg Studio's text folding): a block between a `#region` line and an
`#endregion` line can be folded away in the editor. Regions nest, and may have a name after
`#region`.

CBM prg Studio writes the lines bare, and its assembler and BASIC generator skip them; so do
Linux64Studio's. They can also be written in a comment (`; #region`, `// #region`, or in BASIC a
REM), which is how a Kick Assembler source (where a bare `#region` is an error) gets regions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_START = re.compile(r"^\s*(?:\d+\s*)?(?:(?:;|//|rem\b)\s*)?#region\b[ \t]*(.*?)\s*$", re.I)
_END = re.compile(r"^\s*(?:\d+\s*)?(?:(?:;|//|rem\b)\s*)?#endregion\b", re.I)
BARE = re.compile(r"^\s*#(?:end)?region\b", re.I)          # what the assembler and BASIC skip


@dataclass(frozen=True)
class Region:
    start: int          # 0-based line of #region
    end: int            # 0-based line of #endregion
    name: str = ""
    depth: int = 0      # 0 for outermost


def is_marker(line: str) -> bool:
    """A bare #region or #endregion line, which isn't code."""
    return bool(BARE.match(line))


def find_regions(lines: list[str]) -> list[Region]:
    """The regions, in order of their #region line. An #endregion with no #region, or a #region
    that's never closed, is left out."""
    out: list[Region] = []
    stack: list[tuple[int, str]] = []
    for n, line in enumerate(lines):
        if _END.match(line):
            if stack:
                start, name = stack.pop()
                out.append(Region(start, n, name, len(stack)))
            continue
        m = _START.match(line)
        if m:
            stack.append((n, m.group(1)))
    return sorted(out, key=lambda r: r.start)


def wrap(lines: list[str], first: int, last: int, name: str = "", comment: str = "") -> list[str]:
    """`lines` with lines first..last (0-based) inside a new region. `comment` is put before the
    markers (";", "//") for a source where bare ones aren't allowed."""
    indent = re.match(r"\s*", lines[first] if first < len(lines) else "").group(0) if comment else ""
    pre = f"{indent}{comment} " if comment else ""
    head = f"{pre}#region {name}".rstrip()
    return lines[:first] + [head] + lines[first:last + 1] + [f"{pre}#endregion"] + lines[last + 1:]
