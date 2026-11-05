"""The project's breakpoints, as CBM prg Studio's Breakpoints window lists them: every breakpoint set
in the editor gutter, in open files and closed ones, each on or off. They're kept with the project
(session.ProjectState), so they're there after closing a file or restarting.

While a file is open its editor's marks are the truth (they move as lines are added above them);
the window copies them back here with ``set_file``. Breakpoints written in the source (the
``breakpoint`` directive) aren't kept here: they come from the build.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Breakpoint:
    file: str          # resolved path
    line: int          # 1-based
    enabled: bool = True


def _key(file) -> str:
    return str(Path(file).resolve())


class Breakpoints:
    def __init__(self, items: list[Breakpoint] | None = None):
        self._by_file: dict[str, dict[int, bool]] = {}
        for b in items or []:
            self._by_file.setdefault(_key(b.file), {})[b.line] = b.enabled

    # ---------------------------------------------------------------- reading
    def all(self) -> list[Breakpoint]:
        """Every breakpoint, by file then line."""
        return [Breakpoint(f, ln, on) for f in sorted(self._by_file, key=str.lower)
                for ln, on in sorted(self._by_file[f].items())]

    def enabled(self) -> list[Breakpoint]:
        return [b for b in self.all() if b.enabled]

    def for_file(self, file) -> list[tuple[int, bool]]:
        """(line, on) for one file, in line order."""
        return sorted(self._by_file.get(_key(file), {}).items())

    def __len__(self) -> int:
        return sum(len(d) for d in self._by_file.values())

    # ---------------------------------------------------------------- changing
    def set_file(self, file, lines: list[tuple[int, bool]]):
        """A file's breakpoints are now ``lines`` (from its editor)."""
        if lines:
            self._by_file[_key(file)] = dict(lines)
        else:
            self._by_file.pop(_key(file), None)

    def set_enabled(self, file, line: int, on: bool) -> bool:
        d = self._by_file.get(_key(file))
        if d is None or line not in d:
            return False
        d[line] = on
        return True

    def set_all_enabled(self, on: bool):
        for d in self._by_file.values():
            for ln in d:
                d[ln] = on

    def remove(self, file, line: int) -> bool:
        d = self._by_file.get(_key(file))
        if d is None or line not in d:
            return False
        del d[line]
        if not d:
            del self._by_file[_key(file)]
        return True

    def clear(self):
        self._by_file.clear()

    def rename(self, old, new):
        """A file or folder was renamed or moved: its breakpoints go with it."""
        old, new = Path(old).resolve(), Path(new).resolve()
        for f in list(self._by_file):
            p = Path(f)
            if p == old or old in p.parents:
                self._by_file[str(new / p.relative_to(old)) if p != old else str(new)] = self._by_file.pop(f)

    def forget(self, gone):
        """A file or folder was deleted: drop its breakpoints."""
        gone = Path(gone).resolve()
        for f in list(self._by_file):
            p = Path(f)
            if p == gone or gone in p.parents:
                del self._by_file[f]

    # ---------------------------------------------------------------- keeping them
    def to_list(self) -> list[dict]:
        return [{"file": b.file, "line": b.line, "enabled": b.enabled} for b in self.all()]

    @classmethod
    def from_list(cls, data) -> Breakpoints:
        items = []
        for d in data or []:
            try:
                items.append(Breakpoint(str(d["file"]), int(d["line"]), bool(d.get("enabled", True))))
            except (KeyError, TypeError, ValueError):
                continue
        return cls(items)


# ------------------------------------------------------------------------ where a breakpoint is in memory
def line_addresses(srcmap: dict[int, tuple[str, int]]) -> dict[tuple[str, int], int]:
    """{(file, line): the first address assembled from it} from a build's source map."""
    out: dict[tuple[str, int], int] = {}
    for addr in sorted(srcmap):
        f, ln = srcmap[addr]
        out.setdefault((_key(f), ln), addr)
    return out


def address_for(line_addr: dict[tuple[str, int], int], file, line: int, reach: int = 20) -> int | None:
    """The address a breakpoint on ``line`` stops at: the first code at or after it (a breakpoint on
    a comment or label line stops at the instruction below), within ``reach`` lines."""
    f = _key(file)
    for ln in range(line, line + reach):
        a = line_addr.get((f, ln))
        if a is not None:
            return a
    return None
