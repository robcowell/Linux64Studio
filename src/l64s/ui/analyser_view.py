"""Source Analyser: instruction counts, addressing modes and estimated cycles for a project, a
file or a selection, with filters, a footprint, charts and metrics, as in CBM prg Studio."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..analyser import MODE_NAMES, AnalyseError, Report, analyse, to_html, to_text  # noqa: E402
from .editor import EditorPage  # noqa: E402

SCOPES = [("project", "The project (its build list)"), ("file", "The current file"),
          ("selection", "The selected lines")]
CHARTS = ["Top 10 Instructions", "Top 10 Cycle Consumers", "Addressing Modes", "Cycle Distribution",
          "Instruction Categories"]


def _clear(box):
    while (c := box.get_first_child()) is not None:
        box.remove(c)


class BarChart(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(vexpand=True, hexpand=True)
        self.items: list[tuple[str, float]] = []
        self.unit = ""
        self.set_draw_func(self._draw)

    def show(self, items, unit=""):
        self.items, self.unit = items, unit
        self.queue_draw()

    def _draw(self, _w, cr, width, height):
        fg = self.get_color()
        if not self.items:
            return
        total = sum(v for _, v in self.items) or 1
        top = max(v for _, v in self.items) or 1
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        label_w = max(cr.text_extents(k).x_advance for k, _ in self.items) + 16
        row = min(28, (height - 10) / len(self.items))
        bar_w = max(10, width - label_w - 150)
        for i, (k, v) in enumerate(self.items):
            y = 6 + i * row
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.85)
            cr.move_to(6, y + row * 0.65)
            cr.show_text(k)
            cr.set_source_rgb(0.30, 0.62, 1.0)
            cr.rectangle(label_w, y + 3, bar_w * v / top, row - 6)
            cr.fill()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.7)
            cr.move_to(label_w + bar_w * v / top + 6, y + row * 0.65)
            cr.show_text(f"{v:g}{self.unit}  ({100 * v / total:.1f}%)")


class SourceAnalyser(EditorPage):
    kind = "analyser"

    def __init__(self, get_request, open_line=None):
        super().__init__(None)
        self.get_request = get_request      # scope -> dict of analyse() arguments and a title, or an error string
        self.open_line = open_line          # (file, line) -> None
        self.report: Report | None = None
        self.title_text = ""
        self._cursor: dict[tuple[str, str], int] = {}

        bar = Gtk.Box(spacing=6, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        bar.append(Gtk.Label(label="Analyse"))
        self.scope = Gtk.DropDown.new_from_strings([s[1] for s in SCOPES])
        bar.append(self.scope)
        go = Gtk.Button(label="Analyse", css_classes=["suggested-action"])
        go.connect("clicked", lambda *_: self.run())
        bar.append(go)
        export = Gtk.MenuButton(label="Export", tooltip_text="Save the results as a text or HTML file")
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4, margin_top=4,
                       margin_bottom=4)
        for label, kind in (("As text…", "txt"), ("As HTML…", "html")):
            b = Gtk.Button(label=label, css_classes=["flat"])
            b.connect("clicked", lambda _b, k=kind, p=pop: (p.popdown(), self._export(k)))
            pbox.append(b)
        pop.set_child(pbox)
        export.set_popover(pop)
        bar.append(export)
        self.stack = Adw.ViewStack(vexpand=True)
        bar.append(Gtk.Box(hexpand=True))
        bar.append(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.append(bar)
        self.stack.add_titled_with_icon(self._stats_page(), "stats", "Statistics", "view-list-symbolic")
        self.stack.add_titled_with_icon(self._footprint_page(), "footprint", "Footprint", "view-grid-symbolic")
        self.stack.add_titled_with_icon(self._charts_page(), "charts", "Charts", "x-office-presentation-symbolic")
        self.stack.add_titled_with_icon(self._metrics_page(), "metrics", "Metrics", "document-properties-symbolic")
        self.append(self.stack)
        self.status = Gtk.Label(xalign=0, margin_start=10, margin_bottom=6, wrap=True, css_classes=["dim-label"],
                                label="Choose what to analyse and press Analyse")
        self.append(self.status)

    @property
    def title(self) -> str:
        return "Source Analyser"

    def save(self) -> None:
        pass

    # ================================================================== pages
    def _stats_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_end=8, margin_bottom=6)
        f = Gtk.Box(spacing=6)
        self.mode_filter = Gtk.DropDown.new_from_strings(["All modes"] + [MODE_NAMES[m] for m in MODE_NAMES])
        self.file_names = Gtk.StringList.new(["All files"])
        self.file_filter = Gtk.DropDown(model=self.file_names)
        self.text_filter = Gtk.SearchEntry(placeholder_text="Text", width_chars=10)
        self.min_cycles = Gtk.SpinButton.new_with_range(0, 8, 1)
        self.max_cycles = Gtk.SpinButton.new_with_range(0, 8, 1)
        self.max_cycles.set_value(8)
        self.show_invalid = Gtk.CheckButton(label="Show invalid")
        for w in (self.mode_filter, self.file_filter):
            w.connect("notify::selected", lambda *_: self._fill_stats())
        self.text_filter.connect("search-changed", lambda *_: self._fill_stats())
        for w in (self.min_cycles, self.max_cycles):
            w.connect("value-changed", lambda *_: self._fill_stats())
        self.show_invalid.connect("toggled", lambda *_: self._fill_stats())
        for w in (Gtk.Label(label="Mode"), self.mode_filter, Gtk.Label(label="File"), self.file_filter,
                  self.text_filter, Gtk.Label(label="Cycles"), self.min_cycles, Gtk.Label(label="to"),
                  self.max_cycles, self.show_invalid):
            f.append(w)
        clear = Gtk.Button(label="Clear Filters")
        clear.connect("clicked", lambda *_: self._clear_filters())
        f.append(clear)
        for label, state in (("Expand All", True), ("Collapse All", False)):
            b = Gtk.Button(label=label, css_classes=["flat"])
            b.connect("clicked", lambda _b, s=state: self._expand_all(s))
            f.append(b)
        box.append(Gtk.ScrolledWindow(child=f, vscrollbar_policy=Gtk.PolicyType.NEVER))
        self.summary = Gtk.Label(xalign=0, css_classes=["dim-label"])
        box.append(self.summary)
        self.stats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.append(Gtk.ScrolledWindow(child=self.stats, vexpand=True))
        return box

    def _footprint_page(self):
        self.footprint = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                                     min_children_per_line=1, column_spacing=16, row_spacing=12, margin_start=8,
                                     margin_end=8, valign=Gtk.Align.START, homogeneous=True)
        return Gtk.ScrolledWindow(child=self.footprint, vexpand=True)

    def _charts_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_end=8, margin_bottom=6)
        self.chart_type = Gtk.DropDown.new_from_strings(CHARTS)
        self.chart_type.set_halign(Gtk.Align.START)
        self.chart_type.connect("notify::selected", lambda *_: self._fill_chart())
        box.append(self.chart_type)
        self.chart = BarChart()
        box.append(self.chart)
        return box

    def _metrics_page(self):
        self.metrics = Gtk.Grid(column_spacing=24, row_spacing=6, margin_start=12, margin_top=8)
        return Gtk.ScrolledWindow(child=self.metrics, vexpand=True)

    # ================================================================== running
    def set_scope(self, scope: str):
        self.scope.set_selected([s[0] for s in SCOPES].index(scope))

    def run(self, scope: str | None = None):
        if scope:
            self.set_scope(scope)
        which = SCOPES[self.scope.get_selected()][0]
        req = self.get_request(which)
        if isinstance(req, str):
            self.status.set_text(req)
            return
        title = req.pop("title")
        try:
            self.report = analyse(**req)
        except (AnalyseError, OSError) as e:
            self.status.set_text(str(e))
            return
        self.title_text = title
        self._cursor.clear()
        r = self.report
        files = sorted({i.file for i in r.instrs} | {i.file for i in r.invalid})
        self.file_names.splice(0, self.file_names.get_n_items(), ["All files"] + [Path(f).name for f in files])
        self._files = files
        self._fill_stats()
        self._fill_footprint()
        self._fill_chart()
        self._fill_metrics()
        m = dict(r.metrics())
        self.status.set_text(f"{title}: {m['Files analysed']} file(s), {m['Instructions']} instruction(s), "
                             f"{len(r.invalid)} invalid instruction(s), from the {r.method} code")

    def _clear_filters(self):
        self.mode_filter.set_selected(0)
        self.file_filter.set_selected(0)
        self.text_filter.set_text("")
        self.min_cycles.set_value(0)
        self.max_cycles.set_value(8)

    def _filtered(self):
        r = self.report
        if not r:
            return []
        mode_i = self.mode_filter.get_selected()
        mode = list(MODE_NAMES)[mode_i - 1] if mode_i else None
        file_i = self.file_filter.get_selected()
        file = self._files[file_i - 1] if file_i and file_i - 1 < len(self._files) else None
        text = self.text_filter.get_text().strip().lower()
        lo, hi = self.min_cycles.get_value_as_int(), self.max_cycles.get_value_as_int()
        out = []
        for i in r.instrs:
            if mode and i.mode != mode or file and i.file != file:
                continue
            if text and text not in i.mnemonic and text not in MODE_NAMES[i.mode] and text not in i.source.lower():
                continue
            if not lo <= i.cycles[0] <= hi:
                continue
            out.append(i)
        return out

    def _fill_stats(self):
        _clear(self.stats)
        self._expanders = []
        if not self.report:
            return
        instrs = self._filtered()
        groups: dict[str, list] = {}
        for i in instrs:
            groups.setdefault(i.mnemonic, []).append(i)
        base = sum(i.cycles[0] for i in instrs)
        self.summary.set_text(f"{len(instrs)} instructions shown, {base} base cycles")
        for mn, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            cyc = sum(i.cycles[0] for i in items)
            exp = Gtk.Expander(label=f"{mn.upper()}    {len(items)}    {cyc} cycles", css_classes=["monospace"])
            inner = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"], margin_start=24,
                                margin_top=4, margin_bottom=4)
            modes = Counter(i.mode for i in items)
            for mode, count in modes.most_common():
                b, x = items[[i.mode for i in items].index(mode)].cycles
                op = items[[i.mode for i in items].index(mode)].opcode
                row = Adw.ActionRow(title=MODE_NAMES[mode],
                                    subtitle=f"opcode ${op:02X}  ·  {b}" + (f"-{x}" if x != b else "")
                                             + f" cycles  ·  {count} × = {count * b} cycles",
                                    activatable=True, tooltip_text="Click to go to each one in the source")
                row.connect("activated", lambda _r, m=mn, md=mode, its=items: self._goto(m, md, its))
                row.add_suffix(Gtk.Label(label=str(count)))
                inner.append(row)
            exp.set_child(inner)
            self.stats.append(exp)
            self._expanders.append(exp)
        if self.show_invalid.get_active():
            bad = self.report.invalid
            exp = Gtk.Expander(label=f"Invalid    {len(bad)}", expanded=True)
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"], margin_start=24)
            for b in bad:
                row = Adw.ActionRow(title=GLib.markup_escape_text(b.source),
                                    subtitle=f"{Path(b.file).name}:{b.line}  ·  {b.reason}", activatable=True)
                row.connect("activated", lambda _r, b=b: self.open_line and self.open_line(b.file, b.line))
                lb.append(row)
            if not bad:
                lb.append(Gtk.Label(label="None", margin_top=4, margin_bottom=4))
            exp.set_child(lb)
            self.stats.append(exp)

    def _expand_all(self, state: bool):
        for e in getattr(self, "_expanders", []):
            e.set_expanded(state)

    def _goto(self, mnemonic, mode, items):
        where = [i for i in items if i.mode == mode]
        key = (mnemonic, mode)
        n = self._cursor.get(key, 0) % len(where)
        self._cursor[key] = n + 1
        i = where[n]
        self.status.set_text(f"{mnemonic.upper()} {MODE_NAMES[mode]}: {n + 1} of {len(where)}, "
                             f"{Path(i.file).name} line {i.line}")
        if self.open_line:
            self.open_line(i.file, i.line)

    def _table(self, title, head, rows):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Label(label=f"<b>{title}</b>", use_markup=True, xalign=0))
        g = Gtk.Grid(column_spacing=16, row_spacing=3, css_classes=["card"])
        for c, h in enumerate(head):
            g.attach(Gtk.Label(label=h, xalign=0, css_classes=["dim-label"], margin_start=8 if c == 0 else 0,
                               margin_top=6), c, 0, 1, 1)
        for r, row in enumerate(rows, start=1):
            for c, v in enumerate(row):
                g.attach(Gtk.Label(label=str(v), xalign=0 if c == 0 else 1, margin_start=8 if c == 0 else 0,
                                   margin_end=8 if c == len(row) - 1 else 0,
                                   margin_bottom=6 if r == len(rows) else 0), c, r, 1, 1)
        box.append(g)
        return box

    def _fill_footprint(self):
        _clear(self.footprint)
        r = self.report
        total = sum(i.cycles[0] for i in r.instrs) or 1
        cyc = r.cycles_by_mnemonic().most_common(10)
        self.footprint.append(self._table("Top cycle usage", ["Instruction", "Total cycles", "Share"],
                                          [(m.upper(), c, f"{100 * c / total:.1f}%") for m, c in cyc]))
        n = len(r.instrs) or 1
        top = r.by_mnemonic().most_common(10)
        self.footprint.append(self._table("Top 10 instruction counts", ["Instruction", "Count", "Share"],
                                          [(m.upper(), c, f"{100 * c / n:.1f}%") for m, c in top]))
        files = sorted(r.by_file().items(), key=lambda kv: -kv[1][1])
        self.footprint.append(self._table("By file", ["File", "Instructions", "Cycles"],
                                          [(Path(f).name, a, f"{b}-{c}" if c != b else b) for f, (a, b, c) in files]))

    def _fill_chart(self):
        r = self.report
        if not r:
            return
        kind = CHARTS[self.chart_type.get_selected()]
        if kind == "Top 10 Instructions":
            self.chart.show([(m.upper(), c) for m, c in r.by_mnemonic().most_common(10)])
        elif kind == "Top 10 Cycle Consumers":
            self.chart.show([(m.upper(), c) for m, c in r.cycles_by_mnemonic().most_common(10)], " cycles")
        elif kind == "Addressing Modes":
            self.chart.show([(MODE_NAMES[m], c) for m, c in r.by_mode().most_common()])
        elif kind == "Cycle Distribution":
            self.chart.show([(f"{k} cycles", c) for k, c in sorted(r.cycle_distribution().items())])
        else:
            self.chart.show(r.by_category().most_common())

    def _fill_metrics(self):
        _clear(self.metrics)
        for row, (k, v) in enumerate(self.report.metrics()):
            self.metrics.attach(Gtk.Label(label=k, xalign=0, css_classes=["dim-label"]), 0, row, 1, 1)
            self.metrics.attach(Gtk.Label(label=v, xalign=0, selectable=True), 1, row, 1, 1)

    # ================================================================== export
    def _export(self, kind: str):
        if not self.report:
            self.status.set_text("Analyse something first")
            return
        dlg = Gtk.FileDialog(title="Export the analysis")
        dlg.set_initial_name(f"analysis.{'html' if kind == 'html' else 'txt'}")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            self.export(dest, kind)
        dlg.save(self.get_root(), None, done)

    def export(self, dest: Path, kind: str):
        title = f"Source analysis: {self.title_text}"
        try:
            dest.write_text(to_html(self.report, title) if kind == "html" else to_text(self.report, title))
        except OSError as e:
            self.status.set_text(f"Couldn't write {dest.name}: {e}")
            return
        self.status.set_text(f"Exported to {dest}")
