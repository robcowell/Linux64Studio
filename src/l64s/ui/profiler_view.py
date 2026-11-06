"""The Profiler tab: runs the program in VICE and shows where its time goes, by routine, source
line and file, and where in the frame (by raster line) each routine runs. l64s.profiler samples."""
from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from ..profiler import Profile, ProfileRun, Resolver, Row  # noqa: E402
from .editor import EditorPage  # noqa: E402

ROWS = 80                 # rows shown in each list
# The frame chart's colours for the busiest routines (readable on light and dark backgrounds)
COLOURS = [(0.26, 0.55, 0.96), (0.95, 0.47, 0.18), (0.20, 0.70, 0.40), (0.86, 0.26, 0.42),
           (0.60, 0.40, 0.85), (0.93, 0.75, 0.15), (0.15, 0.70, 0.75), (0.75, 0.50, 0.35)]
OTHER = (0.55, 0.55, 0.55)
VISIBLE = (51, 251)       # the raster lines of the screen's 25 text rows (the rest is border)


def _clear(box):
    while (c := box.get_first_child()) is not None:
        box.remove(c)


class ShareBar(Gtk.DrawingArea):
    """A row's share, as a bar the length of its share of the top row's."""

    def __init__(self, fraction: float, colour=COLOURS[0]):
        super().__init__(content_width=90, content_height=12, valign=Gtk.Align.CENTER)
        self.fraction, self.colour = max(0.0, min(1.0, fraction)), colour
        self.set_draw_func(self._draw)

    def _draw(self, _w, cr, width, height):
        cr.set_source_rgba(*self.colour, 0.18)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.set_source_rgb(*self.colour)
        cr.rectangle(0, 0, max(1.0, width * self.fraction), height)
        cr.fill()


class FrameChart(Gtk.DrawingArea):
    """The frame, top (raster line 0) to bottom: each line a bar split between the routines that
    run on it, as the border-colour trick shows it, but measured."""

    def __init__(self):
        super().__init__(vexpand=True, hexpand=True, has_tooltip=True)
        self.lines: list = []
        self.colours: dict = {}
        self.set_draw_func(self._draw)
        self.connect("query-tooltip", self._tooltip)

    def show(self, lines, colours):
        self.lines, self.colours = lines, colours
        self.queue_draw()

    def _geometry(self, width, height):
        left = 44
        n = len(self.lines) or 312
        return left, 6, max(10, width - left - 8), max(10, height - 12), n

    def _draw(self, _w, cr, width, height):
        fg = self.get_color()
        left, top, w, h, n = self._geometry(width, height)
        per = h / n
        # the screen's rows
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.06)
        cr.rectangle(left, top + VISIBLE[0] * per, w, (VISIBLE[1] - VISIBLE[0]) * per)
        cr.fill()
        rank = {k: i for i, k in enumerate(self.colours)}
        for i, parts in enumerate(self.lines):
            x = left
            # in the same order on every line (the busiest routine overall first), so they line up
            for r, share in sorted(parts, key=lambda p: rank.get((p[0].name, p[0].address), len(rank))):
                cr.set_source_rgb(*self.colours.get((r.name, r.address), OTHER))
                cr.rectangle(x, top + i * per, w * share, per + 0.6)
                cr.fill()
                x += w * share
        cr.select_font_face("Sans")
        cr.set_font_size(10)
        for ln in range(0, n, 50):
            y = top + ln * per
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
            cr.move_to(4, y + 4)
            cr.show_text(str(ln))
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.25)
            cr.rectangle(left - 6, y, 4, 1)
            cr.fill()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.45)
        for ln in VISIBLE:
            cr.rectangle(left - 3, top + ln * per, 2, 1)
        cr.fill()

    def _tooltip(self, _w, x, y, _kb, tip):
        if not self.lines:
            return False
        _left, top, _wd, h, n = self._geometry(self.get_width(), self.get_height())
        ln = int((y - top) / (h / n))
        if not 0 <= ln < n:
            return False
        parts = self.lines[ln]
        where = "the screen" if VISIBLE[0] <= ln < VISIBLE[1] else "the border"
        text = [f"Raster line {ln} (${ln:03X}, {where})"]
        text += [f"{share * 100:5.1f}%  {GLib.markup_escape_text(r.name)}" for r, share in parts[:6]]
        if not parts:
            text.append("No samples yet")
        tip.set_markup("<tt>" + "\n".join(text) + "</tt>")
        return True


