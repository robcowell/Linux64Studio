"""Tools → UTF-8 Check: the characters in the source that aren't plain ASCII, where they are, and
ASCII to put in their place (curly quotes, dashes, non-breaking spaces pasted from the web)."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from .. import utf8check  # noqa: E402
from .editor import EditorPage  # noqa: E402


class Utf8CheckView(EditorPage):
    kind = "utf8"

    def __init__(self, get_files, get_editor_for, open_at):
        """`get_files(scope)` gives the files to check ("file" or "project"); `get_editor_for(path)`
        an open editor (for its unsaved text) or None; `open_at(path, line, column)` shows one."""
        super().__init__(None)
        self.get_files, self.get_editor_for, self.open_at = get_files, get_editor_for, open_at
        self.findings: list[utf8check.Finding] = []
        bar = Gtk.Box(spacing=8, margin_start=8, margin_end=8, margin_top=8)
        self.scope = Gtk.DropDown.new_from_strings(["Current file", "Whole project"])
        self.scope.connect("notify::selected", lambda *_: self.refresh())
        check = Gtk.Button(label="Check Again", tooltip_text="Look at the files as they are now")
        check.connect("clicked", lambda *_: self.refresh())
        self.fix_btn = Gtk.Button(label="Replace All with ASCII", css_classes=["suggested-action"],
                                  tooltip_text="Curly quotes to straight ones, dashes to -, … to ..., no-break spaces "
                                               "to spaces; characters with no ASCII are left (one undo a file)")
        self.fix_btn.connect("clicked", lambda *_: self.fix_all())
        for w in (self.scope, check, Gtk.Box(hexpand=True), self.fix_btn):
            bar.append(w)
        self.append(bar)
        self.summary = Gtk.Label(xalign=0, wrap=True, margin_start=8, margin_top=6, css_classes=["dim-label"])
        self.append(self.summary)
        self.list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE,
                                margin_start=8, margin_end=8, margin_top=6, margin_bottom=8)
        self.list.connect("row-activated", lambda _l, row: self.open_at(Path(row.finding.file), row.finding.line,
                                                                        row.finding.column))
        self.append(Gtk.ScrolledWindow(child=self.list, vexpand=True))
        self.refresh()

    @property
    def title(self) -> str:
        return "UTF-8 Check"

    def save(self):
        self.set_modified(False)

    def _text(self, path: Path) -> str | None:
        ed = self.get_editor_for(path)
        return ed.get_text() if ed is not None else None

    def refresh(self):
        scope = "project" if self.scope.get_selected() == 1 else "file"
        files = self.get_files(scope)
        self.findings = []
        for f in files:
            try:
                self.findings += utf8check.check_file(f, self._text(f))
            except OSError as e:
                self.summary.set_text(f"Can't read {f.name}: {e.strerror}")
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        for fd in self.findings:
            row = Gtk.ListBoxRow()
            row.finding = fd
            box = Gtk.Box(spacing=12, margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)
            box.append(Gtk.Label(label=f"{Path(fd.file).name}:{fd.line}:{fd.column}", xalign=0, width_chars=22,
                                 css_classes=["monospace", "dim-label"]))
            box.append(Gtk.Label(label=fd.describe(), xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
            row.set_child(box)
            self.list.append(row)
        if not files:
            self.summary.set_text("Open a source file (or a project) to check.")
        elif not self.findings:
            self.summary.set_text(f"All plain ASCII: {len(files)} file{'s' if len(files) != 1 else ''} checked.")
        else:
            fixable = sum(1 for f in self.findings if f.replacement is not None)
            self.summary.set_text(f"{len(self.findings)} character{'s' if len(self.findings) != 1 else ''} that "
                                  f"aren't ASCII in {len({f.file for f in self.findings})} file(s); {fixable} have "
                                  f"an ASCII replacement. Double-click one to go to it.")
        self.fix_btn.set_sensitive(any(f.replacement is not None for f in self.findings))

    def fix_all(self):
        """Put ASCII in, in the editors (as one undo each), opening the files that aren't open."""
        for path in sorted({Path(f.file) for f in self.findings if f.replacement is not None}):
            ed = self.get_editor_for(path, open_it=True)
            if ed is None:
                continue
            new, done, _left = utf8check.fix(ed.get_text(), basic=path.suffix.lower() in (".bas", ".pbas"))
            if done:
                ed.replace_text(new)
        self.refresh()
