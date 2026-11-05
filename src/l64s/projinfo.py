"""The Project Information panel, as CBM prg Studio's: the project's labels, variables and macros,
grouped by the file each is defined in. Double-clicking one goes to it.

Built from symindex's scan of the sources (so it works on code that doesn't build yet) and, for
BASIC files, the variables basic.stats finds. A label's value is shown when the last build has it.

* Labels: labels, `@local` labels (after the label they belong to), Kick `.label`s and namespaces.
* Variables: CBM `NAME = value` assignments and Kick `.const`/`.var`, with their value as written;
  and in BASIC files, each variable the program sets (as the C64 sees it, so SCORE and SC are one).
* Macros: CBM `defm`, Kick `.macro`, `.function` and `.pseudocommand`.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .symindex import Symbol, _strip_comment

TABS = (("labels", "Labels"), ("variables", "Variables"), ("macros", "Macros"))
_TAB_OF = {"label": "labels", "local": "labels", "namespace": "labels",
           "const": "variables", "var": "variables",
           "macro": "macros", "function": "macros"}


@dataclass(frozen=True)
class Item:
    name: str
    detail: str         # value, or what it is
    file: str
    line: int           # 1-based line in the file
    local: bool = False  # shown indented under the label before it


@dataclass
class Group:
    file: str
    title: str          # the file's path from the project folder
    items: list[Item] = field(default_factory=list)


def _title(file: str, project_dir: Path | None) -> str:
    if project_dir is None:
        return Path(file).name
    try:
        return os.path.relpath(file, project_dir)
    except ValueError:
        return file


def _assigned_value(sym: Symbol) -> str:
    """`NAME = value` → `value` (comment removed)."""
    line = _strip_comment(sym.text)
    for sep in ("=", " equ ", " EQU "):
        if sep in line:
            return line.split(sep, 1)[1].strip()
    return ""


def collect(symbols: list[Symbol], basic_texts: dict[str, str] | None = None, project_dir: Path | None = None,
            value_of: Callable[[Symbol], int | None] | None = None) -> dict[str, list[Group]]:
    """Each tab's groups, one per file that defines something, in path order; items in line order."""
    tabs: dict[str, dict[str, Group]] = {key: {} for key, _ in TABS}

    def add(tab: str, item: Item):
        g = tabs[tab].get(item.file)
        if g is None:
            g = tabs[tab][item.file] = Group(item.file, _title(item.file, project_dir))
        g.items.append(item)

    for s in symbols:
        tab = _TAB_OF.get(s.kind)
        if tab is None:
            continue
        if tab == "variables":
            detail = _assigned_value(s)
        elif s.kind in ("label", "local"):
            v = value_of(s) if value_of else None
            detail = f"${v:04X}" if v is not None else ""
        else:
            detail = s.kind if s.kind != "macro" else ""
        add(tab, Item(s.name, detail, s.file, s.line, local=s.kind == "local"))

    from .basic.stats import analyse
    for file, text in (basic_texts or {}).items():
        try:
            st = analyse(text)
        except Exception:           # a half-typed program: show nothing rather than fail
            continue
        for v in st.assigned():
            line = st.source_line.get(v.first_set, 0) if v.first_set is not None else 0
            add("variables", Item(v.name, v.kind, file, line))

    out = {}
    for key, groups in tabs.items():
        gs = sorted(groups.values(), key=lambda g: g.title.lower())
        for g in gs:
            g.items.sort(key=lambda i: (i.line, i.name.lower()))
        out[key] = gs
    return out
