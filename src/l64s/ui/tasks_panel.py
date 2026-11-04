"""The Tasks panel: every TODO, FIXME and HACK in the project, as CBM prg Studio's Tasks window.
Double-click (or Enter on) a task to open its file at that line."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ..tasks import Task  # noqa: E402


class TasksPanel(Gtk.Box):
    def __init__(self, on_open: Callable[[Task], None], current_file: Callable[[], Path | None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=6,
                         margin_top=6, margin_bottom=6)
        self.on_open = on_open
        self.current_file = current_file
        self.tasks: list[Task] = []
        self.base: Path | None = None
        bar = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text="Search tasks", hexpand=True)
        self.search.connect("search-changed", lambda *_: self._fill())
        self.only_file = Gtk.CheckButton(label="Current file only")
        self.only_file.connect("toggled", lambda *_: self._fill())
        self.count = Gtk.Label(css_classes=["dim-label"])
        bar.append(self.search)
        bar.append(self.only_file)
        bar.append(self.count)
        self.append(bar)
        self.list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", lambda _l, row: self.on_open(row.task))
        self.empty = Gtk.Label(label="No tasks. Write todo (or a TODO, FIXME or HACK comment) in a source "
                                     "file to add one.", css_classes=["dim-label"], wrap=True, vexpand=True)
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=self.list, vexpand=True, min_content_height=100), "list")
        self.stack.add_named(self.empty, "empty")
        self.append(self.stack)

    def set_tasks(self, tasks: list[Task], base: Path | None):
        """Show these tasks (does nothing if they haven't changed)."""
        if tasks == self.tasks and base == self.base:
            return
        self.tasks, self.base = list(tasks), base
        self._fill()

    def _where(self, t: Task) -> str:
        try:
            return os.path.relpath(t.file, self.base) if self.base else Path(t.file).name
        except ValueError:
            return t.file

    def shown(self) -> list[Task]:
        words = self.search.get_text().lower().split()
        cur = self.current_file() if self.only_file.get_active() else None
        cur = str(cur.resolve()) if cur else None
        out = []
        for t in self.tasks:
            if self.only_file.get_active() and t.file != cur:
                continue
            hay = f"{t.kind} {t.text} {self._where(t)}".lower()
            if all(w in hay for w in words):
                out.append(t)
        return out

    def _fill(self):
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        shown = self.shown()
        for t in shown:
            row = Gtk.ListBoxRow()
            row.task = t
            box = Gtk.Box(spacing=10, margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)
            kind = Gtk.Label(label=t.kind, width_chars=6, xalign=0,
                             css_classes=["caption-heading", "error" if t.kind == "FIXME" else
                                          "warning" if t.kind == "HACK" else "accent"])
            text = Gtk.Label(label=t.text or "(no description)", xalign=0, hexpand=True,
                             ellipsize=Pango.EllipsizeMode.END, tooltip_text=t.text or None)
            where = Gtk.Label(label=f"{self._where(t)}:{t.line}", xalign=1, css_classes=["dim-label", "caption"])
            for w in (kind, text, where):
                box.append(w)
            row.set_child(box)
            self.list.append(row)
        n = len(self.tasks)
        self.count.set_text(f"{len(shown)} of {n}" if len(shown) != n else f"{n} task{'s' if n != 1 else ''}")
        self.stack.set_visible_child_name("list" if shown else "empty")
        if not shown and self.tasks:
            self.empty.set_text("No tasks match.")
        elif not self.tasks:
            self.empty.set_text("No tasks. Write todo (or a TODO, FIXME or HACK comment) in a source file "
                                "to add one.")