class ProfilerView(EditorPage):
    kind = "profiler"

    def __init__(self, start: Callable[[], None], open_line: Callable[[str, int], None],
                 line_text: Callable[[str, int], str], show_figures: Callable[[dict | None], None] | None = None):
        super().__init__(None)
        self._start, self.open_line, self.line_text = start, open_line, line_text
        self.show_figures = show_figures or (lambda _shares: None)
        self.run: ProfileRun | None = None
        self.profile: Profile | None = None
        self.resolver: Resolver | None = None
        self.emulated = 0                    # cycles of the program's time in the profile
        self.clock = 985248
        self.state = "idle"                  # idle, starting, running, stopped
        self.message = ""
        self._dirty = False
        self._closed = False

        bar = Gtk.Box(spacing=6, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        self.go = Gtk.Button(label="Profile in VICE", css_classes=["suggested-action"],
                             tooltip_text="Build the program and run it in VICE, measuring where its time goes")
        self.go.connect("clicked", lambda *_: self._start())
        self.stop_button = Gtk.Button(label="Stop", sensitive=False,
                                      tooltip_text="Stop measuring (the program carries on in VICE)")
        self.stop_button.connect("clicked", lambda *_: self.stop())
        self.reset = Gtk.Button(label="Reset", sensitive=False,
                                tooltip_text="Start the counts again from now (to measure one part of the program)")
        self.reset.connect("clicked", lambda *_: self.clear())
        self.copy = Gtk.Button(icon_name="edit-copy-symbolic", sensitive=False,
                               tooltip_text="Copy the profile as text")
        self.copy.connect("clicked", lambda *_: self._copy())
        self.in_editor = Gtk.CheckButton(label="In the editor", active=True,
                                         tooltip_text="Show each line's share of the time beside it in the editor, "
                                                      "and tint the busiest lines")
        self.in_editor.connect("toggled", lambda *_: self._push_figures())
        self.status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                css_classes=["dim-label"])
        for w in (self.go, self.stop_button, self.reset, self.copy, self.in_editor, self.status):
            bar.append(w)
        self.append(bar)

        self.views = Adw.ViewStack(vexpand=True)
        self.lists: dict[str, Gtk.ListBox] = {}
        for name, title, icon in (("routines", "Routines", "view-list-symbolic"),
                                  ("lines", "Lines", "format-justify-left-symbolic"),
                                  ("files", "Files", "folder-documents-symbolic")):
            lb = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE,
                             margin_start=8, margin_end=8, margin_bottom=8)
            lb.connect("row-activated", self._activated)
            self.lists[name] = lb
            self.views.add_titled_with_icon(Gtk.ScrolledWindow(child=lb, vexpand=True), name, title, icon)
        frame = Gtk.Box(spacing=12, margin_start=8, margin_end=8, margin_bottom=8)
        self.chart = FrameChart()
        frame.append(self.chart)
        self.legend = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=220)
        frame.append(Gtk.ScrolledWindow(child=self.legend, hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=False))
        self.views.add_titled_with_icon(frame, "frame", "Frame", "video-display-symbolic")
        self.views.connect("notify::visible-child-name", lambda *_: self.profile and self._refresh(figures=False))
        switcher = Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE,
                                    halign=Gtk.Align.CENTER, margin_bottom=6)
        self.append(switcher)
        self.empty = Adw.StatusPage(icon_name="utilities-system-monitor-symbolic", title="Profiler",
                                    description="Profile in VICE builds the program and runs it in VICE, at its "
                                                "real speed, measuring where the 6510's time goes: which routines "
                                                "and lines, and where in the frame. Play the game while it "
                                                "measures; Reset starts the counts again from now.")
        self.body = Gtk.Stack(vexpand=True)
        self.body.add_named(self.empty, "empty")
        self.body.add_named(self.views, "views")
        self.append(self.body)
        self._update_buttons()
        GLib.timeout_add(1000, self._tick)

    @property
    def title(self) -> str:
        return "Profiler"

    def save(self):
        pass

    # ------------------------------------------------------------------ running
    def begin(self, target, resolver: Resolver, emulator: str = "", extra_args: list[str] | None = None):
        """Run the program in VICE and profile it (a profile already running stops first)."""
        if self.run:
            self.run.stop()
        self.resolver = resolver
        self.profile = None
        self.emulated = 0
        self.state, self.message = "starting", ""
        idle = GLib.idle_add
        run = ProfileRun(target, resolver,
                         on_start=lambda mem, timing: idle(self._started, run, mem, timing),
                         on_batch=lambda samples, cyc: idle(self._batch, run, samples, cyc),
                         on_end=lambda msg: idle(self._ended, run, msg),
                         emulator=emulator, extra_args=extra_args)
        self.run = run
        try:
            run.start()
        except FileNotFoundError as e:
            self.run = None
            self.state, self.message = "idle", str(e)
        self._refresh()

    def stop(self):
        if self.run:
            self.run.stop()

    def closing(self):
        """The tab's closing: stop measuring (VICE carries on)."""
        self._closed = True
        self.stop()
        self.show_figures(None)

    def clear(self):
        if self.profile:
            self.profile.clear()
            self.emulated = 0
            self._refresh()

    def _started(self, run, memory, timing):
        if run is not self.run:
            return False
        self.clock = timing[2]
        self.profile = Profile(self.resolver, memory, timing[1])
        self.state = "running"
        self._refresh()
        return False

    def _batch(self, run, samples, cycles):
        if run is not self.run or self.profile is None:
            return False
        for pc, line in samples:
            self.profile.add(pc, line)
        self.emulated += cycles
        self._dirty = True
        return False

    def _ended(self, run, message):
        if run is not self.run:
            return False
        self.state, self.message = ("stopped" if self.profile else "idle"), message
        self.run = None
        self._refresh()
        return False

    def _tick(self):
        if self._closed:
            return False
        if self._dirty:
            self._dirty = False
            self._refresh()
        return True

    # ------------------------------------------------------------------ showing it
    def _update_buttons(self):
        running = self.state in ("starting", "running")
        self.go.set_sensitive(not running)
        self.stop_button.set_sensitive(running)
        self.reset.set_sensitive(self.state == "running")
        self.copy.set_sensitive(bool(self.profile and self.profile.samples))

    def _status_text(self) -> str:
        p = self.profile
        if self.state == "starting":
            return "Starting VICE, waiting for the program to start…"
        if p is None:
            return self.message
        secs = self.emulated / self.clock
        text = f"{p.samples:,} samples over {secs:.1f} s of the program"
        if self.state == "running":
            text = "Measuring: " + text
        elif self.state == "stopped":
            text = "Stopped: " + text + (f". {self.message}" if self.message else "")
        return text

    def _push_figures(self):
        p = self.profile
        on = self.in_editor.get_active() and p is not None and p.samples > 0
        self.show_figures(p.line_shares() if on else None)

    def _refresh(self, figures: bool = True):
        if figures:
            self._push_figures()
        self._update_buttons()
        self.status.set_text(self._status_text())
        p = self.profile
        self.body.set_visible_child_name("views" if p is not None else "empty")
        if p is None or not p.samples:
            for lb in self.lists.values():
                _clear(lb)
            self.chart.show([], {})
            _clear(self.legend)
            return
        # (only the page that's showing: the others when they're shown)
        page = self.views.get_visible_child_name()
        routines = p.routines()
        colours = {(r.name, r.address): COLOURS[i] for i, r in enumerate(routines[:len(COLOURS)])}
        if page == "routines":
            self._fill(self.lists["routines"], routines, colours, show_code=False)
        elif page == "lines":
            self._fill(self.lists["lines"], p.lines(), {}, show_code=True)
        elif page == "files":
            self._fill(self.lists["files"], p.files(), {}, show_code=False)
        elif page == "frame":
            self._show_frame(p, routines, colours)

    def _show_frame(self, p: Profile, routines: list[Row], colours: dict):
        self.chart.show(p.raster_lines(), colours)
        _clear(self.legend)
        self.legend.append(Gtk.Label(label="The frame, raster line 0 at the top. The shaded band is the "
                                           "screen's 25 rows; hover over a line for its routines.",
                                     wrap=True, xalign=0, css_classes=["dim-label", "caption"]))
        for i, r in enumerate(routines[:len(COLOURS)]):
            self.legend.append(self._legend_row(COLOURS[i], r))
        rest = sum(r.share for r in routines[len(COLOURS):])
        if rest > 0:
            self.legend.append(self._legend_row(OTHER, Row("everything else", rest, 0)))

    @staticmethod
    def _legend_row(colour, row: Row):
        box = Gtk.Box(spacing=6)
        swatch = Gtk.DrawingArea(content_width=12, content_height=12, valign=Gtk.Align.CENTER)
        swatch.set_draw_func(lambda _w, cr, w, h, c=colour: (cr.set_source_rgb(*c), cr.rectangle(0, 0, w, h),
                                                             cr.fill()))
        box.append(swatch)
        box.append(Gtk.Label(label=f"{row.share * 100:.1f}%", width_chars=6, xalign=1,
                             css_classes=["monospace"]))
        box.append(Gtk.Label(label=row.name, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                             tooltip_text=row.name))
        return box

    def _fill(self, lb: Gtk.ListBox, rows: list[Row], colours: dict, show_code: bool):
        _clear(lb)
        top = rows[0].share if rows else 1
        for r in rows[:ROWS]:
            row = Gtk.ListBoxRow(activatable=bool(r.file))
            row.data = r
            box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
            box.append(Gtk.Label(label=f"{r.share * 100:.1f}%", width_chars=6, xalign=1,
                                 css_classes=["monospace"]))
            box.append(ShareBar(r.share / top if top else 0, colours.get((r.name, r.address), COLOURS[0])))
            name = Gtk.Label(label=r.name, xalign=0, width_chars=24, ellipsize=Pango.EllipsizeMode.END,
                             tooltip_text=r.file or None)
            box.append(name)
            if show_code:
                text = self.line_text(r.file, r.line).strip() if r.file else ""
                box.append(Gtk.Label(label=text, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                     css_classes=["monospace"]))
            else:
                box.append(Gtk.Label(label=r.module, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                     css_classes=["dim-label"]))
            if r.address and lb is not self.lists["files"]:
                box.append(Gtk.Label(label=f"${r.address:04X}", css_classes=["monospace", "dim-label"]))
            box.append(Gtk.Label(label=f"{r.samples:,}", width_chars=8, xalign=1, css_classes=["dim-label"],
                                 tooltip_text="Samples"))
            row.set_child(box)
            lb.append(row)
        if len(rows) > ROWS:
            lb.append(Gtk.ListBoxRow(activatable=False, child=Gtk.Label(
                label=f"and {len(rows) - ROWS} more, under 0.1% each" if rows[ROWS].share < 0.001
                else f"and {len(rows) - ROWS} more", css_classes=["dim-label"], margin_top=4, margin_bottom=4)))

    def _activated(self, _lb, row):
        r = getattr(row, "data", None)
        if r and r.file:
            self.open_line(r.file, r.line or 1)

    def _copy(self):
        if self.profile and self.profile.samples:
            Gdk.Display.get_default().get_clipboard().set(
                self.profile.report(self.emulated / self.clock))
