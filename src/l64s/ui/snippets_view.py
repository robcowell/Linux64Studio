"""Code Snippets: a library of small BASIC and assembler routines to insert into a program, in
CBM prg Studio's Snippets.xml format. BASIC snippets are numbered (and their !n labels
resolved) as they're inserted."""
from __future__ import annotations

import re
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from .. import snippets as sn  # noqa: E402
from ..settings import config_dir  # noqa: E402
from .editor import EditorPage  # noqa: E402


def library_path() -> Path:
    return config_dir() / "snippets.xml"


def line_numbers(text: str) -> list[tuple[int, int]]:
    """(line index in the file, BASIC line number) for each numbered line."""
    out = []
    for i, line in enumerate(text.split("\n")):
        m = re.match(r"\s*(\d+)", line)
        if m:
            out.append((i, int(m.group(1))))
    return out


def last_line_number(text: str) -> int | None:
    nums = [n for _, n in line_numbers(text)]
    return max(nums) if nums else None


def basic_placement(existing: str, new: str) -> tuple[int | None, list[int]]:
    """Where numbered BASIC lines belong in a file: the line index to insert before (None for the
    end), and any line numbers that are already used."""
    have = line_numbers(existing)
    new_nums = [n for _, n in line_numbers(new)]
    clashes = sorted(set(new_nums) & {n for _, n in have})
    if not new_nums:
        return None, clashes
    first = min(new_nums)
    after = [i for i, n in have if n > first]
    return (after[0] if after else None), clashes


class SnippetRow(Gtk.ListBoxRow):
    def __init__(self, snippet: sn.Snippet):
        super().__init__()
        self.snippet = snippet
        self.label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, margin_start=10, margin_end=6, margin_top=3, margin_bottom=3)
        self.set_child(self.label)
        self.refresh()

    def refresh(self):
        self.label.set_text(self.snippet.description or "(no description)")
        self.set_tooltip_text(self.snippet.description)


