"""The Find Results tab of the bottom panel: Find in Files, as CBM prg Studio's. Type what to find;
results are grouped by file with the match highlighted. Double-click (or Enter on) one to open the
file with the match selected. l64s.findfiles does the searching."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from ..findfiles import MAX_MATCHES, SCOPES, Match, Options, excerpt, search  # noqa: E402

class _Row(GObject.Object):
    def __init__(self, file: str = "", matches: list[Match] | None = None, match: Match | None = None):
        super().__init__()
        self.file, self.matches, self.match = file, matches, match


def match_markup(m: Match) -> str:
    """The line with the match in bold on a highlight."""
    before, hit, after = excerpt(m)
    esc = GLib.markup_escape_text
    return f"{esc(before)}<span weight='bold' background='#e5a50a66'>{esc(hit)}</span>{esc(after)}"


class FindPanel(Gtk.Box):
    def __init__(self, get_texts: Callable[[str], dict[str, str]], open_match: Callable[[Match], None],
                 base: Callable[[], Path | None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=6,
                         margin_top=6, margin_bottom=6)
        self.get_texts, self.open_match, self.base = get_texts, open_match, base
        bar = Gtk.Box(spacing=6)
        self.entry = Gtk.SearchEntry(placeholder_text="Find in files", hexpand=True, search_delay=250)
        self.entry.connect("search-changed", lambda *_: self.run())
        self.entry.connect("activate", lambda *_: self.run())
        bar.append(self.entry)
        self.case = Gtk.ToggleButton(label="Aa", tooltip_text="Match case")
        self.word = Gtk.ToggleButton(label="W", tooltip_text="Whole word (a label, not part of a longer one)")
        self.regex = Gtk.ToggleButton(label=".*", tooltip_text="Regular expression")
        for b in (self.case, self.word, self.regex):
            b.add_css_class("flat")
            b.connect("toggled", lambda *_: self.run())
            bar.append(b)
        self.scope = Gtk.DropDown.new_from_strings([label for _k, label in SCOPES])
        self.scope.set_tooltip_text("Where to look")
        self.scope.connect("notify::selected", lambda *_: self.run())
        bar.append(self.scope)
        again = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Search again", css_classes=["flat"])
        again.connect("clicked", lambda *_: self.run())
        bar.append(again)
        self.count = Gtk.Label(css_classes=["dim-label"], width_chars=12, xalign=1)
        bar.append(self.count)
        self.append(bar)

        f = Gtk.SignalListItemFactory()
        f.connect("setup", self._setup)
        f.connect("bind", self._bind)
        self.view = Gtk.ListView(factory=f, css_classes=["navigation-sidebar"])
        self.view.connect("activate", self._activate)
        self.model: Gtk.TreeListModel | None = None
        self.message = Gtk.Label(css_classes=["dim-label"], wrap=True, vexpand=True,
                                 label="Type something to find in the project's sources (Ctrl+Shift+F).")
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=self.view, vexpand=True, min_content_height=100), "list")
        self.stack.add_named(self.message, "message")
        self.stack.set_visible_child_name("message")
        self.append(self.stack)

    # ---------------------------------------------------------------- searching
    def options(self) -> Options:
        return Options(self.entry.get_text(), self.case.get_active(), self.word.get_active(),
                       self.regex.get_active())

    def scope_key(self) -> str:
        return SCOPES[self.scope.get_selected()][0]

    def start(self, text: str | None):
        """Ctrl+Shift+F: search for ``text`` (the selection or the word at the cursor), or just focus."""
        if text:
            self.entry.set_text(text)       # (runs the search)
        else:
            self.run()
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def run(self):
        opts = self.options()
        if not opts.text:
            self._show_message("Type something to find in the project's sources (Ctrl+Shift+F).")
            self.count.set_text("")
            return
        try:
            matches, more = search(self.get_texts(self.scope_key()), opts)
        except ValueError as e:
            self._show_message(str(e))
            self.count.set_text("")
            return
        by_file: dict[str, list[Match]] = {}
        for m in matches:
            by_file.setdefault(m.file, []).append(m)
        files = len(by_file)
        self.count.set_text(f"{len(matches)}{'+' if more else ''} in {files} file{'s' if files != 1 else ''}"
                            if matches else "")
        if not matches:
            self._show_message(f"Nothing found for “{opts.text}”.")
            return
        store = Gio.ListStore(item_type=_Row)
        for file, ms in by_file.items():
            store.append(_Row(file=file, matches=ms))

        def children(r: _Row):
            if r.matches is None:
                return None
            st = Gio.ListStore(item_type=_Row)
            for m in r.matches:
                st.append(_Row(match=m))
            return st
        self.model = Gtk.TreeListModel.new(store, False, True, children)        # files open
        self.view.set_model(Gtk.NoSelection(model=self.model))
        self.stack.set_visible_child_name("list")
        if more:
            self.count.set_tooltip_text(f"Only the first {MAX_MATCHES} matches are shown")
        else:
            self.count.set_tooltip_text(None)

    def _show_message(self, text: str):
        self.message.set_text(text)
        self.stack.set_visible_child_name("message")

    # ---------------------------------------------------------------- the list
    def _where(self, file: str) -> str:
        base = self.base()
        try:
            return os.path.relpath(file, base) if base else Path(file).name
        except ValueError:
            return file

    def _setup(self, _f, li):
        box = Gtk.Box(spacing=8)
        box.append(Gtk.Label(xalign=1, width_chars=6, css_classes=["dim-label", "caption", "monospace"]))
        box.append(Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
        box.append(Gtk.Label(xalign=1, css_classes=["dim-label", "caption"]))
        li.set_child(Gtk.TreeExpander(child=box))

    def _bind(self, _f, li):
        exp: Gtk.TreeExpander = li.get_child()
        row: Gtk.TreeListRow = li.get_item()
        exp.set_list_row(row)
        r: _Row = row.get_item()
        num, text, count = list(exp.get_child())
        if r.match is None:
            num.set_visible(False)
            text.set_css_classes(["heading"])
            text.set_text(self._where(r.file))
            count.set_text(str(len(r.matches)))
            exp.set_tooltip_text(r.file)
        else:
            m = r.match
            num.set_visible(True)
            num.set_text(str(m.line))
            text.set_css_classes(["monospace"])
            text.set_markup(match_markup(m))
            count.set_text("")
            exp.set_tooltip_text(f"Line {m.line}, column {m.col + 1}. Double-click to go to it")

    def _activate(self, _view, pos):
        row = self.model.get_item(pos) if self.model else None
        if row is None:
            return
        r: _Row = row.get_item()
        if r.match is None:
            row.set_expanded(not row.get_expanded())
        else:
            self.open_match(r.match)
