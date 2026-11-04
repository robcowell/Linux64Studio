"""Statistics: the variables a BASIC program sets (and where), the ones that are really the same
variable, and common mistakes, as CBM prg Studio's Statistics tool shows them."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..basic.stats import BASIC_BYTES, BasicErrors, analyse, report  # noqa: E402
from .editor import EditorPage  # noqa: E402


def _esc(t: str) -> str:
    return GLib.markup_escape_text(t)


class BasicStatistics(EditorPage):
    kind = "basicstats"

    def __init__(self, get_target, open_line=None):
        super().__init__(None)
        self.get_target = get_target        # () -> the BASIC SourceEditor to analyse, or None
        self.open_line = open_line          # (file, source line) -> None
        self.stats = None
        self.target = None

        bar = Gtk.Box(spacing=6, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        self.heading = Gtk.Label(xalign=0, hexpand=True, use_markup=True)
        bar.append(self.heading)
        for label, cb in (("Refresh", self.refresh), ("Copy Report", self._copy), ("Export…", self._export)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_, cb=cb: cb())
            bar.append(b)
        self.append(bar)
        self.summary = Gtk.Label(xalign=0, margin_start=10, css_classes=["dim-label"], selectable=True, wrap=True)
        self.append(self.summary)
        self.page = Adw.PreferencesPage(vexpand=True)
        self.append(self.page)
        self.groups: list[Adw.PreferencesGroup] = []
        self.status = Gtk.Label(xalign=0, margin_start=10, margin_bottom=6, wrap=True, css_classes=["dim-label"])
        self.append(self.status)
        self.refresh()

    @property
    def title(self) -> str:
        return "Statistics"

    def save(self) -> None:
        pass

    def _group(self, title: str, description: str = "") -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(title=title, description=description)
        self.page.add(g)
        self.groups.append(g)
        return g

    def _row(self, group, title, subtitle, basic_line=None, suffix=None):
        row = Adw.ActionRow(title=_esc(title), subtitle=_esc(subtitle), activatable=basic_line is not None)
        if suffix:
            row.add_suffix(Gtk.Label(label=suffix, css_classes=["dim-label"]))
        if basic_line is not None:
            row.connect("activated", lambda *_: self._goto(basic_line))
            row.set_tooltip_text(f"Go to line {basic_line}")
        group.add(row)

    def refresh(self):
        for g in self.groups:
            self.page.remove(g)
        self.groups.clear()
        t = self.get_target() if self.get_target else None
        if t is None or not t.is_basic:
            self.target = None
            self.stats = None
            self.heading.set_markup("<b>No BASIC program</b>")
            self.summary.set_text("")
            self.status.set_text("Open (or click into) a .bas file, then press Refresh")
            return
        self.target = t
        self.heading.set_markup(f"<b>{_esc(t.title)}</b>")
        b = t.buffer
        try:
            st = analyse(b.get_text(b.get_start_iter(), b.get_end_iter(), False))
        except BasicErrors as e:
            self.stats = None
            self.summary.set_text("")
            self.status.set_text(f"{t.title} doesn't tokenise: {e}")
            return
        self.stats = st
        self.summary.set_text(f"{st.lines} lines   ${st.start:04X}-${st.end:04X} ({st.start}-{st.end})   "
                              f"{st.size} bytes   {st.free} of {BASIC_BYTES} bytes free")
        problems = st.problems + st.keyword_words
        if problems:
            g = self._group("Problems")
            for p in sorted(problems, key=lambda p: p.line):
                self._row(g, p.message, f"line {p.line}", p.line)
        g = self._group("Variables", "Each variable the program sets, and the line it's first set on. Only the "
                                     "first two characters of a name count.")
        assigned = st.assigned()
        for v in assigned:
            other = f"  (also written {', '.join(v.spellings[1:])})" if len(v.spellings) > 1 else ""
            self._row(g, v.name + ("()" if v.key.endswith("(") else "") + other,
                      f"{v.kind} · first set on line {v.first_set} ({v.how}) · used on {len(v.lines_used)} "
                      f"line{'s' if len(v.lines_used) != 1 else ''}", v.first_set, v.key)
        if not assigned:
            g.add(Adw.ActionRow(title="None"))
        dups = st.duplicates()
        if dups:
            g = self._group("Duplicate Variables", "Different names that the C64 sees as one variable")
            for v in dups:
                self._row(g, " = ".join(v.spellings), f"all {v.key}, first set on line {v.first_set}", v.first_set)
        never = st.never_set()
        if never:
            g = self._group("Used but never set", "They're 0 (or empty, for strings): a typing mistake?")
            for v in never:
                self._row(g, v.name, f"{v.kind} · first used on line {v.lines_used[0]}", v.lines_used[0])
        n = len(problems)
        self.status.set_text(f"{len(assigned)} variables, {len(dups)} duplicate{'s' if len(dups) != 1 else ''}, "
                             f"{n} problem{'s' if n != 1 else ''}")

    def _goto(self, basic_line: int):
        if not self.stats or not self.target or not self.open_line or not self.target.path:
            return
        src = self.stats.source_line.get(basic_line)
        if src:
            self.open_line(str(self.target.path), src)

    def _report(self) -> str:
        return report(self.stats, self.target.title) if self.stats else ""

    def _copy(self):
        if self.stats:
            Gdk.Display.get_default().get_clipboard().set(self._report())
            self.status.set_text("Copied the report")

    def _export(self):
        if not self.stats:
            return
        dlg = Gtk.FileDialog(title="Save the statistics")
        dlg.set_initial_name(Path(self.target.title).stem + "-statistics.txt")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            dest.write_text(self._report())
            self.status.set_text(f"Saved {dest}")
        dlg.save(self.get_root(), None, done)