class SnippetsView(EditorPage):
    kind = "snippets"

    def __init__(self, kickass: bool = False, insert_cb=None, get_target=None, path: Path | None = None):
        super().__init__(None)
        self.kickass = kickass
        self.insert_cb = insert_cb
        self.get_target = get_target          # () -> the SourceEditor code goes into, or None
        self.library = path or library_path()
        self.current: sn.Snippet | None = None
        self._loading = False
        try:
            self.items = sn.load(self.library) if self.library.exists() else sn.builtin()
            msg = f"{len(self.items)} snippets in {self.library}" if self.library.exists() else \
                f"{len(self.items)} built-in snippets. Your changes are saved in {self.library}"
        except (OSError, sn.SnippetError) as e:
            self.items = sn.builtin()
            msg = f"Couldn't read {self.library} ({e}): showing the built-in snippets"

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=340,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)

        # ---- the list
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_top=8, margin_bottom=8)
        self.search = Gtk.SearchEntry(placeholder_text="Search snippets")
        self.search.connect("search-changed", lambda *_: self.list.invalidate_filter())
        left.append(self.search)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["navigation-sidebar"])
        self.list.set_filter_func(self._filter)
        self.list.set_sort_func(self._sort)
        self.list.set_header_func(self._header)
        self.list.connect("row-selected", lambda _l, row: self._select(row))
        self.list.connect("row-activated", lambda *_: self._insert())
        left.append(Gtk.ScrolledWindow(child=self.list, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        bar = Gtk.Box(spacing=4)
        for icon, tip, cb in (("list-add-symbolic", "New snippet", self._new),
                              ("edit-copy-symbolic", "Duplicate this snippet", self._duplicate),
                              ("user-trash-symbolic", "Delete this snippet", self._delete)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", lambda *_, cb=cb: cb())
            bar.append(b)
        more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Import, export and restore")
        menu = Gio.Menu()
        menu.append("Import snippets (CBM prg Studio's Snippets.xml)…", "snip.import")
        menu.append("Export snippets…", "snip.export")
        menu.append("Add back the built-in snippets", "snip.restore")
        more.set_menu_model(menu)
        group = Gio.SimpleActionGroup()
        for name, cb in (("import", self._import_dialog), ("export", self._export_dialog), ("restore", self._restore)):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_, cb=cb: cb())
            group.add_action(a)
        self.insert_action_group("snip", group)
        bar.append(more)
        bar.append(Gtk.Box(hexpand=True))
        save = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save the library (Ctrl+S)")
        save.connect("clicked", lambda *_: self.save())
        bar.append(save)
        left.append(bar)
        paned.set_start_child(left)

        # ---- the snippet
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=8, margin_top=8,
                        margin_bottom=8)
        head = Gtk.Box(spacing=6)
        self.desc = Gtk.Entry(hexpand=True, placeholder_text="Description")
        self.desc.connect("changed", lambda *_: self._edited())
        head.append(self.desc)
        self.type = Gtk.DropDown.new_from_strings(sn.TYPES)
        self.type.set_tooltip_text("Machine Code snippets are assembler; the others are BASIC")
        self.type.connect("notify::selected", lambda *_: self._edited())
        head.append(self.type)
        right.append(head)
        self.hint = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.hint)
        self.code = Gtk.TextView(monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                                 css_classes=["card", "monospace"])
        self.code.get_buffer().connect("changed", lambda *_: self._edited())
        right.append(Gtk.ScrolledWindow(child=self.code, vexpand=True, min_content_height=120))

        prow = Gtk.Box(spacing=6)
        prow.append(Gtk.Label(label="<b>As inserted</b>", use_markup=True, xalign=0, hexpand=True))
        self.lines_box = Gtk.Box(spacing=6)
        self.lines_box.append(Gtk.Label(label="Start line"))
        self.start = Gtk.SpinButton.new_with_range(0, 63999, 10)
        self.start.set_value(1000)
        self.start.connect("value-changed", lambda *_: self._preview())
        self.lines_box.append(self.start)
        self.lines_box.append(Gtk.Label(label="Step"))
        self.step = Gtk.SpinButton.new_with_range(1, 1000, 1)
        self.step.set_value(10)
        self.step.connect("value-changed", lambda *_: self._preview())
        self.lines_box.append(self.step)
        after = Gtk.Button(label="After the program", tooltip_text="Start after the last line of the BASIC file "
                                                                   "you're inserting into")
        after.connect("clicked", lambda *_: self._after_program())
        self.lines_box.append(after)
        prow.append(self.lines_box)
        right.append(prow)
        self.preview = Gtk.TextView(editable=False, monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                                    css_classes=["card", "monospace"])
        right.append(Gtk.ScrolledWindow(child=self.preview, vexpand=True, min_content_height=100))
        btns = Gtk.Box(spacing=6)
        cp = Gtk.Button(label="Copy")
        cp.connect("clicked", lambda *_: self._copy())
        btns.append(cp)
        ins = Gtk.Button(label="Insert into Editor", css_classes=["suggested-action"],
                         tooltip_text="Insert into the last source file used (or double-click the snippet)")
        ins.connect("clicked", lambda *_: self._insert())
        btns.append(ins)
        right.append(btns)
        paned.set_end_child(right)

        self.status = Gtk.Label(xalign=0, margin_start=10, margin_bottom=6, wrap=True, css_classes=["dim-label"],
                                label=msg)
        self.append(self.status)
        self._fill()

    @property
    def title(self) -> str:
        return "Code Snippets"

    # ================================================================== the list
    def _fill(self, select: sn.Snippet | None = None):
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        for s in self.items:
            self.list.append(SnippetRow(s))
        target = select or (self.items[0] if self.items else None)
        self._select_snippet(target)

    def _select_snippet(self, snippet):
        i = 0
        while (row := self.list.get_row_at_index(i)) is not None:
            if row.snippet is snippet:
                self.list.select_row(row)
                return
            i += 1
        self._select(None)

    def _sort(self, a, b) -> int:
        ka = (a.snippet.type, self._index(a.snippet))
        kb = (b.snippet.type, self._index(b.snippet))
        return (ka > kb) - (ka < kb)

    def _index(self, snippet) -> int:
        return next((i for i, s in enumerate(self.items) if s is snippet), len(self.items))

    def _filter(self, row) -> bool:
        q = self.search.get_text().strip().lower()
        s = row.snippet
        return not q or q in s.description.lower() or q in s.code.lower() or q in sn.TYPES[s.type].lower()

    def _header(self, row, before):
        if before is None or before.snippet.type != row.snippet.type:
            row.set_header(Gtk.Label(label=f"<b>{sn.TYPES[row.snippet.type]}</b>", use_markup=True, xalign=0,
                                     margin_start=6, margin_top=8, margin_bottom=2))
        else:
            row.set_header(None)

    def _row_of(self, snippet):
        i = 0
        while (row := self.list.get_row_at_index(i)) is not None:
            if row.snippet is snippet:
                return row
            i += 1
        return None

    def _select(self, row):
        self.current = row.snippet if row else None
        self._loading = True
        try:
            s = self.current
            self.desc.set_text(s.description if s else "")
            self.type.set_selected(s.type if s else 4)
            self.code.get_buffer().set_text(s.code if s else "")
            for w in (self.desc, self.type, self.code):
                w.set_sensitive(s is not None)
        finally:
            self._loading = False
        self._preview()

    # ================================================================== editing
    def _edited(self):
        if self._loading or not self.current:
            return
        s = self.current
        old_type = s.type
        s.description = self.desc.get_text()
        s.type = self.type.get_selected()
        b = self.code.get_buffer()
        s.code = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        row = self._row_of(s)
        if row:
            row.refresh()
            if s.type != old_type:
                self.list.invalidate_sort()
                self.list.invalidate_headers()
        self.set_modified(True)
        self._preview()

    def _new(self):
        kind = self.current.type if self.current else 4
        s = sn.Snippet(kind, "New snippet", [])
        self.items.append(s)
        self.list.append(SnippetRow(s))
        self._select_snippet(s)
        self.desc.grab_focus()
        self.set_modified(True)

    def _duplicate(self):
        if not self.current:
            return
        s = sn.Snippet(self.current.type, self.current.description + " (copy)", list(self.current.lines))
        self.items.append(s)
        self.list.append(SnippetRow(s))
        self._select_snippet(s)
        self.set_modified(True)

    def _delete(self):
        s = self.current
        if not s:
            return
        i = self.items.index(s)
        self.items.remove(s)
        row = self._row_of(s)
        if row:
            self.list.remove(row)
        nxt = self.items[min(i, len(self.items) - 1)] if self.items else None
        self._select_snippet(nxt)
        self.set_modified(True)
        self.status.set_text(f"Deleted “{s.description}” (not saved until you save the library)")

    def _restore(self):
        n = sn.merge(self.items, sn.builtin())
        if n:
            self._fill(self.current)
            self.set_modified(True)
        self.status.set_text(f"Added back {n} built-in snippet{'s' if n != 1 else ''}" if n
                             else "All the built-in snippets are already here")

    def save(self) -> None:
        try:
            sn.save(self.items, self.library)
        except OSError as e:
            self.status.set_text(f"Couldn't save {self.library}: {e}")
            return
        self.set_modified(False)
        self.status.set_text(f"Saved {len(self.items)} snippets to {self.library}")

    # ================================================================== output
    def _target(self):
        return self.get_target() if self.get_target else None

    def output(self) -> str:
        s = self.current
        if not s:
            return ""
        return sn.expand(s, self.start.get_value_as_int(), self.step.get_value_as_int(), self.kickass)

    def _preview(self):
        s = self.current
        basic = bool(s and s.is_basic)
        self.lines_box.set_visible(basic)
        if not s:
            self.hint.set_text("")
            self.preview.get_buffer().set_text("")
            return
        self.hint.set_text(
            "BASIC without line numbers. Start a line with !1-!9 to label it, and use !n after GOTO, GOSUB or "
            "THEN to jump there." if basic else
            "Assembler (CBM prg Studio syntax" + (", converted to Kick Assembler when inserted)." if self.kickass
                                                  else ")."))
        try:
            text = self.output()
        except sn.SnippetError as e:
            text = f"({e})"
        self.preview.get_buffer().set_text(text)

    def _after_program(self):
        t = self._target()
        if not t or not t.is_basic:
            self.status.set_text("Open the BASIC file to insert into first")
            return
        b = t.buffer
        last = last_line_number(b.get_text(b.get_start_iter(), b.get_end_iter(), False))
        step = self.step.get_value_as_int()
        start = 10 if last is None else (last // step + 1) * step
        self.start.set_value(start)
        self.status.set_text(f"{t.title} ends at line {last}: starting at {start}" if last is not None
                             else f"{t.title} has no lines yet: starting at {start}")

    def _copy(self):
        try:
            text = self.output()
        except sn.SnippetError as e:
            self.status.set_text(str(e))
            return
        Gdk.Display.get_default().get_clipboard().set(text)
        self.status.set_text("Copied the snippet")

    def _insert(self):
        s = self.current
        if not s or not self.insert_cb:
            return
        try:
            text = self.output()
        except sn.SnippetError as e:
            self.status.set_text(str(e))
            return
        t = self._target()
        if t is not None and t.is_basic != s.is_basic:
            self.status.set_text(f"“{s.description}” is {'BASIC' if s.is_basic else 'assembler'}, but "
                                 f"{t.title} is {'BASIC' if t.is_basic else 'assembler'}: open the right kind "
                                 f"of file, or use Copy")
            return
        if t is not None and s.is_basic and not getattr(t, "is_pbasic", False):
            b = t.buffer
            before, clashes = basic_placement(b.get_text(b.get_start_iter(), b.get_end_iter(), False), text)
            if clashes:
                shown = ", ".join(map(str, clashes[:5])) + ("…" if len(clashes) > 5 else "")
                self.status.set_text(f"{t.title} already has line{'s' if len(clashes) > 1 else ''} {shown}: "
                                     f"choose another start line, or After the program")
                return
            # put the lines where their numbers belong, not wherever the cursor is
            it = b.get_end_iter() if before is None else b.get_iter_at_line(before)[1]
            b.place_cursor(it)
        where = self.insert_cb(text)
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")

    # ================================================================== files
    def _file_dialog(self, title: str) -> Gtk.FileDialog:
        dlg = Gtk.FileDialog(title=title)
        flt = Gtk.FileFilter(name="Snippets (*.xml)")
        flt.add_pattern("*.xml")
        flt.add_pattern("*.XML")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(flt)
        dlg.set_filters(filters)
        return dlg

    def import_file(self, path: Path) -> None:
        try:
            new = sn.load(path)
        except (OSError, sn.SnippetError) as e:
            self.status.set_text(f"Couldn't import {path.name}: {e}")
            return
        n = sn.merge(self.items, new)
        if n:
            self._fill(self.current)
            self.set_modified(True)
        self.status.set_text(f"Imported {n} of the {len(new)} snippets in {path.name}"
                             + (f" ({len(new) - n} were already here)" if n < len(new) else ""))

    def _import_dialog(self):
        dlg = self._file_dialog("Import snippets")

        def done(d, res):
            try:
                self.import_file(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self.get_root(), None, done)

    def _export_dialog(self):
        dlg = self._file_dialog("Export snippets")
        dlg.set_initial_name("Snippets.xml")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            try:
                sn.save(self.items, dest)
            except OSError as e:
                self.status.set_text(f"Couldn't write {dest.name}: {e}")
                return
            self.status.set_text(f"Exported {len(self.items)} snippets to {dest}")
        dlg.save(self.get_root(), None, done)
