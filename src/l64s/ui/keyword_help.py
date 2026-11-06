"""BASIC Keywords: the BASIC V2 keyword reference (l64s.basic.keywords), searchable, with what each
does, how it's written, an example and its abbreviation. F1 in a BASIC file opens it at the keyword
under the cursor."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from ..basic.keywords import KEYWORDS, SPECIAL, Keyword, describe, lookup  # noqa: E402
from .editor import EditorPage  # noqa: E402

KIND_ORDER = {"statement": 0, "function": 1, "operator": 2, "part of a statement": 3, "variable": 4}


class KeywordHelp(EditorPage):
    kind = "keywords"

    def __init__(self):
        super().__init__(None)
        self.entries: list[Keyword] = sorted(list(KEYWORDS.values()) + list(SPECIAL.values()),
                                             key=lambda k: k.title)
        self.current: Keyword | None = None
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=230, vexpand=True,
                          shrink_start_child=False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_top=8,
                       margin_bottom=8)
        self.search = Gtk.SearchEntry(placeholder_text="Find a keyword")
        self.search.connect("search-changed", lambda *_: self.list.invalidate_filter())
        self.search.connect("activate", lambda *_: self._first_shown())
        left.append(self.search)
        self.list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.list.set_filter_func(self._shown)
        self.list.connect("row-selected", self._selected)
        for k in self.entries:
            row = Gtk.ListBoxRow()
            row.keyword = k
            box = Gtk.Box(spacing=8)
            box.append(Gtk.Label(label=k.title, xalign=0, hexpand=True, css_classes=["monospace"]))
            box.append(Gtk.Label(label=k.kind.split()[0], css_classes=["dim-label", "caption"]))
            row.set_child(box)
            self.list.append(row)
        left.append(Gtk.ScrolledWindow(child=self.list, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        paned.set_start_child(left)

        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=16, margin_end=16,
                              margin_top=12, margin_bottom=12)
        self.heading = Gtk.Label(xalign=0, css_classes=["title-2"], selectable=True)
        self.kind_label = Gtk.Label(xalign=0, css_classes=["dim-label"])
        self.form = Gtk.Label(xalign=0, wrap=True, selectable=True, css_classes=["monospace"])
        self.text = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=70)
        self.example_title = Gtk.Label(label="Example", xalign=0, css_classes=["heading"])
        self.example = Gtk.Label(xalign=0, selectable=True, css_classes=["monospace", "card"],
                                 wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        self.example.set_margin_top(2)
        self.abbrev = Gtk.Label(xalign=0, css_classes=["dim-label"], use_markup=True)
        copy = Gtk.Button(label="Copy Example", halign=Gtk.Align.START)
        copy.connect("clicked", lambda *_: self._copy())
        self.copy_button = copy
        for w in (self.heading, self.kind_label, self.form, self.text, self.example_title, self.example,
                  copy, self.abbrev):
            self.detail.append(w)
        note = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"], vexpand=True,
                         valign=Gtk.Align.END, label=(
                             "Keywords are written in lower case, as listings show them; a capital letter is a "
                             "shifted one, so an abbreviation such as pO is p then Shift+O. In the form, <...> "
                             "is what you supply and [...] may be left out. Press F1 in a BASIC file for the "
                             "keyword under the cursor, or hover over it."))
        self.detail.append(note)
        paned.set_end_child(Gtk.ScrolledWindow(child=self.detail, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.append(paned)
        self.show_keyword(self.entries[0])

    @property
    def title(self) -> str:
        return "BASIC Keywords"

    def save(self):
        pass

    # ------------------------------------------------------------------
    def _shown(self, row) -> bool:
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        k = row.keyword
        return q in k.name or q in k.title.lower() or (len(q) > 2 and q in k.text.lower())

    def _first_shown(self):
        row = self.list.get_row_at_index(0)
        i = 0
        while row is not None and not self._shown(row):
            i += 1
            row = self.list.get_row_at_index(i)
        if row is not None:
            self.list.select_row(row)

    def _selected(self, _lb, row):
        if row is not None:
            self.show_keyword(row.keyword, select=False)

    def show(self, word: str) -> bool:
        """Show a keyword's help (by name, any case). False if it isn't one."""
        k = lookup(word)
        if k is None:
            return False
        self.search.set_text("")
        self.show_keyword(k)
        return True

    def show_keyword(self, k: Keyword, select: bool = True):
        self.current = k
        self.heading.set_text(k.title)
        self.kind_label.set_text(k.kind.capitalize())
        self.form.set_text(k.form)
        self.text.set_text(k.text)
        for w in (self.example_title, self.example, self.copy_button):
            w.set_visible(bool(k.example))
        self.example.set_text(k.example)
        self.abbrev.set_visible(bool(k.abbrev))
        if k.abbrev:
            how = ("a question mark" if k.abbrev == "?" else
                   f"{GLib.markup_escape_text(k.abbrev[:-1])} then Shift+{k.abbrev[-1]}")
            self.abbrev.set_markup(f"Abbreviation: <tt>{GLib.markup_escape_text(k.abbrev)}</tt> ({how})")
        if select:
            i = 0
            while (row := self.list.get_row_at_index(i)) is not None:
                if row.keyword is k:
                    self.list.select_row(row)
                    GLib.idle_add(lambda r=row: (r.grab_focus(), False)[1])
                    break
                i += 1

    def _copy(self):
        if self.current and self.current.example:
            Gdk.Display.get_default().get_clipboard().set(self.current.example)

    def text_of_current(self) -> str:
        return describe(self.current) if self.current else ""
