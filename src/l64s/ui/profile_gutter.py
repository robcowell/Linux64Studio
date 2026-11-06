"""The profiler's figures in the editor: a column beside the line numbers with each line's share of
the program's time (from the last profile, l64s.profiler), and the busiest lines tinted.

The figures are tied to the lines with text marks, so they stay with their lines while you edit
(until the next profile replaces them)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource  # noqa: E402
except (ValueError, ImportError):
    GtkSource = None

# (least share, tint) for the busiest lines, hottest first
HEAT = [(0.10, "rgba(230,97,0,0.34)"), (0.03, "rgba(230,97,0,0.22)"), (0.01, "rgba(230,97,0,0.13)"),
        (0.003, "rgba(230,97,0,0.06)")]
SHOWN = 0.0005            # lines under 0.05% get no figure


def heat_level(share: float) -> int | None:
    """Which tint a line with this share gets (0 the hottest), or None."""
    return next((i for i, (least, _c) in enumerate(HEAT) if share >= least), None)


def figure(share: float) -> str:
    if share < SHOWN:
        return ""
    if share >= 0.10:
        return f"{share * 100:.0f}%"
    return f"{share * 100:.1f}%"


class ProfileFigures:
    """An editor's profile column and tints. set() shows a file's figures, clear() removes them."""

    def __init__(self, view, buffer):
        self.view, self.buffer = view, buffer
        self.tags = [buffer.create_tag(f"profile-heat-{i}", paragraph_background=c) for i, (_l, c) in enumerate(HEAT)]
        for t in self.tags:
            t.set_priority(0)                  # under the PC and breakpoint highlights
        self.marks: list[tuple[Gtk.TextMark, float, int]] = []
        self.column = None
        if GtkSource is not None and hasattr(view, "get_gutter"):
            self.column = ProfileColumn(self)
            self.column.set_visible(False)
            view.get_gutter(Gtk.TextWindowType.LEFT).insert(self.column, -40)

    def clear(self):
        b = self.buffer
        for t in self.tags:
            b.remove_tag(t, b.get_start_iter(), b.get_end_iter())
        for m, _s, _n in self.marks:
            b.delete_mark(m)
        self.marks = []
        if self.column is not None:
            self.column.set_visible(False)

    def set(self, lines: dict[int, tuple[float, int]] | None):
        """{line (from 1): (share, samples)}; None or empty: no figures."""
        self.clear()
        if not lines:
            return
        b = self.buffer
        for line, (share, samples) in lines.items():
            ok, it = b.get_iter_at_line(line - 1)
            if not ok:
                continue
            self.marks.append((b.create_mark(None, it, True), share, samples))
            level = heat_level(share)
            if level is not None:
                end = it.copy()
                end.forward_line()
                b.apply_tag(self.tags[level], it, end)
        if self.column is not None:
            self.column.set_visible(True)
            self.column.queue_draw()

    def by_line(self) -> dict[int, tuple[float, int]]:
        """{line (from 0): (share, samples)}, where the marks are now."""
        b = self.buffer
        return {b.get_iter_at_mark(m).get_line(): (s, n) for m, s, n in self.marks}


if GtkSource is not None:
    class ProfileColumn(GtkSource.GutterRendererText):
        def __init__(self, figures: ProfileFigures):
            super().__init__(xalign=1.0, xpad=4, has_tooltip=True)
            self.figures = figures
            self._lines: dict[int, tuple[float, int]] = {}
            self._sized = False
            self.connect("query-tooltip", self._tooltip)

        def do_begin(self, lines):
            GtkSource.GutterRendererText.do_begin(self, lines)    # (it makes the text layout)
            if not self._sized:
                self._sized = True
                w, _h = self.measure("88.8%")
                self.set_size_request(w + 2 * self.get_xpad(), -1)
            self._lines = self.figures.by_line()

        def do_query_data(self, lines, line):
            share = self._lines.get(line, (0.0, 0))[0]
            text = figure(share)
            if text and share >= HEAT[0][0]:
                self.set_markup(f"<b>{text}</b>", -1)
            else:
                self.set_text(text, -1)

        def _tooltip(self, _w, x, y, _kb, tip):
            view = self.figures.view
            _bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.LEFT, x, y)
            it, _top = view.get_line_at_y(by)
            share, samples = self.figures.by_line().get(it.get_line(), (0.0, 0))
            if not samples:
                return False
            tip.set_text(f"{share * 100:.2f}% of the program's time in the last profile ({samples:,} samples)")
            return True
