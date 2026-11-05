"""Find and Replace in the file being edited: a bar across the top of the source editor (Ctrl+F,
or Ctrl+H for replacing). Every match is highlighted; Enter / Shift+Enter (or F3 / Shift+F3) go to
the next and previous, wrapping round; Escape closes it.

GtkSourceView's search does the matching and highlighting. It's given the same pattern as Find in
Files (l64s.findfiles), so Aa, W and .* mean the same in both. With .* on, it replaces too (\1 is
group 1); otherwise the bar puts the replacement in as typed, since GtkSourceView reads backslashes in
a replacement that refers to a group. Either way, Undo undoes a Replace All in one step."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import GLib, Gdk, Gtk, GtkSource  # noqa: E402

from ..findfiles import Options, editor_search  # noqa: E402


class FindBar(Gtk.Revealer):
    def __init__(self, view: GtkSource.View):
        super().__init__(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.view, self.buffer = view, view.get_buffer()
        self.settings = GtkSource.SearchSettings(wrap_around=True, regex_enabled=True)
        self.context = GtkSource.SearchContext.new(self.buffer, self.settings)
        self.context.set_highlight(False)
        self._applied: Options | None = None      # what the search was last set to

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=6, margin_end=6,
                      margin_top=4, margin_bottom=4, css_classes=["toolbar"])
        find_row = Gtk.Box(spacing=4)
        self.entry = Gtk.SearchEntry(placeholder_text="Find", hexpand=True)
        self.entry.connect("search-changed", lambda *_: self._update(jump=True))
        self.entry.connect("activate", lambda *_: self.next())
        self.entry.connect("previous-match", lambda *_: self.previous())
        self.entry.connect("next-match", lambda *_: self.next())
        self.entry.connect("stop-search", lambda *_: self.close())
        find_row.append(self.entry)
        self.count = Gtk.Label(css_classes=["dim-label", "caption"], width_chars=9, xalign=1)
        find_row.append(self.count)
        prev = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Previous (Shift+Enter, Shift+F3)",
                          css_classes=["flat"])
        prev.connect("clicked", lambda *_: self.previous())
        nxt = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="Next (Enter, F3)", css_classes=["flat"])
        nxt.connect("clicked", lambda *_: self.next())
        find_row.append(prev)
        find_row.append(nxt)
        self.case = Gtk.ToggleButton(label="Aa", tooltip_text="Match case", css_classes=["flat"])
        self.word = Gtk.ToggleButton(label="W", tooltip_text="Whole word", css_classes=["flat"])
        self.regex = Gtk.ToggleButton(label=".*", tooltip_text="Regular expression", css_classes=["flat"])
        for b in (self.case, self.word, self.regex):
            b.connect("toggled", lambda *_: self._update(jump=False))
            find_row.append(b)
        self.replace_toggle = Gtk.ToggleButton(icon_name="edit-find-replace-symbolic", css_classes=["flat"],
                                               tooltip_text="Replace (Ctrl+H)")
        self.replace_toggle.connect("toggled", lambda b: self.replace_row.set_visible(b.get_active()))
        find_row.append(self.replace_toggle)
        close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Close (Escape)", css_classes=["flat"])
        close.connect("clicked", lambda *_: self.close())
        find_row.append(close)
        box.append(find_row)

        self.replace_row = Gtk.Box(spacing=4, visible=False)
        self.with_entry = Gtk.Entry(placeholder_text="Replace with", hexpand=True)
        self.with_entry.connect("activate", lambda *_: self.replace())
        self.replace_row.append(self.with_entry)
        one = Gtk.Button(label="Replace", tooltip_text="Replace this match and go to the next")
        one.connect("clicked", lambda *_: self.replace())
        every = Gtk.Button(label="Replace All")
        every.connect("clicked", lambda *_: self.replace_all())
        self.replace_row.append(one)
        self.replace_row.append(every)
        box.append(self.replace_row)
        self.problem = Gtk.Label(css_classes=["error", "caption"], xalign=0, visible=False)
        box.append(self.problem)
        self.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.context.connect("notify::occurrences-count", lambda *_: self._show_count())
        self.buffer.connect("mark-set", lambda _b, _it, mark: mark.get_name() == "insert" and self._show_count())

    # ---------------------------------------------------------------- opening and closing
    def open(self, text: str = "", replace: bool = False):
        if text:
            self.entry.set_text(text)
        self.replace_toggle.set_active(replace or self.replace_toggle.get_active() and self.get_reveal_child())
        self.set_reveal_child(True)
        self.context.set_highlight(True)
        self._update(jump=False)
        if replace and text:
            self.with_entry.grab_focus()
        else:
            self.entry.grab_focus()
            self.entry.select_region(0, -1)

    def close(self):
        self.set_reveal_child(False)
        self.context.set_highlight(False)
        self.view.grab_focus()

    def _key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.SHIFT_MASK:
            self.previous()
            return True
        return False

    # ---------------------------------------------------------------- searching
    def _options(self) -> Options:
        return Options(self.entry.get_text(), self.case.get_active(), self.word.get_active(), self.regex.get_active())

    def _sync(self):
        """Apply the text as it is now: the entry waits a moment after typing before it searches."""
        if self._options() != self._applied:
            self._update(jump=False)

    def _update(self, jump: bool):
        """Apply the search text and options; ``jump`` to the first match from the cursor."""
        opts = self._options()
        self._applied = opts
        try:
            text, case = editor_search(opts)
        except ValueError as e:
            self.problem.set_text(str(e))
            self.problem.set_visible(True)
            self.settings.set_search_text(None)
            self._show_count()
            return
        self.problem.set_visible(False)
        self.settings.set_case_sensitive(case)
        self.settings.set_search_text(text or None)
        if jump and text:
            sel = self.buffer.get_selection_bounds()
            if sel:
                start = sel[0]
            else:                  # the cursor may be inside a match (the word it opened with): start before it
                start = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                line_start = start.copy()
                line_start.set_line_offset(0)
                start.backward_chars(len(opts.text) if not opts.regex else start.get_line_offset())
                if start.compare(line_start) < 0:
                    start = line_start
            self._go(self.context.forward(start))
        self._show_count()

    def _go(self, found) -> bool:
        ok, start, end, _wrapped = found
        if not ok:
            return False
        self.buffer.select_range(start, end)
        self.view.scroll_to_mark(self.buffer.get_insert(), 0.2, False, 0, 0.5)
        return True

    def next(self):
        self._sync()
        if not self.settings.get_search_text():
            return
        sel = self.buffer.get_selection_bounds()
        after = sel[1] if sel else self.buffer.get_iter_at_mark(self.buffer.get_insert())
        self._go(self.context.forward(after))

    def previous(self):
        self._sync()
        if not self.settings.get_search_text():
            return
        sel = self.buffer.get_selection_bounds()
        before = sel[0] if sel else self.buffer.get_iter_at_mark(self.buffer.get_insert())
        self._go(self.context.backward(before))

    def _show_count(self):
        if not self.settings.get_search_text():
            self.count.set_text("")
            return False
        total = self.context.get_occurrences_count()
        if total < 0:                      # still counting (a big file): it updates when done
            return False
        if total == 0:
            self.count.set_text("No matches")
            return False
        sel = self.buffer.get_selection_bounds()
        at = self.context.get_occurrence_position(*sel) if sel else 0
        self.count.set_text(f"{at} of {total}" if at > 0 else f"{total} found")
        return False

    # ---------------------------------------------------------------- replacing
    def _problem(self, text: str):
        self.problem.set_text(text)
        self.problem.set_visible(True)

    def _put(self, start: Gtk.TextIter, end: Gtk.TextIter, text: str):
        """Replace start..end with ``text`` as typed (no backslash handling)."""
        self.buffer.delete(start, end)
        self.buffer.insert(start, text)

    def replace(self):
        """Replace the selected match (finding one first if none is selected), then go to the next."""
        self._sync()
        sel = self.buffer.get_selection_bounds()
        # is the selection a match? (asked of the search itself: its count may still be being worked out)
        ok, start, end, _w = self.context.forward(sel[0]) if sel else (False, None, None, False)
        if not (ok and start.equal(sel[0]) and end.equal(sel[1])):
            self.next()
            return
        text = self.with_entry.get_text()
        if self.regex.get_active():
            try:
                self.context.replace(start, end, text, -1)
            except GLib.Error as e:
                self._problem(f"Couldn't replace: {e.message}")
                return
        else:
            self.buffer.begin_user_action()
            self._put(start, end, text)
            self.buffer.end_user_action()
        self.next()

    def replace_all(self) -> int:
        self._sync()
        if not self.settings.get_search_text():
            return 0
        text = self.with_entry.get_text()
        if self.regex.get_active():
            try:
                n = self.context.replace_all(text, -1)
            except GLib.Error as e:
                self._problem(f"Couldn't replace: {e.message}")
                return 0
        else:
            # every match first (as marks, which survive the edits), then replace them as one undo step
            marks, it = [], self.buffer.get_start_iter()
            while True:
                ok, start, end, wrapped = self.context.forward(it)
                if not ok or wrapped:
                    break
                marks.append((self.buffer.create_mark(None, start, True), self.buffer.create_mark(None, end, False)))
                it = end
            self.buffer.begin_user_action()
            for a, b in marks:
                self._put(self.buffer.get_iter_at_mark(a), self.buffer.get_iter_at_mark(b), text)
                self.buffer.delete_mark(a)
                self.buffer.delete_mark(b)
            self.buffer.end_user_action()
            n = len(marks)
        root = self.get_root()
        if hasattr(root, "toast"):        # the count changes straight away (to "No matches"), so say it there
            root.toast(f"Replaced {n} match{'es' if n != 1 else ''}" if n else "Nothing to replace")
        return n
