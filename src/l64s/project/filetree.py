"""The project's files as a folder tree, for the sidebar (like VS Code's explorer).

Folders come first, then files. Files on the build list come before the rest of their folder, in
build order (CBM prg Studio assembles in that order, so it's the order worth seeing); the rest are
by name. Files outside the project folder (library and imported-data folders) sit under a top-level
folder named by its path relative to the project, e.g. ``../Library``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    name: str
    path: Path                          # the file, or the folder
    children: list[Node] = field(default_factory=list)
    is_dir: bool = False

    def find(self, path: Path) -> Node | None:
        if self.path == path:
            return self
        for c in self.children:
            if (hit := c.find(path)) is not None:
                return hit
        return None


def _root_of(f: Path, project_dir: Path, roots: list[Path]) -> Path:
    if f.is_relative_to(project_dir):
        return project_dir
    # the deepest library root holding it, else its own folder
    holders = [r for r in roots if f.is_relative_to(r)]
    return max(holders, key=lambda r: len(r.parts)) if holders else f.parent


def _label(root: Path, project_dir: Path) -> str:
    try:
        return os.path.relpath(root, project_dir)
    except ValueError:                  # another drive (not on Linux, but harmless)
        return str(root)


def build_tree(project_dir: Path, files: list[Path], build_order: dict[Path, int] | None = None,
               roots: list[Path] | None = None) -> Node:
    """A tree whose root is the project folder. ``build_order`` maps resolved paths to positions."""
    project_dir = project_dir.resolve()
    order = build_order or {}
    extra_roots = sorted({r.resolve() for r in (roots or []) if not r.resolve().is_relative_to(project_dir)},
                         key=lambda r: len(r.parts), reverse=True)
    top = Node(project_dir.name, project_dir, is_dir=True)
    dirs: dict[Path, Node] = {project_dir: top}

    def folder(path: Path, base: Path) -> Node:
        if path in dirs:
            return dirs[path]
        if path == base:                # a library root: a top-level folder labelled by relative path
            node = Node(_label(base, project_dir), base, is_dir=True)
            top.children.append(node)
        else:
            node = Node(path.name, path, is_dir=True)
            folder(path.parent, base).children.append(node)
        dirs[path] = node
        return node

    for f in files:
        f = f.resolve()
        base = _root_of(f, project_dir, extra_roots)
        folder(f.parent, base).children.append(Node(f.name, f))

    def tidy(node: Node):
        # library folders (only at the top) after the project's own folders, then files
        node.children.sort(key=lambda c: (not c.is_dir, not c.path.is_relative_to(project_dir),
                                          order.get(c.path, len(order)) if not c.is_dir else 0, c.name.lower()))
        for c in node.children:
            if c.is_dir:
                tidy(c)
    tidy(top)
    return top
