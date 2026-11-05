"""The Breakpoints tab of the bottom panel, as CBM prg Studio's Breakpoints window: every breakpoint
in the project (open files and closed), each with a switch, the line it's on and, after a build, the
address it stops at. Double-click one to go to it. l64s.breakpoints keeps them."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from ..breakpoints import Breakpoint  # noqa: E402


class BreakpointsPanel(Gtk.Box):
    def __init__(self, *, items: Callable[[], list[Breakpoint]], line_text: Callable[[str, int], str],
                 address: Callable[[str, int], int | None], base: Callable[[], Path | None],
                 set_enabled: Callable[[Breakpoint, bool], None], set_all: Callable[[bool], None],
                 remove: Callable[[Breakpoint], None], remove_all: Callable[[], None],
                 go_to: Callable[[Breakpoint], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=6,
                         margin_top=6, margin_bottom=6)
        self._items, self._line_text, self._address, self._base = items, line_text, address, base
        self._set_enabled, self._remove, self._go_to = set_enabled, remove, go_to
        bar = Gtk.Box(spacing=6)
        self.count = Gtk.Label(xalign=0, hexpand=True, css_classes=["dim-label"])
        bar.append(self.count)
        for label, tip, cb in (("All On", "Switch every breakpoint on", lambda *_: set_all(True)),
                               ("All Off", "Switch every breakpoint off (they stay, but don't stop)",
                                lambda *_: set_all(False)),
                               ("Remove All", "Remove every breakpoint in the project", lambda *_: remove_all())):
            b = Gtk.Button(label=label, tooltip_text=tip, css_classes=["flat"])
            b.connect("clicked", cb)
            bar.append(b)
        self.append(bar)
        self.list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", lambda _l, row: self._go_to(row.bp))
        self.empty = Gtk.Label(wrap=True, vexpand=True, css_classes=["dim-label"],
                               label="No breakpoints. Click a line number in the editor's margin, or press F9, "
                                     "to add one. (Breakpoints written in the source with the breakpoint "
                                     "directive come from the build, so they aren't listed.)")
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=self.list, vexpand=True, min_content_height=100), "list")
        self.stack.add_named(self.empty, "empty")
        self.append(self.stack)

    def _where(self, file: str) -> str:
        base = self._base()
        try:
            return os.path.relpath(file, base) if base else Path(file).name
        except ValueError:
            return file

    def refresh(self):
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        items = self._items()
        for bp in items:
            row = Gtk.ListBoxRow()
            row.bp = bp
            box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=2, margin_bottom=2)
            on = Gtk.CheckButton(active=bp.enabled, tooltip_text="On: stops here. Off: kept, but doesn't stop")
            on.connect("toggled", lambda b, bp=bp: self._set_enabled(bp, b.get_active()))
            box.append(on)
            where = Gtk.Label(label=f"{self._where(bp.file)}:{bp.line}", xalign=0, width_chars=22,
                              ellipsize=Pango.EllipsizeMode.START, tooltip_text=bp.file)
            text = Gtk.Label(label=self._line_text(bp.file, bp.line).strip(), xalign=0, hexpand=True,
                             ellipsize=Pango.EllipsizeMode.END, css_classes=["monospace"])
            addr = self._address(bp.file, bp.line)
            at = Gtk.Label(label=f"${addr:04X}" if addr is not None else "", width_chars=6, xalign=1,
                           css_classes=["monospace", "dim-label"],
                           tooltip_text="Where it stops, in the last build" if addr is not None else None)
            remove = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Remove this breakpoint",
                                css_classes=["flat", "circular"], valign=Gtk.Align.CENTER)
            remove.connect("clicked", lambda *_, bp=bp: self._remove(bp))
            for w in (where, text, at, remove):
                box.append(w)
            if not bp.enabled:
                for w in (where, text):
                    w.add_css_class("dim-label")
            row.set_child(box)
            self.list.append(row)
        n, on = len(items), sum(1 for b in items if b.enabled)
        self.count.set_text("" if not n else f"{n} breakpoint{'s' if n != 1 else ''}" + (f", {n - on} off" if on < n else ""))
        self.stack.set_visible_child_name("list" if items else "empty")
