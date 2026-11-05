"""The project's task list: the TODOs written in its sources (CBM prg Studio's Tasks panel).

A task is
* CBM prg Studio's `todo` directive, a line of its own (`todo add bounds checking`), which the
  assembler skips;
* or a comment containing TODO, FIXME or HACK (`; TODO ...`, `// FIXME: ...`, `/* TODO */`), so
  Kick Assembler sources, which have no `todo`, have tasks too;
* in BASIC, a REM containing them (`100 rem todo speed this up`).

Every file in the project is scanned, open or not.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

TAGS = ("TODO", "FIXME", "HACK")
_DIRECTIVE = re.compile(r"^\s*todo(?:\s+|:\s*|$)(.*)$", re.I)
_TAG = re.compile(r"\b(TODO|FIXME|HACK)\b[\s:.-]*(.*)", re.I)
BASIC_EXTS = (".bas", ".pbas")
C_EXTS = (".c", ".h")              # cc65 projects: only // and /* */ comments (; ends a statement)
SOURCE_EXTS = (".asm", ".s", ".a", ".inc", ".i") + BASIC_EXTS + C_EXTS


@dataclass(frozen=True)
class Task:
    file: str
    line: int          # 1-based
    kind: str          # TODO, FIXME or HACK
    text: str          # what it says (may be empty)


def _comments(line: str, in_block: bool, in_c: bool = False) -> tuple[list[str], bool]:
    """The comment text on an assembler line (`;`, `//`, `/* */`, outside quotes)."""
    out: list[str] = []
    i, n, quote = 0, len(line), None
    start = 0 if in_block else None
    while i < n:
        c = line[i]
        if start is not None:                       # in /* */
            if line.startswith("*/", i):
                out.append(line[start:i])
                start = None
                i += 2
                continue
            i += 1
            continue
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"" and line.find(c, i + 1) != -1:
            quote = c
        elif (c == ";" and not in_c) or line.startswith("//", i):
            out.append(line[i + (1 if c == ";" else 2):])
            return out, False
        elif line.startswith("/*", i):
            start = i + 2
            i += 2
            continue
        i += 1
    if start is not None:
        out.append(line[start:])
        return out, True
    return out, False


def _basic_rem(line: str) -> str | None:
    """The text after REM on a BASIC line (outside strings), or None."""
    quote = False
    low = line.lower()
    for i, c in enumerate(line):
        if c == '"':
            quote = not quote
        elif not quote and low.startswith("rem", i):
            return line[i + 3:]
    return None


def scan(text: str, file: str = "", basic: bool = False, c: bool = False) -> list[Task]:
    """The tasks in a file: BASIC REMs, C comments (``c``), or assembler comments and todo lines."""
    tasks: list[Task] = []
    in_block = False
    for n, raw in enumerate(text.splitlines(), start=1):
        if basic:
            rem = _basic_rem(raw)
            texts = [rem] if rem is not None else []
        else:
            if not in_block and not c:
                m = _DIRECTIVE.match(raw)
                if m:
                    tasks.append(Task(file, n, "TODO", m.group(1).strip()))
                    continue
            texts, in_block = _comments(raw, in_block, c)
        for t in texts:
            m = _TAG.search(t)
            if m:
                tasks.append(Task(file, n, m.group(1).upper(), m.group(2).strip().rstrip("*/").strip()))
                break
    return tasks


class TaskList:
    """The tasks in a set of files, rescanning only those that changed."""

    def __init__(self):
        self._files: dict[str, tuple[object, list[Task]]] = {}

    def update(self, files: list[Path], overrides: dict[str, str] | None = None) -> list[Task]:
        overrides = {str(Path(k).resolve()): v for k, v in (overrides or {}).items()}
        keep = set()
        for p in files:
            key = str(Path(p).resolve())
            keep.add(key)
            if key in overrides:
                text = overrides[key]
                stamp: object = ("text", hash(text))
                if key in self._files and self._files[key][0] == stamp:
                    continue
            else:
                try:
                    st = os.stat(key)
                except OSError:
                    continue
                stamp = (st.st_mtime_ns, st.st_size)
                if key in self._files and self._files[key][0] == stamp:
                    continue
                try:
                    data = Path(key).read_bytes()
                except OSError:
                    continue
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = data.decode("cp1252")
            sfx = Path(key).suffix.lower()
            self._files[key] = (stamp, scan(text, key, sfx in BASIC_EXTS, sfx in C_EXTS))
        for k in list(self._files):
            if k not in keep:
                del self._files[k]
        return self.tasks()

    def tasks(self) -> list[Task]:
        return sorted((t for _s, ts in self._files.values() for t in ts), key=lambda t: (t.file, t.line))


def todo_line(current: str, text: str, kind: str) -> str:
    """The line Add TODO puts above `current`: `kind` is "cbm" (the todo directive, indented
    like the code), "kick" or "c" (a // comment) or "pbasic" (a REM)."""
    indent = re.match(r"\s*", current).group(0) or "        "
    if kind in ("kick", "c"):
        return f"{indent}// TODO {text}".rstrip()
    if kind == "pbasic":
        return f"rem todo {text}".rstrip()
    return f"{indent}todo {text}".rstrip()


def basic_todo(text: str, line_no: int, task: str) -> tuple[str, int]:
    """Add a `rem todo` to a numbered BASIC program at editor line `line_no`: a new line above it
    when there's a free line number between it and the one before, otherwise on the end of that
    line. Returns (new text, the editor line the TODO is on)."""
    lines = text.split("\n")
    i = max(0, min(line_no - 1, len(lines) - 1))
    m = re.match(r"\s*(\d+)", lines[i]) if lines else None
    if m:
        prev = None
        for j in range(i - 1, -1, -1):
            pm = re.match(r"\s*(\d+)", lines[j])
            if pm:
                prev = int(pm.group(1))
                break
        here = int(m.group(1))
        lo = -1 if prev is None else prev
        if here - lo > 1:
            number = (lo + here + 1) // 2 if prev is not None else max(0, here - 1)
            lines.insert(i, f"{number} rem todo {task}".rstrip())
            return "\n".join(lines), i + 1
        lines[i] = lines[i].rstrip() + f": rem todo {task}".rstrip()
        return "\n".join(lines), i + 1
    lines.insert(i, f"rem todo {task}".rstrip())
    return "\n".join(lines), i + 1
