"""Kick Assembler sources written on Windows, built on Linux.

Windows doesn't mind ``..\\..\\Content\\Sprites.bin`` or ``../../Library`` for a folder called
``library``; Kick Assembler on Linux can't open either. The Retro Game Dev books' Kick Assembler
projects are written that way. Rather than change them, a build that needs it works from a copy:
every source the program imports, with each path it reads written as the file is really called, and
the data those sources read, laid out as the originals are (``shadow``). Lines stay where they were,
so Kick Assembler's errors and its debug dump point back at the original files through ``Shadow.original``.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# The directives that read a file: #import/#importif, .import binary/source/c64/text, and the
# script functions that load data (LoadBinary, LoadPicture, LoadSid)
_READS = re.compile(r'(#import(?:if\b[^"\n]*)?\s+|\.import\s+(?:binary|source|c64|text)\s+|'
                    r'\bLoad(?:Binary|Picture|Sid)\s*\(\s*)"([^"\n]+)"')
_SOURCES = re.compile(r'#import|\.import\s+source')    # (of those, the ones that read source)
_ENCODING = "latin-1"                                  # (any byte goes through unchanged)


def find(name: str, folders: list[Path]) -> Path | None:
    """The file a path in a source means, as Windows would find it: \\ as /, and any part of it in
    another case (when only one file has that name). Tried in each folder in turn."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    for folder in folders:
        at = Path("/") if name.startswith(("/", "\\")) else folder
        for part in parts:
            if part == "..":
                at = at.parent
                continue
            exact = at / part
            if exact.exists():
                at = exact
                continue
            try:
                same = [c for c in at.iterdir() if c.name.lower() == part.lower()]
            except OSError:
                same = []
            if len(same) != 1:
                break
            at = same[0]
        else:
            if at.is_file():
                return at.resolve()
    return None


@dataclass
class _Reached:
    files: dict[Path, list[tuple[int, int, Path]]] = field(default_factory=dict)  # source → (start, end, file read)
    data: set[Path] = field(default_factory=set)
    windows: bool = False                                  # a path only Windows would find


def _walk(main: Path, lib_dirs: list[Path]) -> _Reached:
    """Every file ``main`` reads, following its imports."""
    r = _Reached()
    todo = [main.resolve()]
    while todo:
        src = todo.pop()
        if src in r.files:
            continue
        r.files[src] = []
        try:
            text = src.read_bytes().decode(_ENCODING)
        except OSError:
            continue
        for m in _READS.finditer(text):
            name = m.group(2)
            target = find(name, [src.parent] + lib_dirs)
            if target is None:
                continue                                    # (Kick Assembler will say)
            if not (src.parent / name).is_file():
                r.windows = True
            r.files[src].append((m.start(2), m.end(2), target))
            if _SOURCES.match(m.group(1)):
                todo.append(target)
            else:
                r.data.add(target)
    return r


def needs_shadow(main: Path, lib_dirs: list[Path]) -> bool:
    """Whether ``main`` (or anything it imports) reads a file by a path only Windows finds."""
    return _walk(main, lib_dirs).windows


@dataclass
class Shadow:
    main: Path                                  # the copy of the main source, to build
    original: dict[str, str]                    # each copy's path → the original's

    def map(self, path: str) -> str:
        return self.original.get(path, path)


def shadow(main: Path, lib_dirs: list[Path], where: Path) -> Shadow | None:
    """Copy what ``main`` reads into ``where`` (emptied first) with its paths fixed, if it needs it
    (else None, and nothing's written)."""
    r = _walk(main, lib_dirs)
    if not r.windows:
        return None
    every = list(r.files) + sorted(r.data)
    root = Path(os.path.commonpath([str(p.parent) for p in every]))
    if where.exists():
        shutil.rmtree(where)
    original: dict[str, str] = {}
    for f in every:
        copy = where / f.relative_to(root)
        copy.parent.mkdir(parents=True, exist_ok=True)
        if f in r.files:
            text = f.read_bytes().decode(_ENCODING)
            for start, end, target in reversed(r.files[f]):
                text = text[:start] + os.path.relpath(target, f.parent).replace(os.sep, "/") + text[end:]
            copy.write_bytes(text.encode(_ENCODING))
        else:
            shutil.copy2(f, copy)
        original[str(copy.resolve())] = str(f)
    return Shadow((where / main.resolve().relative_to(root)).resolve(), original)
