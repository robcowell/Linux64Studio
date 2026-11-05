"""Managing a project's files from the sidebar, as CBM prg Studio's Project Explorer does: rename,
delete, new folders, and the build list (add, remove, move earlier or later).

The files themselves are renamed, made or deleted by the caller; this keeps the project's settings
in step. Many settings name files by path relative to the project folder (the build list, Kick's
main file, linked exports, disk and cartridge contents, music, per-file view settings), so:

* ``rename`` points every setting naming the old path (or something inside an old folder) at the new.
* ``forget`` drops the settings that use a deleted file (or anything in a deleted folder) as input.
  Outputs (where an export or the music is written) are left: the build makes them again.
* ``including_lines`` finds source lines that include a file by name, which a rename doesn't change.
"""
from __future__ import annotations

import os
from pathlib import Path

from .model import Project

_BAD_CHARS = set('/\\:*?"<>|')


def check_name(folder: Path, name: str, current: Path | None = None) -> str | None:
    """Why ``name`` can't be a new file or folder name in ``folder``, or None if it can."""
    name = name.strip()
    if not name or name in (".", ".."):
        return "Enter a name"
    if any(c in _BAD_CHARS for c in name):
        return "A name can't contain / \\ : * ? \" < > |"
    target = folder / name
    if target.exists() and (current is None or target.resolve() != current.resolve()):
        # a change of case only is a rename, not a clash
        if current is None or target.name.lower() != current.name.lower() or target.parent != current.parent:
            return f"{name} already exists"
    return None


def relative(project: Project, path: Path) -> str:
    """``path`` relative to the project folder, with / separators (as settings store it)."""
    return Path(os.path.relpath(Path(path).resolve(), project.directory.resolve())).as_posix()


def check_move(src: Path, dest_dir: Path) -> str | None:
    """Whether ``src`` (a file or folder) can be dragged into ``dest_dir``: None if it can, "" if
    there's nothing to do (it's already there), else why not."""
    src, dest_dir = Path(src).resolve(), Path(dest_dir).resolve()
    if dest_dir == src.parent:
        return ""
    if dest_dir == src or src in dest_dir.parents:
        return f"Can't move {src.name} into itself"
    if (dest_dir / src.name).exists():
        return f"{dest_dir.name} already has something called {src.name}"
    return None


def _abs(project: Project, value: str) -> Path:
    return (project.directory / value.replace("\\", "/")).resolve()


def _within(p: Path, old: Path) -> bool:
    return p == old or old in p.parents


def _moved(project: Project, value: str, old: Path, new: Path) -> str | None:
    """``value`` (a relative path) after ``old`` became ``new``, or None if it's unaffected."""
    if not value:
        return None
    p = _abs(project, value)
    if not _within(p, old):
        return None
    return relative(project, new / p.relative_to(old)) if p != old else relative(project, new)


def rename(project: Project, old: Path, new: Path) -> int:
    """Point the project's settings at ``new`` where they named ``old``. Returns how many changed."""
    from .model import store_program
    store_program(project)
    old, new = Path(old).resolve(), Path(new).resolve()
    n = 0

    def mv(v: str) -> str:
        nonlocal n
        m = _moved(project, v, old, new)
        if m is None:
            return v
        n += 1
        return m

    project.build_list = [mv(v) for v in project.build_list]
    for prog in project.programs:                    # the other programs' build lists too
        prog["build_list"] = [mv(v) for v in prog.get("build_list", [])]
        prog["main_file"] = mv(prog.get("main_file", ""))
    for attr in ("main_file", "disk_image", "cart_file", "kickass_jar", "disk_program", "output_dir"):
        setattr(project, attr, mv(getattr(project, attr)))
    project.lib_dirs = [mv(v) for v in project.lib_dirs]
    project.cart_banks = [mv(v) for v in project.cart_banks]
    project.exports = {mv(k): {kind: mv(v) for kind, v in d.items()} for k, d in project.exports.items()}
    for d in project.disk_extra_files:
        if d.get("file"):
            d["file"] = mv(d["file"])
    for d in project.music:
        for key in ("source", "output"):
            if d.get(key):
                d[key] = mv(d[key])
    project.charpad_views = {mv(k): v for k, v in project.charpad_views.items()}
    project.sprite_pads = {mv(k): v for k, v in project.sprite_pads.items()}
    return n


def forget(project: Project, gone: Path) -> int:
    """Drop the settings that used ``gone`` (a file, or a folder and all in it) as an input."""
    from .model import store_program
    store_program(project)
    gone = Path(gone).resolve()
    n = 0

    def uses(v: str) -> bool:
        nonlocal n
        if v and _within(_abs(project, v), gone):
            n += 1
            return True
        return False

    project.build_list = [v for v in project.build_list if not uses(v)]
    for prog in project.programs:
        prog["build_list"] = [v for v in prog.get("build_list", []) if not uses(v)]
        if uses(prog.get("main_file", "")):
            prog["main_file"] = ""
    for attr in ("main_file", "kickass_jar", "disk_program"):
        if uses(getattr(project, attr)):
            setattr(project, attr, "")
    project.cart_banks = [v for v in project.cart_banks if not uses(v)]
    project.exports = {k: d for k, d in project.exports.items() if not uses(k)}
    project.disk_extra_files = [d for d in project.disk_extra_files if not uses(d.get("file", ""))]
    project.music = [d for d in project.music if not uses(d.get("source", ""))]
    project.charpad_views = {k: v for k, v in project.charpad_views.items() if not uses(k)}
    project.sprite_pads = {k: v for k, v in project.sprite_pads.items() if not uses(k)}
    return n


# ------------------------------------------------------------------------ the build list (CBM projects)
def build_index(project: Project, path: Path) -> int | None:
    """Where ``path`` is on the build list, or None."""
    want = Path(path).resolve()
    return next((i for i, v in enumerate(project.build_list) if _abs(project, v) == want), None)


def build_add(project: Project, path: Path) -> bool:
    """Put ``path`` on the build list, at the end (CBM prg Studio builds in list order)."""
    if build_index(project, path) is not None:
        return False
    project.build_list.append(relative(project, path))
    return True


def build_remove(project: Project, path: Path) -> bool:
    i = build_index(project, path)
    if i is None:
        return False
    del project.build_list[i]
    return True


def build_move(project: Project, path: Path, delta: int) -> bool:
    """Move ``path`` ``delta`` places along the build list (negative: earlier)."""
    i = build_index(project, path)
    if i is None:
        return False
    j = max(0, min(len(project.build_list) - 1, i + delta))
    if j == i:
        return False
    project.build_list.insert(j, project.build_list.pop(i))
    return True


# ------------------------------------------------------------------------ what still names a file
def including_lines(texts: dict[str, str], target: Path) -> list[tuple[str, int]]:
    """The (file, 1-based line) of each include line (incasm, incbin, #import, ...) naming ``target``."""
    from ..symindex import include_at
    target = Path(target).resolve()
    out = []
    for file, text in texts.items():
        base = Path(file).parent
        for n, line in enumerate(text.splitlines(), start=1):
            if "inc" not in line.lower() and "import" not in line.lower():
                continue
            p = include_at(line, base)
            if p is not None and p.resolve() == target:
                out.append((file, n))
    return out
