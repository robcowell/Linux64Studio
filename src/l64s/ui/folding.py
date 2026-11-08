"""Folding #region ... #endregion blocks in the source editor (CBM prg Studio's text folding).

A region's #region line gets a ▾ in the gutter; clicking it hides the lines up to and including
#endregion (▸ then shows it's folded, and the line is shaded). Ctrl+P folds every region,
Ctrl+Shift+P unfolds them, and going to a hidden line (an error, the debugger's PC, Go to
Definition) unfolds what hides it. Folding only hides text: the file and the build are unchanged.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..regions import Region, find_regions  # noqa: E402

try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource  # noqa: E402
except (ValueError, ImportError):
    GtkSource = None


class Folding:
    def __init__(self, view, buffer):
        self.view = view
        self.buffer = buffer
        self.regions: list[Region] = []
        self.folded: list = []              # TextMarks at the start of folded #region lines
        self.hidden = buffer.create_tag("folded", invisible=True)
        self.head = buffer.create_tag("fold-head", paragraph_background="rgba(128,128,128,0.16)")
        self._pending = False
        if GtkSource is not None and hasattr(view, "set_mark_attributes"):
            for cat, icon in (("fold-open", "pan-down-symbolic"), ("fold-closed", "pan-end-symbolic")):
                a = GtkSource.MarkAttributes()
                a.set_icon_name(icon)
                view.set_mark_attributes(cat, a, 3)
        if GtkSource is not None and hasattr(view, "set_show_line_numbers") and view.get_show_line_numbers():
            view.set_show_line_numbers(False)          # our own numbers, which skip folded lines
            self.numbers = FoldAwareLineNumbers(self.hidden)
            view.get_gutter(Gtk.TextWindowType.LEFT).insert(self.numbers, -30)
        buffer.connect("changed", lambda *_: self.schedule())
        self.schedule()

    # ---------------------------------------------------------------- state
    def schedule(self):
        if not self._pending:
            self._pending = True
            GLib.timeout_add(150, self.refresh)

    def _lines(self) -> list[str]:
        b = self.buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), True).split("\n")

    def _line_of(self, mark) -> int:
        return self.buffer.get_iter_at_mark(mark).get_line()

    def region_at(self, line: int) -> Region | None:
        """The region whose #region is on this (0-based) line."""
        return next((r for r in self.regions if r.start == line), None)

    def is_folded(self, line: int) -> bool:
        return any(self._line_of(m) == line for m in self.folded)

    def refresh(self):
        """Find the regions again and redraw the markers and folds (after an edit)."""
        self._pending = False
        b = self.buffer
        self.regions = find_regions(self._lines())
        starts = {r.start for r in self.regions}
        for m in list(self.folded):                 # forget folds whose #region line has gone
            if self._line_of(m) not in starts:
                self.folded.remove(m)
                b.delete_mark(m)
        begin, end = b.get_start_iter(), b.get_end_iter()
        b.remove_tag(self.hidden, begin, end)
        b.remove_tag(self.head, begin, end)
        if hasattr(b, "remove_source_marks"):
            b.remove_source_marks(begin, end, "fold-open")
            b.remove_source_marks(begin, end, "fold-closed")
        folded_lines = {self._line_of(m) for m in self.folded}
        hidden_lines: set[int] = set()
        for r in self.regions:
            if r.start in folded_lines:
                hidden_lines.update(range(r.start + 1, r.end + 1))
        for r in self.regions:
            if r.start in hidden_lines:
                continue                            # inside a folded region: no marker of its own
            ok, it = b.get_iter_at_line(r.start)
            if not ok:
                continue
            closed = r.start in folded_lines
            if hasattr(b, "create_source_mark"):
                b.create_source_mark(None, "fold-closed" if closed else "fold-open", it)
            if closed:
                # whole lines, newlines and all, from the one after #region to #endregion
                first = it.copy()
                first.forward_line()
                ok2, after = b.get_iter_at_line(r.end + 1)
                if not ok2 or r.end + 1 >= b.get_line_count():
                    after = b.get_end_iter()
                b.apply_tag(self.hidden, first, after)
                b.apply_tag(self.head, it, first)
        return False

    # ---------------------------------------------------------------- folding
    def fold(self, line: int):
        if self.region_at(line) is None or self.is_folded(line):
            return
        ok, it = self.buffer.get_iter_at_line(line)
        self.folded.append(self.buffer.create_mark(None, it, True))
        r = self.region_at(line)
        cur = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        if r.start < cur <= r.end:                  # don't leave the cursor in hidden text
            end = it.copy()
            if not end.ends_line():
                end.forward_to_line_end()
            self.buffer.place_cursor(end)
        self.refresh()

    def unfold(self, line: int):
        for m in [m for m in self.folded if self._line_of(m) == line]:
            self.folded.remove(m)
            self.buffer.delete_mark(m)
        self.refresh()

    def toggle(self, line: int) -> bool:
        """Fold or unfold the region starting on this line; False if none does."""
        if self.region_at(line) is None:
            return False
        (self.unfold if self.is_folded(line) else self.fold)(line)
        return True

    def fold_all(self):
        self.refresh()
        for r in self.regions:
            if not self.is_folded(r.start):
                ok, it = self.buffer.get_iter_at_line(r.start)
                self.folded.append(self.buffer.create_mark(None, it, True))
        cur = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        outer = [r for r in self.regions if r.start < cur <= r.end]
        if outer:
            ok, it = self.buffer.get_iter_at_line(min(r.start for r in outer))
            if not it.ends_line():
                it.forward_to_line_end()
            self.buffer.place_cursor(it)
        self.refresh()

    def unfold_all(self):
        for m in self.folded:
            self.buffer.delete_mark(m)
        self.folded.clear()
        self.refresh()

    def reveal(self, line: int):
        """Unfold whatever hides this (0-based) line."""
        self.refresh()
        changed = False
        for r in self.regions:
            if r.start < line <= r.end and self.is_folded(r.start):
                for m in [m for m in self.folded if self._line_of(m) == r.start]:
                    self.folded.remove(m)
                    self.buffer.delete_mark(m)
                changed = True
        if changed:
            self.refresh()


if GtkSource is not None:
    class FoldAwareLineNumbers(GtkSource.GutterRendererText):
        """Line numbers that leave folded (hidden) lines out. GtkSourceView's own draws a hidden
        line's number on top of the next line's."""

        def __init__(self, hidden_tag):
            super().__init__(xalign=1.0, xpad=4)
            self.hidden_tag = hidden_tag
            self._digits = 0

        def text_zoom_changed(self):
            self._digits = 0                   # measure the numbers again

        def do_begin(self, lines):
            GtkSource.GutterRendererText.do_begin(self, lines)   # it makes the text layout
            digits = max(2, len(str(lines.get_buffer().get_line_count())))
            if digits != self._digits:
                self._digits = digits
                w, _h = self.measure("9" * digits)
                self.set_size_request(w + 2 * self.get_xpad(), -1)

        def do_query_data(self, lines, line):
            it = lines.get_iter_at_line(line)
            if it.has_tag(self.hidden_tag):
                self.set_text("", -1)
            elif lines.is_cursor(line):
                self.set_markup(f"<b>{line + 1}</b>", -1)
            else:
                self.set_text(str(line + 1), -1)
